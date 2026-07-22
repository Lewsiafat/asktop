"""Ports 分頁游標刷新驗證（headless，不需 root、不打網路）。

跑法：.venv/bin/python spike/test_ports.py

monkeypatch collectors.listening_ports 回固定清單，驗證 tick_ports 增量更新後
游標仍固定在原本選中的列（依 proto|addr|port|pid 這個穩定 row key），不漂回頂端。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import collectors
import config
from asktop import AskTop
from textual.widgets import DataTable, TabbedContent

ok, failed = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok, failed
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name} {detail}")


def cfg(**over) -> dict:
    return {**config.DEFAULTS, "api_key": "", "model": "", **over}


def ports(pids: list[int]) -> tuple[list[collectors.Port], int]:
    # port 綁 pid（不綁列序），模擬「port 跟著 process 走」的真實情況
    return ([collectors.Port(port=8000 + p, proto="tcp", addr="0.0.0.0",
                             pid=p, process=f"proc{p}") for p in pids], 0)


async def test_cursor_holds_across_refresh() -> None:
    original = collectors.listening_ports
    collectors.listening_ports = lambda: ports([100, 101, 102, 103, 104])
    try:
        app = AskTop(cfg())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "tab-ports"
            await pilot.pause()
            table = app.query_one("#ports", DataTable)

            table.move_cursor(row=2)          # 選中第三列（pid=102）
            await pilot.pause()
            selected = app.cursor_pid(table)
            check("選到中間列（非頂端）", table.cursor_row == 2 and selected == "tcp|0.0.0.0|8102|102", selected)

            app.tick_ports()                  # 模擬一次刷新（同一份資料）
            await pilot.pause()
            check("刷新後游標 key 不變", app.cursor_pid(table) == selected, app.cursor_pid(table))
            check("刷新後游標未漂回頂端", table.cursor_row == 2, str(table.cursor_row))

            # 移除頂端一列，游標仍跟著 pid=102 這列走
            collectors.listening_ports = lambda: ports([101, 102, 103, 104])
            app.tick_ports()
            await pilot.pause()
            check("上方列消失後游標仍指原列", app.cursor_pid(table) == selected, app.cursor_pid(table))
    finally:
        collectors.listening_ports = original


async def main() -> None:
    await test_cursor_holds_across_refresh()
    print(f"\n{ok} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
