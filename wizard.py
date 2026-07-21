"""首次啟動設定精靈（PLAN.md 第 9 節）。

四個步驟：provider / model / API key / theme。
AI 相關的前三步可整組跳過，不擋住監控功能；theme 不可跳過但有預設值。
"""

import httpx
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static

import config

MODEL_SUGGESTIONS = "anthropic/claude-sonnet-4.5 ／ openai/gpt-4o-mini"
STEP_TITLES = ["1/5 服務商", "2/5 Model", "3/5 API Key", "4/5 外觀", "5/5 確認"]


class SetupWizard(Screen[dict]):
    """回傳完成後的設定 dict。"""

    CSS = """
    SetupWizard { align: center middle; }
    /* 固定高度 + 按鈕 dock 底部：各步驟內容長短不一，若讓框自動伸縮，
       上一步／下一步會隨步驟上下跳動，連續操作時很難瞄準。 */
    #box { width: 72; height: 18; border: round $primary; padding: 1 2; }
    #title { text-style: bold; margin-bottom: 1; }
    .step { height: 1fr; }
    #buttons { height: 3; dock: bottom; }
    Button { margin-right: 1; }
    #hint, #key-hint { color: $text-muted; margin-top: 1; }
    """

    def __init__(self, cfg: dict | None = None) -> None:
        super().__init__()
        self.cfg = dict(cfg or config.DEFAULTS)
        self.step = 0
        self.ai_skipped = False
        self.verified_key = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static(STEP_TITLES[0], id="title")

            with Vertical(id="step-0", classes="step"):
                yield Label("選擇 LLM 服務商：")
                custom = self.cfg.get("provider") == "custom"
                yield RadioSet(
                    RadioButton("OpenRouter（推薦）", value=not custom),
                    RadioButton("自訂 OpenAI-compatible endpoint", value=custom),
                    id="provider",
                )
                yield Input(self.cfg.get("base_url", ""), placeholder="base URL",
                            id="base_url", disabled=not custom)

            with Vertical(id="step-1", classes="step"):
                yield Label("要使用的 model id：")
                # 回填現值：不填的話按「下一步」會用空字串覆寫掉既有設定（issue #4）
                yield Input(self.cfg.get("model", ""), placeholder=MODEL_SUGGESTIONS, id="model")

            with Vertical(id="step-2", classes="step"):
                yield Label("API Key：")
                # key 不以明文回填——精靈是拿來改設定的，不是拿來看 key 的
                yield Input(password=True, placeholder="sk-or-...", id="api_key")
                yield Static("", id="key-hint")
                yield Static("", id="verify")

            with Vertical(id="step-3", classes="step"):
                yield Label("外觀（選擇後立即套用）：")
                light = self.cfg.get("theme") == "textual-light"
                yield RadioSet(RadioButton("Dark（預設）", value=not light),
                               RadioButton("Light", value=light), id="theme")

            with Vertical(id="step-4", classes="step"):
                yield Static("", id="summary")

            with Horizontal(id="buttons"):
                yield Button("上一步", id="back", disabled=True)
                yield Button("下一步", id="next", variant="primary")
                yield Button("跳過 AI 設定", id="skip")
            yield Static("", id="hint")

    def on_mount(self) -> None:
        if config.api_key({}) and not self.cfg.get("api_key"):
            self.query_one("#hint", Static).update(
                "偵測到環境變數 ASKTOP_API_KEY，將優先使用——第 3 步可直接跳過。"
            )
        self.query_one("#key-hint", Static).update(
            "已設定過 key，留空即保留現有的；要換才輸入新的。" if self.cfg.get("api_key")
            else "留空代表暫不設定，日後可再執行 asktop setup。"
        )
        self.show_step(0)

    def show_step(self, step: int) -> None:
        self.step = step
        for i in range(5):
            self.query_one(f"#step-{i}").display = i == step
        self.query_one("#title", Static).update(STEP_TITLES[step])
        self.query_one("#back", Button).disabled = step == 0
        self.query_one("#next", Button).label = "儲存" if step == 4 else "下一步"
        # 跳過鍵只在 AI 相關的前三步有意義
        self.query_one("#skip", Button).display = step <= 2
        if step == 4:
            self.query_one("#summary", Static).update(self.summary())

    def summary(self) -> str:
        key = config.api_key(self.cfg)
        if self.ai_skipped or not key:
            ai = "AI 功能：未啟用（可日後執行 asktop setup 設定）"
        else:
            ai = (
                f"服務商：{self.cfg['provider']}\n"
                f"Model：{self.cfg['model'] or '（未填）'}\n"
                f"API Key：{'*' * 6}{key[-4:]}"
            )
        theme = "Dark" if self.cfg["theme"] == "textual-dark" else "Light"
        return f"{ai}\n外觀：{theme}\n\n設定將寫入 {config.config_path()}（權限 600）"

    # --- 事件 ---

    @on(RadioSet.Changed, "#provider")
    def on_provider(self, event: RadioSet.Changed) -> None:
        custom = event.index == 1
        self.cfg["provider"] = "custom" if custom else "openrouter"
        self.query_one("#base_url", Input).disabled = not custom

    @on(RadioSet.Changed, "#theme")
    def on_theme(self, event: RadioSet.Changed) -> None:
        self.cfg["theme"] = "textual-light" if event.index == 1 else "textual-dark"
        self.app.theme = self.cfg["theme"]  # 即時預覽

    @on(Button.Pressed, "#back")
    def on_back(self) -> None:
        self.show_step(max(0, self.step - 1))

    @on(Button.Pressed, "#skip")
    def on_skip(self) -> None:
        self.ai_skipped = True
        self.cfg["model"] = ""
        self.cfg["api_key"] = ""
        self.show_step(3)

    @on(Button.Pressed, "#next")
    def on_next(self) -> None:
        if self.step == 0:
            base = self.query_one("#base_url", Input).value.strip()
            if self.cfg["provider"] == "custom":
                if not base:
                    self.query_one("#hint", Static).update("自訂 endpoint 需要填 base URL。")
                    return
                self.cfg["base_url"] = base
            self.show_step(1)
        elif self.step == 1:
            self.cfg["model"] = self.query_one("#model", Input).value.strip()
            self.show_step(2)
        elif self.step == 2:
            key = self.query_one("#api_key", Input).value.strip()
            if not key:
                self.show_step(3)  # 沒填就當跳過，不阻塞
                return
            self.cfg["api_key"] = key
            if key == self.verified_key:
                self.show_step(3)  # 驗過了就放行，不重打一次 API
            else:
                self.verify(key)
        elif self.step == 3:
            self.show_step(4)
        else:
            self.dismiss(self.cfg)

    @work(exclusive=True)
    async def verify(self, key: str) -> None:
        """打一個最小成本的請求驗證 key。失敗不阻塞，使用者仍可繼續。"""
        status = self.query_one("#verify", Static)
        status.update("驗證中…")
        self.query_one("#next", Button).disabled = True
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.cfg['base_url'].rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
            ok = resp.status_code == 200
            # 一律不印出 key 或含 key 的回應內容，只留狀態碼
            status.update("✓ 可用，按「下一步」繼續" if ok else f"✗ 驗證失敗（HTTP {resp.status_code}），仍可按「下一步」略過")
        except httpx.HTTPError as exc:
            status.update(f"✗ 連線失敗（{type(exc).__name__}），仍可按「下一步」略過")
        finally:
            # 驗證結果只是參考，成功失敗都放行——再按一次「下一步」即前進
            self.verified_key = key
            self.query_one("#next", Button).disabled = False
