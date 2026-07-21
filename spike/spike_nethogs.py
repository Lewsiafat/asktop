"""Phase 0 spike：驗證 nethogs trace mode 輸出是否可穩定解析成 per-process 流量。

跑法（需 root）：sudo uv run spike/spike_nethogs.py [秒數]

驗證重點：
1. trace mode 每列能不能可靠拆出 pid（有些列 pid 為 0 或路徑含空白/斜線）
2. 數值單位是不是 KB/s、累計值還是瞬時值
3. 沒有流量的 process 會不會消失（影響表格 join 策略）
"""

import re
import subprocess
import sys
import time

# nethogs -t 每列格式：<program path>/<pid>/<uid>\t<sent>\t<received>
LINE = re.compile(r"^(?P<prog>.+)/(?P<pid>\d+)/(?P<uid>\d+)\t(?P<sent>[\d.]+)\t(?P<recv>[\d.]+)$")


def main(duration: float) -> None:
    proc = subprocess.Popen(
        ["nethogs", "-t", "-d", "1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    parsed, unparsed, refreshes = 0, [], 0
    deadline = time.monotonic() + duration

    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith("Refreshing:"):
                refreshes += 1
            elif m := LINE.match(line):
                parsed += 1
                if parsed <= 10:
                    print(f"  pid={m['pid']:>7} sent={m['sent']:>8} recv={m['recv']:>8}  {m['prog']}")
            else:
                unparsed.append(line)
            if time.monotonic() > deadline:
                break
    finally:
        proc.terminate()
        stderr = proc.stderr.read()

    print(f"\n--- {duration}s 內：refresh {refreshes} 次，解析成功 {parsed} 列，失敗 {len(unparsed)} 列")
    for line in unparsed[:10]:
        print(f"  [解析失敗] {line!r}")
    if stderr.strip():
        print(f"  [stderr] {stderr.strip()[:500]}")

    print("\n結論判讀：refreshes 應約等於秒數；unparsed 若非零要看是雜訊還是真的格式外例外。")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 10)
