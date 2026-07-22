"""AI 可呼叫的六個**唯讀** tool。不 import textual。

硬性約束（PLAN.md 4.2）：**這裡不存在任何寫入或送 signal 的能力**。
AI 只能調查與建議，kill 永遠由人類在 UI 按下確認。新增 tool 前先問一次
「它能改變系統狀態嗎」，答案是 yes 就不該存在。

另外兩條：所有回傳裁切到 MAX_ROWS 列（token 成本與 context 都撐不住整台機器），
所有 cmdline 必經 mask——tool 回傳是系統數據出境的第二個入口。
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psutil

import collectors
import i18n
import mask

MAX_ROWS = 30
CMDLINE_LIMIT = 160


@dataclass
class Source:
    """把「現在的系統狀態」以 callable 形式交給 tools。

    刻意用 callable 而非快照：使用者追問時 tool 必須拿到當下的新數據，
    沿用開場快照等於回答上一分鐘的系統（issue #3 的驗收條件之一）。
    """
    procs: Callable[[], list[collectors.Proc]]
    ports: Callable[[], list[collectors.Port] | None]
    flow: Callable[[], dict[int, tuple[float, float]] | None]
    rate: Callable[[], tuple[float, float]]


SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_top_processes",
            "description": "取得目前資源用量最高的 process。sort_by 可選 cpu、mem、net"
                           "（net 需要 per-process 流量可用：Linux 需 root + nethogs，macOS 需 nettop）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sort_by": {"type": "string", "enum": ["cpu", "mem", "net"]},
                    "limit": {"type": "integer", "description": f"最多 {MAX_ROWS} 筆"},
                },
                "required": ["sort_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_process_detail",
            "description": "取得單一 process 的詳細資訊：完整命令列、狀態、記憶體實際用量、"
                           "執行緒數、啟動時間、父行程、連線數。",
            "parameters": {
                "type": "object",
                "properties": {"pid": {"type": "integer"}},
                "required": ["pid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_connections",
            "description": "取得目前的網路連線。可用 pid 或 state（如 ESTABLISHED、LISTEN）篩選。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {"type": "integer"},
                    "state": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_listening_ports",
            "description": "取得正在 listen 的 port 與擁有它的 process。可指定 port 只查一個。",
            "parameters": {
                "type": "object",
                "properties": {"port": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_net_rates",
            "description": "取得目前網路速率：全域上下行，以及（若可用）流量最高的 process。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_process",
            "description": "以名稱、命令列片段或 PID 搜尋 process。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]

def describe(name: str, arguments: str) -> str:
    """tool call 進行中顯示在對話區的狀態行。文案於呼叫時查，語言切換即生效。"""
    tkey = f"tool_{name}"
    text = i18n.t(tkey) if tkey in i18n.MESSAGES["en"] else i18n.t("tool_generic", name=name)
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        args = {}
    detail = "、".join(f"{k}={v}" for k, v in args.items())
    return f"{text}（{detail}）" if detail else text


def run(name: str, arguments: str, source: Source) -> str:
    """執行 tool 並回傳純文字結果。任何錯誤都轉成給模型看的說明，不往上拋。"""
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return f"參數不是合法 JSON：{arguments[:200]}"
    if not isinstance(args, dict):
        return "參數必須是物件。"
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"沒有名為 {name} 的工具。"
    try:
        return handler(args, source)
    except Exception as exc:                       # noqa: BLE001 —— 工具失敗不該中斷對話
        return f"查詢失敗（{type(exc).__name__}）：{exc}"


def _limit(args: dict) -> int:
    try:
        want = int(args.get("limit", 10))
    except (TypeError, ValueError):
        want = 10
    return max(1, min(want, MAX_ROWS))


def _cut(rows: list[str], total: int) -> str:
    if not rows:
        return "沒有符合的資料。"
    tail = f"\n（共 {total} 筆，只顯示前 {len(rows)} 筆）" if total > len(rows) else ""
    return "\n".join(rows) + tail


def _proc_line(p: collectors.Proc) -> str:
    return (f"PID {p.pid} | {p.name} | {p.user} | CPU {p.cpu}% | MEM {p.mem}% | "
            f"{mask.cmdline(p.cmdline, limit=CMDLINE_LIMIT)}")


def _flow_rows(flow: dict[int, tuple[float, float]], procs: list[collectors.Proc],
               limit: int, skip_idle: bool = False) -> list[str]:
    """把 nethogs 的 pid→速率對映排名成人看得懂的列。

    pid 0 是 nethogs 無法歸屬的流量，必須顯示出來——靜默丟棄會讓 per-process
    加總對不上全域速率，使用者會以為工具在說謊（PLAN.md 10.2 結論 3）。
    """
    by_pid = {p.pid: p for p in procs}
    rows = []
    for pid, (up, down) in sorted(flow.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))[:limit]:
        if skip_idle and not up and not down:
            continue
        if pid == collectors.UNATTRIBUTED:
            who = "未歸屬流量（nethogs 無法對應到 process）"
        elif pid in by_pid:
            who = f"PID {pid} | {by_pid[pid].name} | {by_pid[pid].user}"
        else:
            who = f"PID {pid} | （process 已結束）"
        rows.append(f"{who} | ↑ {collectors.humanize(up)} | ↓ {collectors.humanize(down)}")
    return rows


def _top_processes(args: dict, source: Source) -> str:
    sort_by = str(args.get("sort_by", "cpu"))
    limit = _limit(args)
    procs = source.procs()
    if sort_by == "net":
        flow = source.flow()
        if flow is None:
            return ("per-process 流量不可用（Linux 需 root + nethogs，macOS 需 nettop）。"
                    "只有全域速率可查，請改用 get_net_rates，並向使用者說明無法得知是哪個 process。")
        return _cut(_flow_rows(flow, procs, limit), len(flow))
    key = (lambda p: -p.mem) if sort_by == "mem" else (lambda p: -p.cpu)
    return _cut([_proc_line(p) for p in sorted(procs, key=key)[:limit]], len(procs))


def _process_detail(args: dict, source: Source) -> str:
    pid = args.get("pid")
    if not isinstance(pid, int):
        return "需要整數 pid。"
    # CPU% 取自主畫面那份採集：這裡新建的 psutil.Process 首次呼叫 cpu_percent()
    # 依定義一定回 0.0，直接用會讓 AI 回報「這個 process 沒在吃 CPU」
    live = next((p for p in source.procs() if p.pid == pid), None)
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            info = {
                "PID": pid,
                "名稱": p.name(),
                "使用者": p.username(),
                "狀態": p.status(),
                "CPU%": live.cpu if live else "不明（不在最近一次採集中）",
                "記憶體": f"{p.memory_info().rss / 1024 ** 2:.1f}MB"
                          f"（{round(p.memory_percent(), 1)}%）",
                "執行緒": p.num_threads(),
                "啟動時間": datetime.fromtimestamp(p.create_time()).strftime("%Y-%m-%d %H:%M:%S"),
                "父行程": f"{p.ppid()}",
                "命令列": mask.cmdline(" ".join(p.cmdline()) or p.name(), limit=CMDLINE_LIMIT * 2),
            }
    except psutil.NoSuchProcess:
        return f"PID {pid} 不存在（可能已經結束）。"
    except psutil.AccessDenied:
        return f"沒有權限讀取 PID {pid} 的細節（需要 root）。"
    try:
        info["連線數"] = len(p.net_connections(kind="inet"))
    except (psutil.Error, PermissionError):
        info["連線數"] = "不明（需要 root）"
    return "\n".join(f"{k}：{v}" for k, v in info.items())


def _connections(args: dict, source: Source) -> str:
    pid = args.get("pid")
    state = str(args.get("state", "")).upper()
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError):
        return "沒有權限讀取連線表（此平台需要 root）。請向使用者說明要用 sudo 執行 asktop。"
    names: dict[int, str] = {}
    rows, total = [], 0
    for c in conns:
        if pid is not None and c.pid != pid:
            continue
        if state and c.status != state:
            continue
        total += 1
        if len(rows) >= MAX_ROWS:
            continue
        if c.pid is not None and c.pid not in names:
            try:
                names[c.pid] = psutil.Process(c.pid).name()
            except psutil.Error:
                names[c.pid] = "?"
        local = f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "-"
        remote = f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else "-"
        owner = f"PID {c.pid} {names.get(c.pid, '?')}" if c.pid else "PID 不明（需 root）"
        rows.append(f"{'tcp' if c.type == 1 else 'udp'} | {local} → {remote} | {c.status} | {owner}")
    return _cut(rows, total)


def _listening_ports(args: dict, source: Source) -> str:
    ports = source.ports()
    if ports is None:
        return "目前拿不到連線表（此平台非 root 時完全無法讀取）。請說明需要以 sudo 執行 asktop。"
    want = args.get("port")
    rows = [p for p in ports if want is None or p.port == want]
    if want is not None and not rows:
        return f"port {want} 目前沒有任何 process 在 listen。"
    unknown = sum(1 for p in rows if p.pid is None)
    lines = [f"port {p.port} | {p.proto} | {p.addr} | "
             f"{f'PID {p.pid} {p.process}' if p.pid else 'PID 不明（需 root 才看得到擁有者）'}"
             for p in rows[:MAX_ROWS]]
    note = (f"\n（其中 {unknown} 筆看不到擁有者，因為目前不是 root）" if unknown else "")
    return _cut(lines, len(rows)) + note


def _net_rates(args: dict, source: Source) -> str:
    sent, recv = source.rate()
    out = [f"全域網路速率：↑ {collectors.humanize(sent)} ↓ {collectors.humanize(recv)}"]
    flow = source.flow()
    if flow is None:
        out.append("per-process 流量不可用（Linux 需 root + nethogs，macOS 需 nettop），"
                   "因此無法得知是哪個 process 在用頻寬——請據實說明，不要猜測。")
        return "\n".join(out)
    rows = _flow_rows(flow, source.procs(), MAX_ROWS, skip_idle=True)
    out.append("流量最高的 process：")
    out += [f"- {row}" for row in rows] or ["- 目前所有 process 的流量都是 0。"]
    return "\n".join(out)


def _search_process(args: dict, source: Source) -> str:
    query = str(args.get("query", "")).strip().lower()
    if not query:
        return "需要 query。"
    procs = source.procs()
    hit = [p for p in procs
           if query in p.name.lower() or query in str(p.pid) or query in p.cmdline.lower()]
    return _cut([_proc_line(p) for p in hit[:MAX_ROWS]], len(hit))


_HANDLERS: dict[str, Callable[[dict, Source], str]] = {
    "get_top_processes": _top_processes,
    "get_process_detail": _process_detail,
    "get_connections": _connections,
    "get_listening_ports": _listening_ports,
    "get_net_rates": _net_rates,
    "search_process": _search_process,
}
