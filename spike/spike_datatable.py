"""Phase 0 spike：Textual DataTable 增量更新 vs 整表重建，以及排序劇烈變動下的游標穩定性。

跑法：uv run spike/spike_datatable.py
按鍵：r = 切換 增量 / 整表重建 兩種模式（同畫面比較耗時）、q = 離開

驗證重點：
1. 增量更新（以 PID 為 row key，只改變動的格）耗時是否真的低於 clear + add_rows
2. 依 CPU% 排序時列順序會劇烈變動，**游標是否黏在同一個 process 上**（風險 #9 的核心）
   —— 畫面上「游標 PID」欄位若在你沒操作時自己變號，就是會殺錯 process
3. asktop 自身 CPU% / RSS 是否低到可接受（第 5 節「監控工具不能成為負載」）

注意：整表重建模式下 clear() 會把 cursor_coordinate 重設為 (0,0)，
且 move_cursor 預設 scroll=True 會把視窗拉回游標——游標與捲動位置是獨立的兩件事。
"""

import os
import time

import psutil
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Static

REFRESH_SECONDS = 2.0


def collect() -> dict[str, tuple]:
    """回傳 {pid: (pid, user, cpu%, mem%, name)}，以 pid 字串當 row key。"""
    out = {}
    for p in psutil.process_iter(["pid", "username", "cpu_percent", "memory_percent", "name"]):
        i = p.info
        out[str(i["pid"])] = (
            i["pid"],
            (i["username"] or "?")[:12],
            round(i["cpu_percent"] or 0.0, 1),
            round(i["memory_percent"] or 0.0, 1),
            (i["name"] or "?")[:24],
        )
    return out


class SpikeApp(App):
    BINDINGS = [("q", "quit", "離開"), ("r", "toggle_mode", "切換更新模式")]

    def __init__(self) -> None:
        super().__init__()
        self.me = psutil.Process()
        self.me.cpu_percent()  # 第一次呼叫必定回 0.0，先丟掉
        self.incremental = True
        self.rows: dict[str, tuple] = {}

    def compose(self) -> ComposeResult:
        yield Static("量測中…", id="stats")
        yield DataTable(cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        self.cols = table.add_columns("PID", "使用者", "CPU%", "MEM%", "名稱")
        self.set_interval(REFRESH_SECONDS, self.refresh_table)
        self.refresh_table()

    def action_toggle_mode(self) -> None:
        self.incremental = not self.incremental

    def cursor_pid(self, table: DataTable) -> str | None:
        """游標目前指向哪個 PID——注意這要在動表格之前取，動完之後列索引就失去意義。"""
        try:
            return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:
            return None

    def refresh_table(self) -> None:
        t0 = time.perf_counter()
        fresh = collect()
        collect_ms = (time.perf_counter() - t0) * 1000

        table = self.query_one(DataTable)
        pid = self.cursor_pid(table)
        t1 = time.perf_counter()

        if self.incremental:
            added = removed = updated = 0
            for gone in self.rows.keys() - fresh.keys():
                table.remove_row(gone)
                removed += 1
            for key, row in fresh.items():
                old = self.rows.get(key)
                if old is None:
                    table.add_row(*row, key=key)
                    added += 1
                elif old[2] != row[2] or old[3] != row[3]:
                    # 只有 CPU%/MEM% 會變，PID/使用者/名稱是靜態的，不必碰
                    table.update_cell(key, self.cols[2], row[2])
                    table.update_cell(key, self.cols[3], row[3])
                    updated += 1
            self.rows = fresh
            table.sort(self.cols[2], reverse=True)
            detail = f"+{added} -{removed} ~{updated}"
        else:
            offset = table.scroll_offset
            table.clear()
            # 一樣帶 key，兩種模式才是同基準比較（否則重建模式連 PID 身分都沒有，
            # 游標必定漂移，量到的就不是「重建比較慢」而是「我沒給 key」）
            for key, row in sorted(fresh.items(), key=lambda kv: kv[1][2], reverse=True):
                table.add_row(*row, key=key)
            self.rows = fresh
            table.scroll_to(x=offset.x, y=offset.y, animate=False)
            detail = f"重建 {len(fresh)} 列"

        # 兩種模式都把游標移回原本那個 PID 所在的新位置（不是原本的列號）
        if pid is not None and pid in fresh:
            try:
                table.move_cursor(row=table.get_row_index(pid), scroll=False)
            except Exception:
                pass
        update_ms = (time.perf_counter() - t1) * 1000

        now = self.cursor_pid(table)
        mode = "增量" if self.incremental else "整表重建"
        drift = "" if now == pid else f"  ⚠ 游標從 {pid} 漂到 {now}"
        self.query_one("#stats", Static).update(
            f"[{mode}] {len(fresh)} 列 | 採集 {collect_ms:.0f}ms | 更新 {update_ms:.0f}ms | {detail} | "
            f"游標 PID {now} | 自身 CPU {self.me.cpu_percent():.1f}% | "
            f"RSS {self.me.memory_info().rss / 1e6:.0f}MB{drift}"
        )


if __name__ == "__main__":
    if os.name == "nt":
        print("Windows 不在支援範圍內（見 PLAN.md 第 2.3 節）")
    SpikeApp().run()
