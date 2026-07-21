"""Phase 3-2 驗證：壓縮系統摘要 + 摘要注入 system prompt。

跑法：.venv/bin/python spike/test_summary.py
"""
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import collectors
import config
import llm
import mask
from asktop import AskTop

ok, failed = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok, failed
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name} {detail}")


def fake_procs() -> list[collectors.Proc]:
    return [
        collectors.Proc(101, "lewsi", 91.5, 3.2, "node",
                        "/usr/bin/node server.js --api-key=sk-live-LEAKME123"),
        collectors.Proc(102, "root", 40.0, 1.0, "nginx", "nginx: worker process"),
        collectors.Proc(103, "postgres", 5.0, 62.5, "postgres",
                        "postgres: writer  postgres://admin:hunter2@localhost/db"),
        collectors.Proc(104, "lewsi", 1.0, 0.1, "sshd", "sshd: lewsi@pts/0"),
        collectors.Proc(105, "root", 0.0, 0.0, "systemd", "/sbin/init"),
        collectors.Proc(106, "root", 0.0, 12.0, "java", "java -Xmx4g -jar app.jar"),
    ]


fake_ports = [collectors.Port(80, "tcp", "0.0.0.0", 102, "nginx"),
              collectors.Port(5432, "tcp", "127.0.0.1", 103, "postgres")]

print("1. 摘要內容")
text = collectors.summary(fake_procs(), cpu=37.5, sent=12345.0, recv=987654.0, ports=fake_ports)
print("--- 摘要開始 ---")
print(text)
print("--- 摘要結束 ---")
for field in ("負載", "記憶體", "CPU", "listening", "前 5 名"):
    check(f"含「{field}」", field in text)
check("含 top CPU 的 PID", "101" in text)
check("含 top MEM 的 PID", "103" in text)
cpu_section = text.split("### CPU 前")[1].split("###")[0]
mem_section = text.split("### 記憶體前")[1]
check("CPU 榜依 CPU 由高到低", [l.split()[2] for l in cpu_section.splitlines() if l.startswith("- PID")]
      == ["101", "102", "103", "104", "105"], cpu_section)
check("記憶體榜依 MEM 由高到低（第一名是 postgres）",
      mem_section.splitlines()[1].startswith("- PID 103"), mem_section)
check("榜單只取 5 名（共 6 個 process）", cpu_section.count("- PID") == 5)
check("含全域速率", "K/s" in text or "M/s" in text, text)
check("含 listening port 數", "2" in text)

print("\n2. 摘要中的 cmdline 已遮罩")
check("api key 已遮蔽", "sk-live-LEAKME123" not in text, text)
check("DB 密碼已遮蔽", "hunter2" not in text, text)
check("遮蔽後仍看得出是什麼程式", "server.js" in text and "nginx" in text, text)

print("\n3. 拿不到連線表時如實說明（macOS 非 root）")
no_ports = collectors.summary(fake_procs(), cpu=1.0, sent=0.0, recv=0.0, ports=None)
check("標示連線表不可用而非填 0", "需 root" in no_ports or "無法" in no_ports, no_ports)

print("\n4. 產生成本（不得拖慢 UI）")
procs = collectors.processes()
t0 = time.perf_counter()
for _ in range(20):
    collectors.summary(procs, cpu=1.0, sent=0.0, recv=0.0, ports=fake_ports)
per = (time.perf_counter() - t0) / 20 * 1000
check(f"單次生成 {per:.2f}ms < 20ms（重用既有採集結果，不重新掃 process）", per < 20)

print("\n5. 真實 process 的 cmdline 出境前被遮罩")
proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)",
                         "--api-key=sk-test123", "--db=postgres://u:pw123@h/d"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(0.3)
raw = " ".join(psutil.Process(proc.pid).cmdline())
check("psutil 讀得到含假 key 的 cmdline", "sk-test123" in raw, raw)
check("遮罩後不含 key", "sk-test123" not in mask.cmdline(raw), mask.cmdline(raw))
check("遮罩後不含 DB 密碼", "pw123" not in mask.cmdline(raw), mask.cmdline(raw))
forced = [collectors.Proc(proc.pid, "lewsi", 99.0, 99.0, "python", raw)]
check("摘要含該 process 時亦已遮蔽",
      "sk-test123" not in collectors.summary(forced, cpu=1.0, sent=0.0, recv=0.0, ports=None))

print("\n6. 送出的 system prompt 確實帶上摘要")
sent_payloads: list[dict] = []


async def handler(request: httpx.Request) -> httpx.Response:
    sent_payloads.append(json.loads(request.read()))
    return httpx.Response(200, content=b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                                       b"data: [DONE]\n\n")


class Fake(llm.Client):
    def __init__(self, base_url, api_key, model, transport=None):
        super().__init__(base_url, api_key, model, transport=httpx.MockTransport(handler))


async def e2e() -> None:
    llm.Client = Fake
    app = AskTop({**config.DEFAULTS, "api_key": "sk-test", "model": "test/model"})
    async with app.run_test() as pilot:
        await pilot.pause()
        app.ask("現在系統怎麼樣")
        await app.workers.wait_for_complete()
        await pilot.pause()
    system = sent_payloads[0]["messages"][0]
    check("第一則是 system", system["role"] == "system")
    check("system prompt 帶上系統摘要", "前 5 名" in system["content"], system["content"][:200])
    check("system prompt 帶上主機名與時間", "主機名稱" in system["content"])
    check("system prompt 要求不知道就說不知道", "不知道" in system["content"])
    check("送出內容不含本機任何 API key",
          "sk-test" not in json.dumps(sent_payloads[0], ensure_ascii=False))


asyncio.run(e2e())
proc.terminate()

print(f"\n{ok} 通過 / {failed} 失敗")
sys.exit(1 if failed else 0)
