"""系統資料採集層。與 UI 完全無關，不 import textual（見 PLAN.md 風險 #7）。

Phase 0 實測結論直接影響本層設計（見 PLAN.md 第 10 節）：
- `net_connections()` 只要 3–7ms，不需要可見性驅動採集那類優化
- 非 root 的降級行為分平台：Linux 拿得到連線但多數無 pid，macOS 直接 AccessDenied
- psutil 採集（20–27ms）比表格渲染貴 3–4 倍，要優化就從這裡下手
"""

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

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


def humanize(rate: float) -> str:
    """bytes/s → 人看得懂的字串。"""
    for unit in ("B", "K", "M", "G"):
        if rate < 1024:
            return f"{rate:.0f}{unit}/s" if unit == "B" else f"{rate:.1f}{unit}/s"
        rate /= 1024
    return f"{rate:.1f}T/s"
