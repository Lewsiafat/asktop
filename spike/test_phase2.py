"""Phase 2 驗證：per-process 流量（需 sudo 執行）。

跑法：cd /home/lewsi/workspace/asktop && sudo .venv/bin/python test_phase2.py
"""
import asyncio, subprocess, time
import collectors, config
from asktop import AskTop
from textual.widgets import DataTable, Static

print("IS_ROOT:", collectors.IS_ROOT, "| nethogs:", collectors.Nethogs.binary())

# 製造一點流量，否則所有數值都是 0 看不出對錯
traffic = None
try:
    traffic = subprocess.Popen(
        ["curl", "-s", "-o", "/dev/null", "https://speed.cloudflare.com/__down?bytes=20000000"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("已在背景下載 20MB 製造流量")
except FileNotFoundError:
    print("找不到 curl，將只量測既有流量（數值可能全為 0）")

n = collectors.Nethogs()
print("啟動:", n.start(), "| error:", n.error)
for i in range(6):
    time.sleep(1)
    r = n.rates()
    top = sorted(r.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))[:3]
    print(f"  {i+1}s 有流量的 pid 數={len(r)} top3=" +
          ", ".join(f"pid{p}:↑{u/1024:.1f}↓{d/1024:.1f}KB/s" for p, (u, d) in top))
un = n.rates().get(collectors.UNATTRIBUTED, (0.0, 0.0))
print("未歸屬流量: ↑%.1f ↓%.1f KB/s" % (un[0]/1024, un[1]/1024))
n.stop()

async def main():
    app = AskTop({**config.DEFAULTS})
    async with app.run_test() as pilot:
        await pilot.pause()
        t = app.query_one("#procs", DataTable)
        print("flow 可用:", app.flow, "| 提示:", str(app.query_one("#flow-notice", Static).render()))
        print("欄位:", [str(c.label) for c in t.columns.values()])
        for _ in range(4):
            await asyncio.sleep(1); app.tick_procs(); app.tick_net(); await pilot.pause()
        app.sort_col, app.sort_reverse = 4, True
        app.tick_procs(); await pilot.pause()
        print("依上行排序前 5 列:")
        for i in range(min(5, t.row_count)):
            print("   ", t.get_row_at(i))
        print("流量列:", str(app.query_one("#rate", Static).render()))
        print("ports:", app.query_one("#ports", DataTable).row_count,
              "| 提示:", str(app.query_one("#ports-notice", Static).render())[:60] or "（無，代表全部有 PID）")
asyncio.run(main())
if traffic: traffic.terminate()
