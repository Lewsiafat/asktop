"""設定精靈驗證：重跑精靈不得弄丟現有設定（issue #4）。

跑法：.venv/bin/python spike/test_wizard.py
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
import i18n
from asktop import AskTop
from textual.widgets import Input, Label, Static

ok, failed = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok, failed
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name} {detail}")


CONFIGURED = {
    **config.DEFAULTS,
    "model": "anthropic/claude-sonnet-4.5",
    "api_key": "sk-or-v1-EXISTING",
    "theme": "textual-light",
    "port_registry_path": "/srv/projects/port-registry.json",
}


async def open_wizard(app: AskTop, pilot) -> object:
    app.action_setup()
    await pilot.pause()
    return app.screen


async def click_through(wizard, pilot, steps: int = 4) -> None:
    """一路按「下一步」直到儲存。headless 下連點會被吞，直接呼叫 handler。"""
    for _ in range(steps):
        wizard.on_next()
        await pilot.pause()


# --- 1. 輸入框要回填現值 ---

async def test_inputs_prefilled() -> None:
    app = AskTop(dict(CONFIGURED))
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = await open_wizard(app, pilot)
        check("model 輸入框帶入現值",
              wizard.query_one("#model", Input).value == CONFIGURED["model"],
              repr(wizard.query_one("#model", Input).value))
        check("API key 不以明文回填（只提示已設定）",
              wizard.query_one("#api_key", Input).value == "",
              repr(wizard.query_one("#api_key", Input).value))
        wizard.show_step(3)
        await pilot.pause()
        hint = str(wizard.query_one("#key-hint", Static).render())
        check("有說明留空代表保留現有 key（預設英文）", "keep it" in hint, hint)


# --- 2. 一路按下一步不得改動任何設定 ---

async def test_click_through_preserves_everything() -> None:
    app = AskTop(dict(CONFIGURED))
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = await open_wizard(app, pilot)
        await click_through(wizard, pilot)
        for key in ("model", "api_key", "theme", "base_url", "port_registry_path", "provider"):
            check(f"{key} 維持原值",
                  wizard.cfg[key] == CONFIGURED[key],
                  f"{wizard.cfg[key]!r} != {CONFIGURED[key]!r}")


# --- 3. 使用者真的改東西時要生效 ---

async def test_edits_still_apply() -> None:
    app = AskTop(dict(CONFIGURED))
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = await open_wizard(app, pilot)
        wizard.query_one("#model", Input).value = "openai/gpt-4o-mini"
        await pilot.pause()
        await click_through(wizard, pilot)
        check("改過的 model 生效", wizard.cfg["model"] == "openai/gpt-4o-mini", wizard.cfg["model"])
        check("沒動到的 api_key 不受影響", wizard.cfg["api_key"] == CONFIGURED["api_key"])


async def test_new_key_replaces_old() -> None:
    app = AskTop(dict(CONFIGURED))
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = await open_wizard(app, pilot)
        wizard.verified_key = "sk-or-v1-NEW"          # 略過驗證請求，不打網路
        wizard.query_one("#api_key", Input).value = "sk-or-v1-NEW"
        await pilot.pause()
        await click_through(wizard, pilot)
        check("填了新 key 就換掉舊的", wizard.cfg["api_key"] == "sk-or-v1-NEW", wizard.cfg["api_key"])


# --- 4. 「跳過 AI 設定」仍要能清乾淨（那是明確的意圖） ---

async def test_skip_still_clears_ai() -> None:
    app = AskTop(dict(CONFIGURED))
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = await open_wizard(app, pilot)
        wizard.on_skip()
        await pilot.pause()
        check("跳過 AI 設定會清掉 model", wizard.cfg["model"] == "", repr(wizard.cfg["model"]))
        check("跳過 AI 設定會清掉 key", wizard.cfg["api_key"] == "", repr(wizard.cfg["api_key"]))
        check("跳過不影響 theme", wizard.cfg["theme"] == CONFIGURED["theme"])


# --- 5. 空設定檔仍要能從預設值走完（首次啟動情境不能被回填搞壞） ---

async def test_first_run_from_defaults() -> None:
    app = AskTop({**config.DEFAULTS})
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = await open_wizard(app, pilot)
        check("首次啟動 model 輸入框是空的",
              wizard.query_one("#model", Input).value == "",
              repr(wizard.query_one("#model", Input).value))
        wizard.query_one("#model", Input).value = "openai/gpt-4o-mini"
        await pilot.pause()
        await click_through(wizard, pilot)
        check("首次啟動填入的 model 生效", wizard.cfg["model"] == "openai/gpt-4o-mini")


# --- 6. asktop setup 要與按 s 一致（issue #4 的第三個面向） ---

async def test_setup_argv_preloads_config() -> None:
    from asktop import FirstRun
    app = FirstRun(dict(CONFIGURED))
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = app.screen
        check("asktop setup 帶入現有設定，不從預設值重來",
              wizard.query_one("#model", Input).value == CONFIGURED["model"],
              repr(wizard.query_one("#model", Input).value))
        check("asktop setup 也保留 theme", wizard.cfg["theme"] == CONFIGURED["theme"])


# --- 7. 語言步：預設英文，切換即時 retranslate 並記入 cfg ---

async def test_language_step() -> None:
    app = AskTop({**config.DEFAULTS})   # lang 預設 en
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = await open_wizard(app, pilot)
        check("預設英文：provider 標題是英文",
              "provider" in str(wizard.query_one("#lbl-provider", Label).render()).lower(),
              str(wizard.query_one("#lbl-provider", Label).render()))
        wizard.on_lang(SimpleNamespace(index=list(i18n.LANGS).index("zh")))
        await pilot.pause()
        check("切到中文寫入 cfg", wizard.cfg["lang"] == "zh", wizard.cfg["lang"])
        check("切到中文即時 retranslate 標題",
              "服務商" in str(wizard.query_one("#lbl-provider", Label).render()),
              str(wizard.query_one("#lbl-provider", Label).render()))


# --- 8. Provider preset：選擇即帶入對應 base_url，custom 才可自填 ---

async def test_provider_presets() -> None:
    app = AskTop({**config.DEFAULTS})
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = await open_wizard(app, pilot)
        for provider, base in (("openai", "https://api.openai.com/v1"),
                               ("claude", "https://api.anthropic.com/v1"),
                               ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/")):
            wizard.on_provider(SimpleNamespace(index=config.PROVIDER_ORDER.index(provider)))
            await pilot.pause()
            check(f"{provider} 帶入預設 base_url", wizard.cfg["base_url"] == base, wizard.cfg["base_url"])
            check(f"{provider} 的 base_url 欄位唯讀",
                  wizard.query_one("#base_url", Input).disabled)
        wizard.on_provider(SimpleNamespace(index=config.PROVIDER_ORDER.index("custom")))
        await pilot.pause()
        check("custom 才開放自填 base_url",
              not wizard.query_one("#base_url", Input).disabled)


async def main() -> None:
    for test in (
        test_inputs_prefilled,
        test_click_through_preserves_everything,
        test_edits_still_apply,
        test_new_key_replaces_old,
        test_skip_still_clears_ai,
        test_first_run_from_defaults,
        test_setup_argv_preloads_config,
        test_language_step,
        test_provider_presets,
    ):
        print(test.__name__)
        await test()
    print(f"\n{ok} 通過 / {failed} 失敗")
    sys.exit(1 if failed else 0)


asyncio.run(main())
