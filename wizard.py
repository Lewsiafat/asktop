"""首次啟動設定精靈（PLAN.md 第 9 節）。

六個步驟：language / provider / model / API key / theme / confirm。
預設英文，第一步可切語言並即時套用。AI 相關的 provider/model/key 三步可整組跳過，
不擋住監控功能；theme 不可跳過但有預設值。
"""

import httpx
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static

import config
import i18n

STEP_KEYS = ["wiz_s_lang", "wiz_s_provider", "wiz_s_model", "wiz_s_key", "wiz_s_theme", "wiz_s_confirm"]
N_STEPS = len(STEP_KEYS)


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
        i18n.set_lang(self.cfg.get("lang", "en"))   # 帶著現有語言開精靈
        self.step = 0
        self.ai_skipped = False
        self.verified_key = ""
        self._ready = False   # 擋掉 compose 期間 RadioSet 的初始 Changed 事件

    def compose(self) -> ComposeResult:
        provider = self.cfg.get("provider", "openrouter")
        preset = config.PROVIDERS.get(provider, config.PROVIDERS["openrouter"])
        custom = provider == "custom"
        light = self.cfg.get("theme") == "textual-light"

        with Vertical(id="box"):
            yield Static("", id="title")

            with Vertical(id="step-0", classes="step"):
                yield Label(i18n.t("wiz_pick_lang"), id="lbl-lang")
                cur = self.cfg.get("lang", "en")
                yield RadioSet(
                    *(RadioButton(name, value=(code == cur)) for code, name in i18n.LANGS.items()),
                    id="language",
                )

            with Vertical(id="step-1", classes="step"):
                yield Label(i18n.t("wiz_pick_provider"), id="lbl-provider")
                yield RadioSet(
                    *(RadioButton(self._provider_label(code), value=(code == provider))
                      for code in config.PROVIDER_ORDER),
                    id="provider",
                )
                yield Input(preset["base_url"] if not custom else self.cfg.get("base_url", ""),
                            placeholder=i18n.t("wiz_base_ph"), id="base_url", disabled=not custom)

            with Vertical(id="step-2", classes="step"):
                yield Label(i18n.t("wiz_model_label"), id="lbl-model")
                # 回填現值：不填的話按「下一步」會用空字串覆寫掉既有設定（issue #4）
                yield Input(self.cfg.get("model", ""), placeholder=preset["hint"], id="model")

            with Vertical(id="step-3", classes="step"):
                yield Label(i18n.t("wiz_key_label"), id="lbl-key")
                # key 不以明文回填——精靈是拿來改設定的，不是拿來看 key 的
                yield Input(password=True, placeholder=i18n.t("wiz_key_ph"), id="api_key")
                yield Static("", id="key-hint")
                yield Static("", id="verify")

            with Vertical(id="step-4", classes="step"):
                yield Label(i18n.t("wiz_theme_label"), id="lbl-theme")
                yield RadioSet(RadioButton(i18n.t("wiz_theme_dark"), value=not light),
                               RadioButton(i18n.t("wiz_theme_light"), value=light), id="theme")

            with Vertical(id="step-5", classes="step"):
                yield Static("", id="summary")

            with Horizontal(id="buttons"):
                yield Button(i18n.t("btn_back"), id="back", disabled=True)
                yield Button(i18n.t("btn_next"), id="next", variant="primary")
                yield Button(i18n.t("btn_skip"), id="skip")
            yield Static("", id="hint")

    def _provider_label(self, code: str) -> str:
        return i18n.t("wiz_provider_custom") if code == "custom" else config.PROVIDERS[code]["label"]

    def on_mount(self) -> None:
        self._render_hint()
        self._render_key_hint()
        self._ready = True
        self.show_step(0)

    def show_step(self, step: int) -> None:
        self.step = step
        for i in range(N_STEPS):
            self.query_one(f"#step-{i}").display = i == step
        self.query_one("#title", Static).update(f"{step + 1}/{N_STEPS} {i18n.t(STEP_KEYS[step])}")
        self.query_one("#back", Button).disabled = step == 0
        self.query_one("#next", Button).label = i18n.t("btn_save") if step == N_STEPS - 1 else i18n.t("btn_next")
        # 跳過鍵只在 AI 相關的三步（provider/model/key）有意義
        self.query_one("#skip", Button).display = 1 <= step <= 3
        if step == N_STEPS - 1:
            self.query_one("#summary", Static).update(self.summary())

    def _render_hint(self) -> None:
        show = config.api_key({}) and not self.cfg.get("api_key")
        self.query_one("#hint", Static).update(i18n.t("wiz_env_key") if show else "")

    def _render_key_hint(self) -> None:
        self.query_one("#key-hint", Static).update(
            i18n.t("wiz_key_hint_have") if self.cfg.get("api_key") else i18n.t("wiz_key_hint_none")
        )

    def retranslate(self) -> None:
        """語言切換後就地更新所有靜態文案（精靈是唯一支援即時切換的畫面）。"""
        self.query_one("#lbl-lang", Label).update(i18n.t("wiz_pick_lang"))
        self.query_one("#lbl-provider", Label).update(i18n.t("wiz_pick_provider"))
        self.query_one("#lbl-model", Label).update(i18n.t("wiz_model_label"))
        self.query_one("#lbl-key", Label).update(i18n.t("wiz_key_label"))
        self.query_one("#lbl-theme", Label).update(i18n.t("wiz_theme_label"))
        self.query_one("#base_url", Input).placeholder = i18n.t("wiz_base_ph")
        self.query_one("#api_key", Input).placeholder = i18n.t("wiz_key_ph")
        # 只有 custom 選項與 theme 選項的文案隨語言（provider 專有名詞不變）
        provider_btns = list(self.query_one("#provider", RadioSet).query(RadioButton))
        provider_btns[config.PROVIDER_ORDER.index("custom")].label = i18n.t("wiz_provider_custom")
        theme_btns = list(self.query_one("#theme", RadioSet).query(RadioButton))
        theme_btns[0].label = i18n.t("wiz_theme_dark")
        theme_btns[1].label = i18n.t("wiz_theme_light")
        self.query_one("#skip", Button).label = i18n.t("btn_skip")
        self.query_one("#back", Button).label = i18n.t("btn_back")
        self._render_hint()
        self._render_key_hint()
        self.show_step(self.step)   # 重算 title 與 next/save 文字

    def summary(self) -> str:
        key = config.api_key(self.cfg)
        if self.ai_skipped or not key:
            ai = i18n.t("wiz_ai_off")
        else:
            provider = self.cfg["provider"]
            label = self._provider_label(provider)
            if provider == "custom":
                label = f"{label} — {self.cfg.get('base_url', '')}"
            ai = "\n".join([
                i18n.t("wiz_sum_provider", provider=label),
                i18n.t("wiz_sum_model", model=self.cfg["model"] or i18n.t("wiz_model_blank")),
                i18n.t("wiz_sum_key", masked="*" * 6 + key[-4:]),
            ])
        theme = "Dark" if self.cfg["theme"] == "textual-dark" else "Light"
        return "\n".join([ai, i18n.t("wiz_sum_theme", theme=theme), "",
                          i18n.t("wiz_sum_path", path=config.config_path())])

    # --- 事件 ---

    @on(RadioSet.Changed, "#language")
    def on_lang(self, event: RadioSet.Changed) -> None:
        if not self._ready:
            return
        lang = list(i18n.LANGS)[event.index]
        self.cfg["lang"] = lang
        i18n.set_lang(lang)
        self.retranslate()

    @on(RadioSet.Changed, "#provider")
    def on_provider(self, event: RadioSet.Changed) -> None:
        if not self._ready:
            return
        provider = config.PROVIDER_ORDER[event.index]
        self.cfg["provider"] = provider
        preset = config.PROVIDERS[provider]
        custom = provider == "custom"
        base = self.query_one("#base_url", Input)
        base.disabled = not custom
        if not custom:
            self.cfg["base_url"] = preset["base_url"]
            base.value = preset["base_url"]   # 顯示該 provider 的 endpoint（唯讀）
        self.query_one("#model", Input).placeholder = preset["hint"]

    @on(RadioSet.Changed, "#theme")
    def on_theme(self, event: RadioSet.Changed) -> None:
        if not self._ready:
            return
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
        self.show_step(4)   # 跳到 theme

    @on(Button.Pressed, "#next")
    def on_next(self) -> None:
        if self.step == 0:
            self.show_step(1)
        elif self.step == 1:
            provider = self.cfg.get("provider", "openrouter")
            if provider == "custom":
                base = self.query_one("#base_url", Input).value.strip()
                if not base:
                    self.query_one("#hint", Static).update(i18n.t("wiz_custom_need_url"))
                    return
                self.cfg["base_url"] = base
            else:
                self.cfg["base_url"] = config.PROVIDERS[provider]["base_url"]
            self.show_step(2)
        elif self.step == 2:
            self.cfg["model"] = self.query_one("#model", Input).value.strip()
            self.show_step(3)
        elif self.step == 3:
            key = self.query_one("#api_key", Input).value.strip()
            if not key:
                self.show_step(4)  # 沒填就當跳過，不阻塞
                return
            self.cfg["api_key"] = key
            if key == self.verified_key:
                self.show_step(4)  # 驗過了就放行，不重打一次 API
            else:
                self.verify(key)
        elif self.step == 4:
            self.show_step(5)
        else:
            self.dismiss(self.cfg)

    @work(exclusive=True)
    async def verify(self, key: str) -> None:
        """打一個最小成本的請求驗證 key。失敗不阻塞，使用者仍可繼續。"""
        status = self.query_one("#verify", Static)
        status.update(i18n.t("wiz_verifying"))
        self.query_one("#next", Button).disabled = True
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.cfg['base_url'].rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
            ok = resp.status_code == 200
            # 一律不印出 key 或含 key 的回應內容，只留狀態碼
            status.update(i18n.t("wiz_verify_ok") if ok else i18n.t("wiz_verify_bad", code=resp.status_code))
        except httpx.HTTPError as exc:
            status.update(i18n.t("wiz_verify_err", err=type(exc).__name__))
        finally:
            # 驗證結果只是參考，成功失敗都放行——再按一次「下一步」即前進
            self.verified_key = key
            self.query_one("#next", Button).disabled = False
