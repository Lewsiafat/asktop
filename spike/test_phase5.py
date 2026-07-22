"""Phase 5 驗證：issue #5 —— tools.py 的 per-process 流量分支（需 Linux + root + nethogs）。

test_phase2.py 驗到的是 collectors.Nethogs 與 UI 欄位；本檔補的是 tools.py 中
`_flow_rows` / `_net_rates` / `_top_processes(sort_by="net")` 這條「餵給 AI」的路徑——
在 macOS 上永遠走不到（flow() 恆為 None），是 issue #5 唯一沒被真實執行過的程式碼。

作法：節流的 curl 製造一個「知道 pid、知道名字」的下載，看 nethogs 經 tools 出來的
文字有沒有把這個下載正確歸屬回那個 pid。全零資料驗不了歸屬（PLAN.md 10.4 教訓）。

跑法：cd ~/workspace/asktop && sudo .venv/bin/python spike/test_phase5.py
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import collectors
import tools

fails = 0


def check(ok: bool, msg: str) -> None:
    global fails
    print(("  ✓ " if ok else "  ✗ ") + msg)
    if not ok:
        fails += 1


print("IS_ROOT:", collectors.IS_ROOT, "| nethogs:", collectors.Nethogs.binary())
if not collectors.IS_ROOT:
    print("需要 root：sudo .venv/bin/python spike/test_phase5.py")
    sys.exit(1)
if collectors.Nethogs.binary() is None:
    print("找不到 nethogs：sudo apt install nethogs")
    sys.exit(1)

# 節流下載，讓它在整個取樣視窗內持續有流量、且 pid 穩定可辨識。
# 注意 cloudflare speed 端點對 bytes 有上限（300MB 會回 403），50MB 節流到 3MB/s
# ≈16 秒，足夠涵蓋 6 秒取樣視窗又不會爆量。
URL = "https://speed.cloudflare.com/__down?bytes=50000000"
try:
    traffic = subprocess.Popen(
        ["curl", "-s", "--limit-rate", "3M", "-o", "/dev/null", URL],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except FileNotFoundError:
    print("找不到 curl，無法製造流量")
    sys.exit(1)
curl_pid = traffic.pid
print(f"背景 curl pid={curl_pid}（節流 3MB/s 下載 50MB）")

net = collectors.NetRate()
n = collectors.Nethogs()
started = n.start()
print("nethogs 啟動:", started, "| error:", n.error)
check(started, "nethogs 啟動成功")

# 取樣幾秒讓差分穩定。
last_rate = (0.0, 0.0)
for _ in range(6):
    time.sleep(1)
    last_rate = net.sample()

source = tools.Source(
    procs=collectors.processes,
    ports=lambda: None,
    flow=n.rates,
    rate=lambda: last_rate,
)

flow = source.flow()
print("\n有流量的 pid 數:", len(flow) if flow else flow)
check(bool(flow), "flow() 有資料（nethogs 正在產出速率，非降級的 None）")
if last_rate[1] < 100 * 1024:
    print(f"⚠ 全域下行僅 {collectors.humanize(last_rate[1])}，curl 疑似沒下載"
          f"（alive={traffic.poll() is None}）——下面的歸屬斷言會失敗，先查 traffic 生成")

top = tools.run("get_top_processes", '{"sort_by": "net", "limit": 10}', source)
rates_out = tools.run("get_net_rates", "{}", source)
print("\n--- get_top_processes(net) ---")
print(top)
print("\n--- get_net_rates ---")
print(rates_out)

# checkbox 1：nethogs 把下載歸屬到 curl 的那個 pid、名字對得上。
curl_flow = (flow or {}).get(curl_pid)
print(f"\ncurl pid={curl_pid} 的速率: {curl_flow}")
check(curl_flow is not None and curl_flow[1] > 0,
      f"nethogs 把下載歸屬到 curl 的 pid={curl_pid} 且下行 > 0")
check(f"PID {curl_pid}" in top and "curl" in top,
      f"get_top_processes(net) 輸出含 PID {curl_pid} 與名稱 curl（歸屬正確）")

# checkbox 2：pid=0 未歸屬流量若存在，必須出現在輸出而非被靜默丟棄。
un = (flow or {}).get(collectors.UNATTRIBUTED)
if un is not None:
    print(f"未歸屬流量 pid=0: {un}")
    check("未歸屬" in rates_out or "未歸屬" in top,
          "存在 pid=0 未歸屬流量時，輸出有列出（未靜默丟棄）")
else:
    print("本次取樣沒有 pid=0 未歸屬流量（非必然出現，跳過該斷言）")

check(rates_out.startswith("全域網路速率") and "流量最高的 process" in rates_out,
      "get_net_rates 含全域速率 + per-process 排名（走 nethogs 分支而非降級文案）")

# checkbox 3：流量停止後該 pid 歸零。
print("\n停止 curl，等 3 秒看是否歸零…")
traffic.terminate()
try:
    traffic.wait(timeout=5)
except subprocess.TimeoutExpired:
    traffic.kill()
time.sleep(3)
after = n.rates().get(curl_pid, (0.0, 0.0))
print(f"停止後 curl pid={curl_pid} 的速率: {after}")
check(after[1] < 50 * 1024, "下載停止後該 pid 下行歸零（< 50KB/s 殘留）")

n.stop()
print(f"\n{'✗ 有失敗' if fails else '✓ 全過'}：{fails} 失敗")
sys.exit(1 if fails else 0)
