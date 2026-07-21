"""asktop — 看得到網路、問得了 AI 的 htop。

Phase 1 MVP：process 表格（排序／篩選／kill）、全域流量、port 占用分頁、設定精靈。
per-process 流量（Phase 2）與 AI 詢問（Phase 3）尚未實作。
"""

import os
import signal
import sys
from collections import deque

import psutil
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label, Sparkline, Static, TabbedContent, TabPane,
)

import collectors
import config
from wizard import SetupWizard

PROC_INTERVAL = 2.0   # psutil 採集是主要成本（實測 20–27ms），見 PLAN.md 10.3
NET_INTERVAL = 1.0
HISTORY = 120         # 全域流量 sparkline 保留約 2 分鐘


class KillConfirm(ModalScreen[bool]):
    """確認框綁 PID 不綁列位置——表格每 2 秒重排，綁列號會殺錯（風險 #9）。"""

    CSS = """
    KillConfirm { align: center middle; }
    #box { width: 70; height: auto; border: round $error; padding: 1 2; }
    #cmd { color: $text-muted; margin: 1 0; }
    Button { margin-right: 1; }
    """

    def __init__(self, proc: collectors.Proc) -> None:
        super().__init__()
        self.proc = proc

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label(f"送出 SIGTERM 給 PID {self.proc.pid}（{self.proc.name}）？")
            yield Static(self.proc.cmdline[:300], id="cmd")
            with Horizontal():
                yield Button("取消", id="cancel", variant="primary")
                yield Button("終止", id="ok", variant="error")

    @on(Button.Pressed, "#ok")
    def confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(False)


class AskTop(App):
    TITLE = "asktop"

    CSS = """
    #rate { height: 1; }
    Sparkline { height: 3; margin: 0 1; }
    #filter { margin: 0 1; }
    #status { height: 1; color: $text-muted; }
    .notice { color: $warning; height: auto; padding: 1; }
    """

    BINDINGS = [
        ("q", "quit", "離開"),
        ("k", "kill", "終止"),
        ("/", "focus_filter", "篩選"),
        ("p", "pause", "暫停"),
        ("s", "setup", "設定"),
    ]

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.cfg = cfg
        self.rate = collectors.NetRate()
        self.history: deque[float] = deque([0.0] * HISTORY, maxlen=HISTORY)
        self.rows: dict[str, collectors.Proc] = {}
        self.nethogs = collectors.Nethogs()
        self.flow = False                                  # per-process 流量是否可用
        self.shown_flow: dict[str, tuple[float, float]] = {}
        self.filter = ""
        self.paused = False
        self.sort_col = 2      # 預設依 CPU% 排序
        self.sort_reverse = True
        self.registry = collectors.load_port_registry(cfg["port_registry_path"])
        self.me = psutil.Process()
        self.me.cpu_percent()

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="tab-proc"):
            with TabPane("Process", id="tab-proc"):
                yield Static("流量量測中…", id="rate")
                yield Sparkline([0.0], id="spark")
                yield Static("", id="flow-notice", classes="notice")
                yield Input(placeholder="篩選 process（名稱／PID／cmdline）", id="filter")
                yield DataTable(id="procs", cursor_type="row")
            with TabPane("Ports", id="tab-ports"):
                yield Static("", id="ports-notice", classes="notice")
                yield DataTable(id="ports", cursor_type="row")
            with TabPane("AI", id="tab-ai"):
                yield Static(self.ai_status(), classes="notice")
        yield Static("", id="status")
        yield Footer()

    def ai_status(self) -> str:
        if not config.api_key(self.cfg):
            return "尚未設定 API Key，按 s 執行設定精靈。\n（AI 詢問功能屬 Phase 3，尚未實作）"
        return f"已設定 model：{self.cfg['model'] or '（未填）'}\n（AI 詢問功能屬 Phase 3，尚未實作）"

    def on_mount(self) -> None:
        self.theme = self.cfg["theme"]
        self.flow = self.nethogs.start()
        notice = self.query_one("#flow-notice", Static)
        notice.update(f"per-process 流量未啟用：{self.nethogs.error}" if not self.flow else "")
        notice.display = not self.flow

        procs = self.query_one("#procs", DataTable)
        # 流量欄只在真的拿得到時才建立——填 0 會讓「沒資料」看起來像「沒流量」
        self.cols = procs.add_columns(
            "PID", "使用者", "CPU%", "MEM%", *(("↑KB/s", "↓KB/s") if self.flow else ()), "名稱"
        )
        self.numeric_cols = {2, 3, 4, 5} if self.flow else {2, 3}
        self.query_one("#ports", DataTable).add_columns("Port", "協定", "位址", "PID", "程式", "專案")
        self.set_interval(NET_INTERVAL, self.tick_net)
        self.set_interval(PROC_INTERVAL, self.tick_procs)
        self.set_interval(PROC_INTERVAL, self.tick_ports)
        self.tick_procs()
        self.tick_ports()

    # --- 採集迴圈 ---

    def tick_net(self) -> None:
        if self.paused:
            return
        sent, recv = self.rate.sample()
        self.history.append(sent + recv)
        line = f"↑ {collectors.humanize(sent)}   ↓ {collectors.humanize(recv)}"
        if self.flow:
            # 未歸屬流量必須顯示，否則 per-process 加總對不上全域數字，
            # 使用者會以為工具在說謊（PLAN.md 10.2 結論 3）
            up, down = self.nethogs.rates().get(collectors.UNATTRIBUTED, (0.0, 0.0))
            if up or down:
                line += f"    未歸屬 ↑ {collectors.humanize(up)} ↓ {collectors.humanize(down)}"
        self.query_one("#rate", Static).update(line)
        self.query_one("#spark", Sparkline).data = list(self.history)

    def matches(self, proc: collectors.Proc) -> bool:
        if not self.filter:
            return True
        f = self.filter.lower()
        return f in proc.name.lower() or f in str(proc.pid) or f in proc.cmdline.lower()

    def tick_procs(self) -> None:
        if self.paused:
            return
        fresh = {str(p.pid): p for p in collectors.processes() if self.matches(p)}
        table = self.query_one("#procs", DataTable)
        pid = self.cursor_pid(table)
        rates = self.nethogs.rates() if self.flow else {}

        def kb(p: collectors.Proc) -> tuple[float, float]:
            up, down = rates.get(p.pid, (0.0, 0.0))
            return round(up / 1024, 1), round(down / 1024, 1)

        for gone in self.rows.keys() - fresh.keys():
            table.remove_row(gone)
            self.shown_flow.pop(gone, None)
        for key, p in fresh.items():
            old = self.rows.get(key)
            if old is None:
                table.add_row(p.pid, p.user, p.cpu, p.mem, *(kb(p) if self.flow else ()), p.name, key=key)
                if self.flow:
                    self.shown_flow[key] = kb(p)
            else:
                if (old.cpu, old.mem) != (p.cpu, p.mem):
                    table.update_cell(key, self.cols[2], p.cpu)
                    table.update_cell(key, self.cols[3], p.mem)
                if self.flow and self.shown_flow.get(key) != (now := kb(p)):
                    table.update_cell(key, self.cols[4], now[0])
                    table.update_cell(key, self.cols[5], now[1])
                    self.shown_flow[key] = now
        self.rows = fresh
        table.sort(self.cols[self.sort_col], reverse=self.sort_reverse)

        if pid and pid in fresh:
            table.move_cursor(row=table.get_row_index(pid), scroll=False)
        self.query_one("#status", Static).update(
            f"{len(fresh)} 個 process | 自身 CPU {self.me.cpu_percent():.1f}% | "
            f"{'已暫停（p 恢復）' if self.paused else '執行中'}"
        )

    def tick_ports(self) -> None:
        if self.paused:
            return
        table = self.query_one("#ports", DataTable)
        notice = self.query_one("#ports-notice", Static)
        try:
            ports, unknown = collectors.listening_ports()
        except collectors.ConnectionError_:
            table.display = False
            notice.update(
                "無法取得連線表（需 root）。\n"
                "此平台在非 root 下完全拿不到連線資料，請改用 sudo 執行 asktop。"
            )
            return

        table.display = True
        notice.update(
            f"{unknown} 個 port 的擁有者不明（需 root 才看得到 PID）。" if unknown
            else ""
        )
        notice.display = bool(unknown)
        table.clear()
        for p in ports:
            table.add_row(
                p.port, p.proto, p.addr,
                p.pid if p.pid is not None else "?",
                p.process,
                self.registry.get(p.port, ""),
            )

    # --- 操作 ---

    def cursor_pid(self, table: DataTable) -> str | None:
        try:
            return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:
            return None

    @on(DataTable.HeaderSelected, "#procs")
    def sort_by(self, event: DataTable.HeaderSelected) -> None:
        col = event.column_index
        self.sort_reverse = not self.sort_reverse if col == self.sort_col else col in self.numeric_cols
        self.sort_col = col
        self.tick_procs()

    @on(Input.Changed, "#filter")
    def on_filter(self, event: Input.Changed) -> None:
        self.filter = event.value.strip()
        self.tick_procs()

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_pause(self) -> None:
        self.paused = not self.paused
        self.query_one("#status", Static).update(
            f"{'已暫停（p 恢復）' if self.paused else '執行中'}"
        )

    def action_kill(self) -> None:
        table = self.query_one("#procs", DataTable)
        pid = self.cursor_pid(table)
        proc = self.rows.get(pid) if pid else None
        if proc is None:
            self.notify("請先在 Process 分頁選一列", severity="warning")
            return

        def do_kill(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                os.kill(proc.pid, signal.SIGTERM)
                self.notify(f"已送出 SIGTERM 給 PID {proc.pid}")
            except (ProcessLookupError, PermissionError) as exc:
                self.notify(f"終止失敗：{exc}", severity="error")

        self.push_screen(KillConfirm(proc), do_kill)

    def on_unmount(self) -> None:
        self.nethogs.stop()

    def action_setup(self) -> None:
        def done(cfg: dict | None) -> None:
            if cfg is None:
                return
            self.cfg = cfg
            config.save(cfg)
            self.theme = cfg["theme"]
            self.registry = collectors.load_port_registry(cfg["port_registry_path"])
            self.notify(f"設定已儲存至 {config.config_path()}")

        self.push_screen(SetupWizard(self.cfg), done)


class FirstRun(App):
    """找不到設定檔時先跑精靈，存檔後再進主畫面。"""

    def on_mount(self) -> None:
        self.theme = "textual-dark"
        self.push_screen(SetupWizard(), self.done)

    def done(self, cfg: dict | None) -> None:
        self.exit(cfg)


def main() -> None:
    cfg = config.load()
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        cfg = None
    if cfg is None:
        cfg = FirstRun().run()
        if cfg is None:
            return
        config.save(cfg)
    AskTop(cfg).run()


if __name__ == "__main__":
    if os.name == "nt":
        sys.exit("Windows 不在支援範圍內（見 PLAN.md 第 2.3 節）")
    main()
