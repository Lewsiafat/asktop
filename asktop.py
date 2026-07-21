"""asktop — 看得到網路、問得了 AI 的 htop。

Phase 1 MVP：process 表格（排序／篩選／kill）、全域流量、port 占用分頁、設定精靈。
Phase 2：per-process 流量。Phase 3：AI 詢問分頁。
"""

import os
import signal
import sys
from collections import deque

import psutil
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label, Markdown, Sparkline, Static, TabbedContent,
    TabPane,
)
from textual.widgets.markdown import MarkdownStream

import collectors
import config
import llm
import tools
from wizard import SetupWizard

PROC_INTERVAL = 2.0   # psutil 採集是主要成本（實測 20–27ms），見 PLAN.md 10.3
NET_INTERVAL = 1.0
HISTORY = 120         # 全域流量 sparkline 保留約 2 分鐘

QUICK_QUESTIONS = ("現在系統怎麼了", "誰在吃 CPU", "誰在吃頻寬", "哪些 port 被誰占用")


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
    #chat { height: 1fr; }
    #chat Markdown { margin: 0 1; }
    .ask-me { color: $text-accent; text-style: bold; margin: 1 1 0 1; }
    .tool-status { color: $text-muted; text-style: italic; margin: 0 1; }
    #quick { height: auto; }
    #quick Button { margin: 0 1 0 0; min-width: 12; }
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
        self.all_procs: list[collectors.Proc] = []   # 未經篩選，供 AI 摘要用
        self.port_rows: list[collectors.Port] | None = None
        self.cpu_total = 0.0
        self.last_rate = (0.0, 0.0)
        self.nethogs = collectors.Nethogs()
        self.flow = False                                  # per-process 流量是否可用
        self.shown_flow: dict[str, tuple[float, float]] = {}
        self.filter = ""
        self.paused = False
        self.sort_col = 2      # 預設依 CPU% 排序
        self.sort_reverse = True
        self.registry = collectors.load_port_registry(cfg["port_registry_path"])
        self.messages: list[dict] = []   # 本次 session 的對話歷史（不含 system）
        self.me = psutil.Process()
        self.me.cpu_percent()
        # 用 callable 而非快照：AI 追問時 tool 要拿到當下的數據，不是開場那份
        self.source = tools.Source(
            procs=lambda: self.all_procs,
            ports=lambda: self.port_rows,
            flow=lambda: self.nethogs.rates() if self.flow else None,
            rate=lambda: self.last_rate,
        )

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
                yield Static("", id="ai-notice", classes="notice")
                yield VerticalScroll(id="chat")
                with Horizontal(id="quick"):
                    for question in QUICK_QUESTIONS:
                        yield Button(question, classes="quick-q")
                yield Input(placeholder="問問題，例如：現在系統怎麼了", id="ask")
        yield Static("", id="status")
        yield Footer()

    # --- AI 對話 ---

    def ai_ready(self) -> bool:
        return bool(config.api_key(self.cfg) and self.cfg.get("model"))

    def refresh_ai_tab(self) -> None:
        """依設定切換「可對話」與「引導設定」兩種狀態。未設定不是錯誤（PLAN.md 第 9 節）。"""
        notice = self.query_one("#ai-notice", Static)
        if not config.api_key(self.cfg):
            notice.update("尚未設定 API Key，按 s 執行設定精靈即可啟用 AI 詢問。")
        elif not self.cfg.get("model"):
            notice.update("已設定 API Key 但未指定 model，按 s 執行設定精靈補上。")
        else:
            notice.update("")
        notice.display = not self.ai_ready()
        self.enable_ask(self.ai_ready())

    def enable_ask(self, enabled: bool) -> None:
        """回覆進行中一律鎖住輸入與快捷問題，避免同時跑兩輪對話。"""
        self.query_one("#ask", Input).disabled = not enabled
        for button in self.query(".quick-q").results(Button):
            button.disabled = not enabled

    def run_tool(self, name: str, arguments: str) -> str:
        return tools.run(name, arguments, self.source)

    def prompt(self) -> str:
        """每次提問都重新組 system prompt——快照要是問題送出當下的，不是開場的。"""
        summary = collectors.summary(
            self.all_procs, cpu=self.cpu_total,
            sent=self.last_rate[0], recv=self.last_rate[1], ports=self.port_rows,
        ) if self.all_procs else None
        return llm.system_prompt(summary)

    @on(Input.Submitted, "#ask")
    def on_ask(self, event: Input.Submitted) -> None:
        question = event.value.strip()
        if not question or not self.ai_ready():
            return
        event.input.value = ""
        self.ask(question)

    @on(Button.Pressed, ".quick-q")
    def on_quick_question(self, event: Button.Pressed) -> None:
        if self.ai_ready():
            self.ask(str(event.button.label))

    @work(exclusive=True)
    async def ask(self, question: str) -> None:
        """送出提問並串流回覆。

        跑在 worker 裡（async，不是 thread）：httpx 等待期間事件迴圈照常跑計時器，
        監控畫面不會因為在等 LLM 而凍結。
        """
        chat = self.query_one("#chat", VerticalScroll)
        self.enable_ask(False)
        await chat.mount(Static(f"❯ {question}", classes="ask-me"))
        chat.anchor()

        # tool 結果只活在這一輪：留進長期歷史會讓下一次追問拿舊快照當現況
        working = [{"role": "system", "content": self.prompt()},
                   *self.messages,
                   {"role": "user", "content": question}]
        client = llm.Client(self.cfg["base_url"], config.api_key(self.cfg), self.cfg["model"])
        reply: Markdown | None = None
        # stream 等第一個 chunk 到了才開：MarkdownStream 的背景 task 若在首次排程前就被
        # stop()，CancelledError 會回頭把這個 worker 一起取消（尚未收到內容就失敗時必踩）
        stream: MarkdownStream | None = None
        answer, error = "", None
        try:
            async for event in client.converse(working, tools.SPECS, self.run_tool, tools.describe):
                if isinstance(event, llm.Status):
                    if stream is not None:
                        await stream.stop()
                        stream, reply = None, None      # 狀態行之後的回覆另起一段
                    await chat.mount(Static(f"⋯ {event.text}", classes="tool-status"))
                    continue
                if reply is None:
                    reply = Markdown()
                    await chat.mount(reply)
                if stream is None:
                    stream = Markdown.get_stream(reply)
                answer += event.text
                await stream.write(event.text)
        except llm.LLMError as exc:
            error = str(exc)
        finally:
            if stream is not None:
                await stream.stop()

        if error or not answer:
            # 失敗的這輪不進歷史，否則後續追問會帶著半截回答
            if reply is None:
                reply = Markdown()
                await chat.mount(reply)
            await reply.update(
                f"{answer}\n\n> ⚠️ {error}" if error and answer else
                f"> ⚠️ {error}" if error else
                "> ⚠️ 模型沒有回傳任何內容，請確認 model id 是否正確。")
        else:
            self.messages += [{"role": "user", "content": question},
                              {"role": "assistant", "content": answer}]
        self.enable_ask(True)
        self.query_one("#ask", Input).focus()

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
        self.refresh_ai_tab()
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
        self.last_rate = (sent, recv)
        # cpu_percent(interval=None) 算的是「距離上次呼叫」的平均，得有人固定呼叫它
        # 才有意義；放在這裡讓 AI 摘要隨時取得到最近 1 秒的數字
        self.cpu_total = psutil.cpu_percent(interval=None)
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
        self.all_procs = collectors.processes()
        fresh = {str(p.pid): p for p in self.all_procs if self.matches(p)}
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
            self.port_rows = None
            table.display = False
            notice.update(
                "無法取得連線表（需 root）。\n"
                "此平台在非 root 下完全拿不到連線資料，請改用 sudo 執行 asktop。"
            )
            return

        self.port_rows = ports
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
            self.refresh_ai_tab()
            self.notify(f"設定已儲存至 {config.config_path()}")

        self.push_screen(SetupWizard(self.cfg), done)


class FirstRun(App):
    """找不到設定檔、或使用者指定 `asktop setup` 時先跑精靈，存檔後再進主畫面。"""

    def __init__(self, cfg: dict | None = None) -> None:
        super().__init__()
        self.cfg = cfg

    def on_mount(self) -> None:
        self.theme = (self.cfg or config.DEFAULTS)["theme"]
        self.push_screen(SetupWizard(self.cfg), self.done)

    def done(self, cfg: dict | None) -> None:
        self.exit(cfg)


def main() -> None:
    cfg = config.load()
    # `asktop setup` 是「修改設定」不是「重新設定」，現有值要帶進精靈（issue #4）；
    # 只有真的沒有設定檔時才從預設值開始
    setup = len(sys.argv) > 1 and sys.argv[1] == "setup"
    if cfg is None or setup:
        cfg = FirstRun(cfg).run()
        if cfg is None:
            return
        config.save(cfg)
    AskTop(cfg).run()


if __name__ == "__main__":
    if os.name == "nt":
        sys.exit("Windows 不在支援範圍內（見 PLAN.md 第 2.3 節）")
    main()
