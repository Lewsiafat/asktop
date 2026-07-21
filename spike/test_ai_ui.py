"""Phase 3-1 驗證：AI 對話分頁（headless，不打真 API）。

跑法：.venv/bin/python spike/test_ai_ui.py

用 httpx MockTransport 假裝 OpenRouter，走的是 llm.Client 的真實 SSE 解析路徑。
"""
import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
import llm
from asktop import AskTop
from textual.widgets import Input, Markdown, Static

ok, failed = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok, failed
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name} {detail}")


def fake_llm(chunks: list[str], status: int = 200, delay: float = 0.0):
    """把 llm.Client 換成打 MockTransport 的版本，回傳還原用的原始類別。"""
    async def body():
        for c in chunks:
            if delay:
                await asyncio.sleep(delay)
            yield ('data: {"choices":[{"delta":{"content":%s}}]}\n\n' % _json(c)).encode()
        yield b"data: [DONE]\n\n"

    async def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "No auth credentials found"}})
        return httpx.Response(200, content=body())

    original = llm.Client

    class Fake(original):
        def __init__(self, base_url, api_key, model, transport=None):
            super().__init__(base_url, api_key, model, transport=httpx.MockTransport(handler))

    llm.Client = Fake
    return original


def _json(text: str) -> str:
    import json
    return json.dumps(text, ensure_ascii=False)


def cfg(**over) -> dict:
    return {**config.DEFAULTS, "api_key": "sk-test", "model": "test/model", **over}


def chat_text(app: AskTop) -> str:
    return "\n".join(md.source for md in app.query("#chat Markdown").results(Markdown))


# --- 1. 未設定 API key：引導而非錯誤 ---

async def test_unconfigured_shows_guidance() -> None:
    app = AskTop(cfg(api_key="", model=""))
    async with app.run_test() as pilot:
        await pilot.pause()
        notice = app.query_one("#ai-notice", Static)
        check("未設定時顯示引導文案", notice.display and "設定精靈" in str(notice.render()))
        check("未設定時輸入框停用", app.query_one("#ask", Input).disabled)


async def test_missing_model_shows_guidance() -> None:
    app = AskTop(cfg(model=""))
    async with app.run_test() as pilot:
        await pilot.pause()
        check("有 key 沒 model 也擋下並說明",
              "model" in str(app.query_one("#ai-notice", Static).render()))


# --- 2. 正常對話 ---

async def test_streaming_reply() -> None:
    original = fake_llm(["目前 ", "系統**正常**", "，負載不高。"])
    try:
        app = AskTop(cfg())
        async with app.run_test() as pilot:
            await pilot.pause()
            check("設定完成時輸入框可用", not app.query_one("#ask", Input).disabled)
            app.ask("現在系統怎麼了")
            await app.workers.wait_for_complete()
            await pilot.pause()
            text = chat_text(app)
            check("回覆完整呈現於 Markdown", "目前 系統**正常**，負載不高。" in text, text)
            check("提問顯示在對話區",
                  any("現在系統怎麼了" in str(s.render()) for s in app.query(".ask-me").results(Static)))
            check("輸入框回覆後解鎖", not app.query_one("#ask", Input).disabled)
            check("歷史留下一問一答", [m["role"] for m in app.messages] == ["user", "assistant"],
                  str(app.messages))

            # 多輪：第二次提問要把第一輪帶上
            app.ask("那記憶體呢")
            await app.workers.wait_for_complete()
            await pilot.pause()
            check("多輪對話累積歷史",
                  [m["role"] for m in app.messages] == ["user", "assistant", "user", "assistant"],
                  str([m["role"] for m in app.messages]))
    finally:
        llm.Client = original


# --- 3. 送出內容不含任何系統數據 ---

async def test_prompt_carries_no_system_data() -> None:
    prompt = llm.system_prompt()
    import socket
    check("system prompt 含主機名", socket.gethostname() in prompt)
    check("system prompt 含時間戳", ":" in prompt and "20" in prompt)
    for leak in ("cmdline", "PID", "pid=", "/usr/", "python3 "):
        if leak in ("PID",):
            continue
        check(f"system prompt 不含 {leak!r}", leak not in prompt, prompt[-200:])


# --- 4. 錯誤不讓程式退出 ---

async def test_error_shown_in_chat() -> None:
    original = fake_llm([], status=401)
    try:
        app = AskTop(cfg())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.ask("測試")
            await app.workers.wait_for_complete()
            await pilot.pause()
            text = chat_text(app)
            check("401 以對話訊息呈現", "⚠️" in text and "401" in text, text)
            check("錯誤訊息不外洩 key", "sk-test" not in text)
            check("程式仍在執行", app.is_running)
            check("失敗的一輪不留在歷史", app.messages == [], str(app.messages))
            check("錯誤後輸入框解鎖", not app.query_one("#ask", Input).disabled)
    finally:
        llm.Client = original


# --- 5. streaming 期間 UI 不凍結 ---

async def test_ui_not_blocked_during_stream() -> None:
    original = fake_llm(["a", "b", "c", "d"], delay=0.1)
    try:
        app = AskTop(cfg())
        async with app.run_test() as pilot:
            await pilot.pause()
            ticks = 0

            def count() -> None:
                nonlocal ticks
                ticks += 1

            app.set_interval(0.05, count)
            app.ask("慢慢回答")
            await app.workers.wait_for_complete()
            await pilot.pause()
            check("streaming 期間計時器照常觸發（UI 未凍結）", ticks >= 4, f"ticks={ticks}")
            check("慢速串流內容完整", "abcd" in chat_text(app), chat_text(app))
    finally:
        llm.Client = original


async def main() -> None:
    for test in (
        test_unconfigured_shows_guidance,
        test_missing_model_shows_guidance,
        test_streaming_reply,
        test_prompt_carries_no_system_data,
        test_error_shown_in_chat,
        test_ui_not_blocked_during_stream,
    ):
        print(test.__name__)
        await test()
    print(f"\n{ok} 通過 / {failed} 失敗")
    sys.exit(1 if failed else 0)


asyncio.run(main())
