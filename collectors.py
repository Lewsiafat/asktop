"""系統資料採集層。與 UI 完全無關，不 import textual（見 PLAN.md 風險 #7）。

Phase 0 實測結論直接影響本層設計（見 PLAN.md 第 10 節）：
- `net_connections()` 只要 3–7ms，不需要可見性驅動採集那類優化
- 非 root 的降級行為分平台：Linux 拿得到連線但多數無 pid，macOS 直接 AccessDenied
- psutil 採集（20–27ms）比表格渲染貴 3–4 倍，要優化就從這裡下手
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psutil

import mask

IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
PLATFORM = sys.platform


@dataclass
class Proc:
    pid: int
    user: str
    cpu: float
    mem: float
    name: str
    cmdline: str


@dataclass
class Port:
    port: int
    proto: str
    addr: str
    pid: int | None
    process: str


def processes() -> list[Proc]:
    out = []
    for p in psutil.process_iter(["pid", "username", "cpu_percent", "memory_percent", "name", "cmdline"]):
        i = p.info
        cmdline = " ".join(i["cmdline"]) if i["cmdline"] else (i["name"] or "")
        out.append(Proc(
            pid=i["pid"],
            user=(i["username"] or "?"),
            cpu=round(i["cpu_percent"] or 0.0, 1),
            mem=round(i["memory_percent"] or 0.0, 1),
            name=(i["name"] or "?"),
            cmdline=cmdline,
        ))
    return out


class NetRate:
    """全域 NIC 流量：對 net_io_counters() 做差分算出每秒速率。"""

    def __init__(self) -> None:
        self._prev = psutil.net_io_counters()
        self._at = time.monotonic()

    def sample(self) -> tuple[float, float]:
        """回傳 (上行 bytes/s, 下行 bytes/s)。"""
        now = psutil.net_io_counters()
        at = time.monotonic()
        elapsed = at - self._at
        if elapsed <= 0:
            return 0.0, 0.0
        sent = max(0, now.bytes_sent - self._prev.bytes_sent) / elapsed
        recv = max(0, now.bytes_recv - self._prev.bytes_recv) / elapsed
        self._prev, self._at = now, at
        return sent, recv


class ConnectionError_(Exception):
    """連線表整個拿不到（macOS 非 root 的情況）。"""


def listening_ports() -> tuple[list[Port], int]:
    """回傳 (listening ports, 無法解析 pid 的筆數)。

    非 root 時 Linux 仍拿得到完整 LISTEN 清單、只是多數沒有 pid；
    macOS 則直接 AccessDenied——兩者要分開處理，不能共用同一套文案。
    """
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError) as exc:
        raise ConnectionError_(str(exc)) from exc

    names: dict[int, str] = {}
    out, unknown = [], 0
    for c in conns:
        if c.status != psutil.CONN_LISTEN or not c.laddr:
            continue
        if c.pid is None:
            unknown += 1
            process = "?"
        else:
            if c.pid not in names:
                try:
                    names[c.pid] = psutil.Process(c.pid).name()
                except psutil.Error:
                    names[c.pid] = "?"
            process = names[c.pid]
        out.append(Port(
            port=c.laddr.port,
            proto="tcp" if c.type == 1 else "udp",
            addr=c.laddr.ip,
            pid=c.pid,
            process=process,
        ))
    out.sort(key=lambda p: p.port)
    return out, unknown


def load_port_registry(path: str) -> dict[int, str]:
    """讀 Lewis 的 port-registry 對照表，標註「這個 port 是哪個專案」。

    注意：registry 的實際格式尚未確認（PLAN.md 3.3 只提到路徑），
    這裡容忍幾種常見形狀，解析不出來就當作沒有，不讓它擋住 port 分頁。
    """
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}

    out: dict[int, str] = {}

    def put(port, name) -> None:
        try:
            out[int(port)] = str(name)
        except (TypeError, ValueError):
            pass

    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict) and "port" in v:      # {"agent-arena": {"port": 8080}}
                put(v["port"], k)
            elif isinstance(v, (int, str)):              # {"8080": "agent-arena"} 或 {"agent-arena": 8080}
                put(k, v) if str(k).isdigit() else put(v, k)
    elif isinstance(data, list):
        for item in data:                                # [{"name": ..., "port": ...}]
            if isinstance(item, dict) and "port" in item:
                put(item["port"], item.get("name", "?"))
    return out


NETHOGS_ROW = re.compile(r"^(?P<prog>.+)/(?P<pid>\d+)/(?P<uid>\d+)\t(?P<sent>[\d.]+)\t(?P<recv>[\d.]+)$")
UNATTRIBUTED = 0  # nethogs 對無法歸屬的流量給 pid 0（程式名 "unknown TCP"）


class Nethogs:
    """per-process 流量（Phase 2 靈魂功能）。包裝 `nethogs -t`，Linux + root 限定。

    Phase 0 實測（PLAN.md 10.2）決定了這裡的兩個關鍵設計：
    1. nethogs trace mode 輸出的是**自啟動以來的累計 KB，不是速率**，必須自行差分
    2. stdout 混雜診斷訊息（Adding local address / Ethernet link detected /
       Unknown connection），濾掉即可，不是格式例外
    """

    NOISE = ("Adding local address", "Ethernet link detected", "Unknown connection:",
             "Waiting for first packet", "creating socket")

    def __init__(self, interval: int = 1) -> None:
        self.interval = interval
        self.error: str | None = None
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._rates: dict[int, tuple[float, float]] = {}   # pid -> (上行, 下行) bytes/s
        self._totals: dict[int, tuple[float, float]] = {}  # pid -> 累計 KB
        self._pending: dict[int, tuple[float, float]] = {}
        self._at = time.monotonic()

    @staticmethod
    def binary() -> str | None:
        # sudo 的 secure_path 通常含 /usr/sbin，但直接跑 root shell 時未必
        return shutil.which("nethogs") or next(
            (p for p in ("/usr/sbin/nethogs", "/usr/bin/nethogs") if os.path.exists(p)), None
        )

    def start(self) -> bool:
        """啟動失敗時把原因寫進 self.error 並回 False——降級不是報錯。"""
        if PLATFORM != "linux":
            self.error = "per-process 流量僅支援 Linux（macOS 需改用 nettop，尚未實作）"
            return False
        binary = self.binary()
        if binary is None:
            self.error = "找不到 nethogs，請安裝：sudo apt install nethogs"
            return False
        if not IS_ROOT:
            self.error = "per-process 流量需要 root，請改用 sudo 執行"
            return False
        try:
            self._proc = subprocess.Popen(
                [binary, "-t", "-d", str(self.interval)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
            )
        except OSError as exc:
            self.error = f"nethogs 啟動失敗：{exc}"
            return False
        threading.Thread(target=self._read, daemon=True).start()
        return True

    def _read(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.rstrip("\n")
            if line.startswith("Refreshing:"):
                self._flush()          # 一個 Refreshing 到下一個之間是一份完整快照
            elif m := NETHOGS_ROW.match(line):
                pid = int(m["pid"])
                sent, recv = float(m["sent"]), float(m["recv"])
                prev = self._pending.get(pid, (0.0, 0.0))
                # 同一 pid 可能因多個網路介面出現多列，累加
                self._pending[pid] = (prev[0] + sent, prev[1] + recv)
            elif line and not line.startswith(self.NOISE):
                pass  # 未知格式：忽略而非中斷，nethogs 版本差異不該讓整個功能掛掉
        with self._lock:
            self.error = "nethogs 已結束"
            self._rates = {}

    def _flush(self) -> None:
        """把累計值差分成速率。"""
        now = time.monotonic()
        elapsed = now - self._at
        if elapsed <= 0 or not self._pending:
            self._pending = {}
            return
        rates = {}
        for pid, total in self._pending.items():
            prev = self._totals.get(pid, (0.0, 0.0))
            # 差分為負代表 counter 重置（process 結束後 pid 重用、nethogs 重啟），
            # 此輪算 0 並以新值當基準，不要輸出負流量
            up = max(0.0, total[0] - prev[0]) * 1024 / elapsed
            down = max(0.0, total[1] - prev[1]) * 1024 / elapsed
            rates[pid] = (up, down)
        with self._lock:
            self._rates = rates
            self._totals = dict(self._pending)
        self._pending = {}
        self._at = now

    def rates(self) -> dict[int, tuple[float, float]]:
        with self._lock:
            return dict(self._rates)

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()


SUMMARY_TOP = 5
SUMMARY_CMDLINE = 90   # 摘要要壓在數百 token，完整 cmdline 動輒上百字元


def summary(procs: list[Proc], cpu: float, sent: float, recv: float,
            ports: list[Port] | None) -> str:
    """壓縮系統摘要，注入 system prompt 打底（PLAN.md 4.1）。

    刻意做成**純格式化**：process／速率／port 都由呼叫端把既有採集結果傳進來，
    不在這裡重掃一次，否則每問一個問題就多付一次 psutil 的錢。
    uptime／load／記憶體是 µs 級的讀取，就地取即可。

    所有 cmdline 一律過 mask——這是系統數據出境的唯一入口。
    """
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    uptime = time.time() - psutil.boot_time()
    try:
        load = "%.2f / %.2f / %.2f（1／5／15 分鐘）" % psutil.getloadavg()
    except (AttributeError, OSError):
        load = "無法取得"

    def line(p: Proc) -> str:
        cmd = mask.cmdline(p.cmdline, limit=SUMMARY_CMDLINE)
        return f"- PID {p.pid} {p.name}（{p.user}）CPU {p.cpu}% / MEM {p.mem}% — {cmd}"

    top_cpu = sorted(procs, key=lambda p: -p.cpu)[:SUMMARY_TOP]
    top_mem = sorted(procs, key=lambda p: -p.mem)[:SUMMARY_TOP]
    if ports is None:
        port_line = "無法取得連線表（此平台需 root 才看得到，目前不是 root）"
    else:
        port_line = f"{len(ports)} 個"

    return "\n".join([
        f"## 系統快照（{datetime.now().astimezone():%Y-%m-%d %H:%M:%S}）",
        f"- 開機至今：{_duration(uptime)}",
        f"- 平均負載：{load}，CPU 核心數 {psutil.cpu_count()}",
        f"- CPU 使用率：{cpu:.1f}%",
        f"- 記憶體：{_gb(mem.used)} / {_gb(mem.total)}（{mem.percent}%）"
        f"，swap {_gb(swap.used)} / {_gb(swap.total)}",
        f"- 全域網路速率：↑ {humanize(sent)} ↓ {humanize(recv)}",
        f"- listening port：{port_line}",
        f"- process 總數：{len(procs)}",
        "",
        f"### CPU 前 {SUMMARY_TOP} 名",
        *[line(p) for p in top_cpu],
        "",
        f"### 記憶體前 {SUMMARY_TOP} 名",
        *[line(p) for p in top_mem],
    ])


def _gb(value: float) -> str:
    return f"{value / 1024 ** 3:.1f}GB"


def _duration(seconds: float) -> str:
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    return (f"{days} 天 " if days else "") + f"{hours} 小時 {minutes} 分"


def humanize(rate: float) -> str:
    """bytes/s → 人看得懂的字串。"""
    for unit in ("B", "K", "M", "G"):
        if rate < 1024:
            return f"{rate:.0f}{unit}/s" if unit == "B" else f"{rate:.1f}{unit}/s"
        rate /= 1024
    return f"{rate:.1f}T/s"
