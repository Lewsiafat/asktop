"""Phase 3-3 驗證：6 個唯讀 tools + agent loop。

跑法：.venv/bin/python spike/test_tools.py
"""
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import collectors
import llm
import tools

ok, failed = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok, failed
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name} {detail}")


def proc(pid: int, name: str, cpu: float = 0.0, mem: float = 0.0, cmd: str = "") -> collectors.Proc:
    return collectors.Proc(pid, "lewsi", cpu, mem, name, cmd or name)


def source(procs=None, ports=None, flow=None, rate=(0.0, 0.0)) -> tools.Source:
    return tools.Source(lambda: procs or [], lambda: ports, lambda: flow, lambda: rate)


def run(name: str, args: dict, src: tools.Source) -> str:
    return tools.run(name, json.dumps(args), src)


print("1. tools 清單本身沒有破壞性能力（硬性約束）")
names = {spec["function"]["name"] for spec in tools.SPECS}
check("剛好六個 tool", names == {
    "get_top_processes", "get_process_detail", "get_connections",
    "get_listening_ports", "get_net_rates", "search_process"}, str(names))
blob = json.dumps(tools.SPECS, ensure_ascii=False).lower()
for danger in ("kill", "terminate", "signal", "write", "delete", "restart", "stop"):
    check(f"tool 描述不提供 {danger!r} 能力", danger not in blob)
src_code = Path(__file__).resolve().parent.parent.joinpath("tools.py").read_text()
for danger in ("os.kill", "send_signal", "terminate()", "subprocess", "open(", "unlink"):
    check(f"tools.py 沒有用到 {danger!r}", danger not in src_code)
check("未知 tool 名稱被擋下", "沒有名為" in tools.run("kill_process", "{}", source()))

print("\n2. 回傳裁切 ≤ 30 列")
many = [proc(i, f"p{i}", cpu=float(i)) for i in range(1, 101)]
out = run("get_top_processes", {"sort_by": "cpu", "limit": 999}, source(procs=many))
check(f"limit 超過上限仍只回 {tools.MAX_ROWS} 列",
      out.count("PID ") == tools.MAX_ROWS, str(out.count("PID ")))
check("有標示被裁切", "共 100 筆" in out, out[-80:])
check("依 CPU 由高到低", out.splitlines()[0].startswith("PID 100"), out.splitlines()[0])
hits = run("search_process", {"query": "p"}, source(procs=many))
check("search_process 同樣裁切", hits.count("PID ") == tools.MAX_ROWS)
ports = [collectors.Port(1000 + i, "tcp", "0.0.0.0", i, f"p{i}") for i in range(60)]
check("get_listening_ports 同樣裁切",
      run("get_listening_ports", {}, source(ports=ports)).count("port ") <= tools.MAX_ROWS + 1)

print("\n3. tool 回傳的 cmdline 已遮罩")
leaky = [proc(7, "node", cpu=9.0, cmd="node app.js --api-key=sk-live-LEAKME --db=postgres://u:pw1@h/d")]
for tool, args in (("get_top_processes", {"sort_by": "cpu"}), ("search_process", {"query": "node"})):
    out = run(tool, args, source(procs=leaky))
    check(f"{tool} 遮住 api key", "sk-live-LEAKME" not in out, out)
    check(f"{tool} 遮住 DB 密碼", "pw1@" not in out, out)
    check(f"{tool} 仍看得出程式", "app.js" in out, out)

print("\n4. port 查詢回真實 PID／程式名")
real = collectors.Port(8080, "tcp", "0.0.0.0", 4242, "gunicorn")
out = run("get_listening_ports", {"port": 8080}, source(ports=[real]))
check("查得到 8080 的擁有者", "4242" in out and "gunicorn" in out, out)
check("查不到的 port 明說沒有",
      "沒有任何 process" in run("get_listening_ports", {"port": 9999}, source(ports=[real])))
check("拿不到連線表時說明需 root",
      "sudo" in run("get_listening_ports", {}, source(ports=None)))

print("\n5. 頻寬問題：沒有 nethogs 時如實說明只有全域數據")
out = run("get_net_rates", {}, source(rate=(1024.0, 2048.0), flow=None))
check("回全域速率", "1.0K/s" in out and "2.0K/s" in out, out)
check("明說無法歸屬到 process", "不可用" in out and "不要猜測" in out, out)
check("sort_by=net 但無 nethogs 時導向全域數據",
      "get_net_rates" in run("get_top_processes", {"sort_by": "net"}, source(flow=None)))

out = run("get_net_rates", {}, source(
    procs=[proc(11, "curl"), proc(12, "sshd")],
    flow={11: (100.0, 900000.0), 12: (10.0, 10.0), collectors.UNATTRIBUTED: (5.0, 5.0)},
    rate=(115.0, 900015.0)))
check("有 nethogs 時列出 per-process 流量", "PID 11 | curl" in out, out)
check("流量最高的排前面", out.index("PID 11") < out.index("PID 12"), out)
check("未歸屬流量不被靜默丟棄", "未歸屬" in out, out)

print("\n6. get_process_detail 打的是真實 process")
me = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "--token=abc123secret"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(0.3)
detail = run("get_process_detail", {"pid": me.pid},
             source(procs=[proc(me.pid, "python", cpu=17.5)]))
check("回傳真實 PID 的細節", f"PID：{me.pid}" in detail, detail)
check("CPU% 取自既有採集而非恆為 0（新建 psutil.Process 首呼叫必回 0.0）",
      "17.5" in detail, detail)
check("不在採集結果中的 process 標明 CPU 不明",
      "不明" in run("get_process_detail", {"pid": me.pid}, source()))
check("含啟動時間與執行緒數", "啟動時間" in detail and "執行緒" in detail)
check("detail 的 cmdline 也遮罩", "abc123secret" not in detail, detail)
me.terminate()
check("不存在的 PID 給明確訊息", "不存在" in run("get_process_detail", {"pid": 999999}, source()))
check("壞掉的參數不炸", "查詢失敗" in tools.run("get_process_detail", '{"pid": "abc"}', source())
      or "需要整數" in tools.run("get_process_detail", '{"pid": "abc"}', source()))
check("非 JSON 參數不炸", "不是合法 JSON" in tools.run("get_top_processes", "{oops", source()))

print("\n7. 狀態行")
check("狀態行含中文說明", "listening" in tools.describe("get_listening_ports", "{}"))
check("狀態行帶上參數", "8080" in tools.describe("get_listening_ports", '{"port": 8080}'))


# --- 8. agent loop ---

def sse(*events: str) -> bytes:
    return "".join(f"data: {e}\n\n" for e in events).encode() + b"data: [DONE]\n\n"


def tool_call_body(name: str, args: str = "{}") -> bytes:
    return sse(
        json.dumps({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "function": {"name": name}}]}}]}),
        json.dumps({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": args[:3]}}]}}]}),
        json.dumps({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": args[3:]}}]}}]}),
    )


def text_body(text: str) -> bytes:
    return sse(json.dumps({"choices": [{"delta": {"content": text}}]}))


async def loop_with(responder, src: tools.Source) -> tuple[str, list[str], list[dict]]:
    requests: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        requests.append(payload)
        return httpx.Response(200, content=responder(len(requests), payload))

    client = llm.Client("https://x/v1", "sk-secret", "m", transport=httpx.MockTransport(handler))
    messages: list[dict] = [{"role": "user", "content": "誰在占 8080"}]
    text, statuses = "", []
    async for event in client.converse(messages, tools.SPECS,
                                       lambda n, a: tools.run(n, a, src), tools.describe):
        if isinstance(event, llm.Status):
            statuses.append(event.text)
        else:
            text += event.text
    return text, statuses, requests


async def test_tool_round_trip() -> None:
    src = source(ports=[collectors.Port(8080, "tcp", "0.0.0.0", 4242, "gunicorn")])

    def responder(n: int, payload: dict) -> bytes:
        if n == 1:
            return tool_call_body("get_listening_ports", '{"port": 8080}')
        return text_body("8080 由 PID 4242 gunicorn 占用。")

    text, statuses, requests = await loop_with(responder, src)
    check("模型呼叫 tool 後拿到結果並作答", "4242" in text, text)
    check("進行中顯示狀態行", any("listening" in s for s in statuses), str(statuses))
    check("第二次請求帶上 tool 結果",
          any(m["role"] == "tool" and "gunicorn" in m["content"] for m in requests[1]["messages"]),
          str(requests[1]["messages"][-1]))
    check("tool 訊息帶正確的 tool_call_id",
          [m for m in requests[1]["messages"] if m["role"] == "tool"][0]["tool_call_id"] == "call_1")


async def test_round_limit() -> None:
    """模型無限想查下去時，loop 必須停在 4 輪並逼它作答。"""
    calls = {"n": 0}

    def counting_tool(name: str, arguments: str) -> str:
        calls["n"] += 1
        return "還是沒查到，再查一次別的。"

    requests: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        requests.append(payload)
        if "tools" in payload:                       # 只要還給 tools 就繼續要求呼叫
            return httpx.Response(200, content=tool_call_body("get_net_rates"))
        return httpx.Response(200, content=text_body("查不出來，以目前資訊只能說明到這裡。"))

    client = llm.Client("https://x/v1", "sk-secret", "m", transport=httpx.MockTransport(handler))
    messages: list[dict] = [{"role": "user", "content": "一直查"}]
    text = "".join([e.text async for e in client.converse(
        messages, tools.SPECS, counting_tool, tools.describe) if isinstance(e, llm.Text)])
    check(f"tool 呼叫停在 {llm.MAX_TOOL_ROUNDS} 輪", calls["n"] == llm.MAX_TOOL_ROUNDS, str(calls))
    check("最後一次請求不再提供 tools", "tools" not in requests[-1], str(list(requests[-1])))
    check("超過上限後仍以現有資訊作答", "查不出來" in text, text)


async def test_followup_refetches() -> None:
    """追問要拿到新數據，不能沿用第一次的快照。"""
    versions = [[proc(1, "old-process", cpu=1.0)], [proc(2, "new-process", cpu=2.0)]]
    calls = {"n": 0}

    def shifting() -> list[collectors.Proc]:
        current = versions[min(calls["n"], 1)]
        calls["n"] += 1
        return current

    src = tools.Source(shifting, lambda: None, lambda: None, lambda: (0.0, 0.0))

    def responder(n: int, payload: dict) -> bytes:
        return (tool_call_body("get_top_processes", '{"sort_by": "cpu"}') if n % 2 == 1
                else text_body("（已回報）"))

    _, _, first = await loop_with(responder, src)
    _, _, second = await loop_with(responder, src)
    first_tool = [m for m in first[1]["messages"] if m["role"] == "tool"][0]["content"]
    second_tool = [m for m in second[1]["messages"] if m["role"] == "tool"][0]["content"]
    check("第一次拿到當時的資料", "old-process" in first_tool, first_tool)
    check("追問時重新查詢而非沿用舊快照", "new-process" in second_tool, second_tool)


async def main() -> None:
    print("\n8. agent loop")
    for test in (test_tool_round_trip, test_round_limit, test_followup_refetches):
        await test()
    print(f"\n{ok} 通過 / {failed} 失敗")
    sys.exit(1 if failed else 0)


asyncio.run(main())
