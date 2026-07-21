"""Phase 0 spike：量化 root 與無 root 下 psutil 拿得到多少資料。

跑法（兩次，比對輸出）：
    uv run spike/spike_psutil_root.py
    sudo uv run spike/spike_psutil_root.py

驗證重點：
1. net_connections() 無 root 時是整個爆 AccessDenied，還是只回傳自己的連線
2. 有多少連線的 pid 是 None（拿不到 pid 就無法 join 到 process 表格）
3. process 的 cmdline / username 在無 root 下失敗率多高（影響 kill 確認框與 AI 摘要）
4. 全表掃描一次要多久（決定第 5 節的輪詢間隔是否站得住）
"""

import os
import time

import psutil


def main() -> None:
    print(f"euid={os.geteuid()}  {'(root)' if os.geteuid() == 0 else '(一般使用者)'}\n")

    t0 = time.perf_counter()
    try:
        conns = psutil.net_connections(kind="inet")
    except psutil.AccessDenied:
        print("net_connections(): AccessDenied — 這個模式下完全拿不到連線表")
        conns = []
    conn_ms = (time.perf_counter() - t0) * 1000

    with_pid = sum(1 for c in conns if c.pid is not None)
    listening = sum(1 for c in conns if c.status == psutil.CONN_LISTEN)
    print(f"net_connections(): {len(conns)} 條，{with_pid} 條有 pid，{listening} 條 LISTEN，耗時 {conn_ms:.0f}ms")

    t0 = time.perf_counter()
    total = denied_cmdline = denied_user = 0
    for p in psutil.process_iter(["username", "cmdline"]):
        total += 1
        if p.info["cmdline"] is None:
            denied_cmdline += 1
        if p.info["username"] is None:
            denied_user += 1
    proc_ms = (time.perf_counter() - t0) * 1000

    print(f"process_iter(): {total} 個 process，cmdline 取不到 {denied_cmdline} 個，"
          f"username 取不到 {denied_user} 個，耗時 {proc_ms:.0f}ms")

    print("\n結論判讀：若無 root 下 with_pid 遠小於 root，port 分頁就必須標示"
          "「部分連線的擁有者不明」而不是假裝資料完整。耗時若超過輪詢間隔就要改採樣策略。")


if __name__ == "__main__":
    main()
