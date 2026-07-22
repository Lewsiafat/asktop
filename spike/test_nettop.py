"""Phase 4 驗證：macOS per-process 流量（`collectors.Nettop`，需 macOS，**不需 root**）。

對稱於 Linux 的 spike/test_phase5.py：以節流 curl 製造一個「知道 pid、知道名字」的
下載，看 nettop 經 tools 出來的文字有沒有把它正確歸屬回那個 pid。nettop 不需要 root，
所以這支在一般帳號就能跑。

跑法：.venv/bin/python spike/test_nettop.py
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


print("PLATFORM:", collectors.PLATFORM, "| nettop:", collectors.Nettop.binary())
if collectors.PLATFORM != "darwin":
    print("此測試僅適用 macOS（Linux 請跑 spike/test_phase5.py）")
    sys.exit(1)
if collectors.Nettop.binary() is None:
    print("找不到 nettop（macOS 應內建）")
    sys.exit(1)

check(isinstance(collectors.flow_monitor(), collectors.Nettop),
      "flow_monitor() 在 macOS 回傳 Nettop")

# 節流下載，讓它在整個取樣視窗內持續有流量、且 pid 穩定可辨識。
# cloudflare speed 端點 bytes 有上限（>300MB 回 403），50MB 節流到 3MB/s ≈16 秒。
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
mon = collectors.Nettop()
started = mon.start()
print("nettop 啟動:", started, "| error:", mon.error)
check(started, "nettop 啟動成功（不需 root）")

last_rate = (0.0, 0.0)
for _ in range(6):
    time.sleep(1)
    last_rate = net.sample()

source = tools.Source(
    procs=collectors.processes,
    ports=lambda: None,
    flow=mon.rates,
    rate=lambda: last_rate,
)

flow = source.flow()
print("\n有流量的 pid 數:", len(flow) if flow else flow)
check(bool(flow), "flow() 有資料（nettop 正在產出速率）")
if last_rate[1] < 100 * 1024:
    print(f"⚠ 全域下行僅 {collectors.humanize(last_rate[1])}，curl 疑似沒下載"
          f"（alive={traffic.poll() is None}）——下面的歸屬斷言會失敗，先查 traffic 生成")

top = tools.run("get_top_processes", '{"sort_by": "net", "limit": 10}', source)
rates_out = tools.run("get_net_rates", "{}", source)
print("\n--- get_top_processes(net) ---")
print(top)
print("\n--- get_net_rates ---")
print(rates_out)

# nettop 把下載歸屬到 curl 的那個 pid、名字（由 psutil 解析）對得上。
curl_flow = (flow or {}).get(curl_pid)
print(f"\ncurl pid={curl_pid} 的速率: {curl_flow}")
check(curl_flow is not None and curl_flow[1] > 0,
      f"nettop 把下載歸屬到 curl 的 pid={curl_pid} 且下行 > 0")
check(f"PID {curl_pid}" in top and "curl" in top,
      f"get_top_processes(net) 輸出含 PID {curl_pid} 與名稱 curl（歸屬正確）")

check(rates_out.startswith("全域網路速率") and "流量最高的 process" in rates_out,
      "get_net_rates 含全域速率 + per-process 排名（走流量分支而非降級文案）")

# 流量停止後該 pid 最終歸零（nettop 1s 取樣，terminate 後可能還有一兩個樣本帶尾端
# 流量，所以輪詢「最終降到 0」而非要求立刻 0——永遠殘留才是真的 bug）。
print("\n停止 curl，輪詢是否最終歸零…")
traffic.terminate()
try:
    traffic.wait(timeout=5)
except subprocess.TimeoutExpired:
    traffic.kill()
after = (0.0, 0.0)
for _ in range(8):
    time.sleep(1)
    after = mon.rates().get(curl_pid, (0.0, 0.0))
    if after[1] < 50 * 1024:
        break
print(f"停止後 curl pid={curl_pid} 的速率: {after}")
check(after[1] < 50 * 1024, "下載停止後該 pid 下行最終歸零（< 50KB/s 殘留）")

mon.stop()
print(f"\n{'✗ 有失敗' if fails else '✓ 全過'}：{fails} 失敗")
sys.exit(1 if fails else 0)
