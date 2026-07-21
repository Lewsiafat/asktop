"""Phase 3-1 驗證：OpenRouter streaming client（不打真 API，用 httpx MockTransport）。

跑法：.venv/bin/python spike/test_llm.py
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import llm

ok, failed = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok, failed
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name} {detail}")


def sse(*lines: str) -> bytes:
    return "".join(f"{line}\n\n" for line in lines).encode()


def transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def collect(client: llm.Client, messages=None) -> list[str]:
    return [chunk async for chunk in client.stream(messages or [{"role": "user", "content": "hi"}])]


# --- 1. 正常 streaming ---

async def test_stream_yields_content_deltas() -> None:
    body = sse(
        'data: {"choices":[{"delta":{"role":"assistant","content":""}}]}',
        'data: {"choices":[{"delta":{"content":"系統"}}]}',
        'data: {"choices":[{"delta":{"content":"正常"}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        "data: [DONE]",
    )
    client = llm.Client("https://x/api/v1", "sk-secret", "m", transport=transport(
        lambda request: httpx.Response(200, content=body)))
    check("依序吐出 content delta", await collect(client) == ["系統", "正常"])


# --- 2. OpenRouter 的 keep-alive 註解行不可當成資料 ---

async def test_ignores_sse_comments() -> None:
    body = sse(": OPENROUTER PROCESSING", 'data: {"choices":[{"delta":{"content":"ok"}}]}', "data: [DONE]")
    client = llm.Client("https://x/api/v1", "sk-secret", "m", transport=transport(
        lambda request: httpx.Response(200, content=body)))
    check("略過 SSE 註解行", await collect(client) == ["ok"])


# --- 3. 請求內容正確 ---

async def test_request_shape() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, content=sse("data: [DONE]"))

    client = llm.Client("https://x/api/v1", "sk-secret", "my-model", transport=transport(handler))
    await collect(client, [{"role": "user", "content": "誰在吃 CPU"}])
    check("打 /chat/completions", seen["url"] == "https://x/api/v1/chat/completions", seen.get("url", ""))
    check("帶 Bearer 授權標頭", seen["auth"] == "Bearer sk-secret")
    check("body 指定 model 且開 stream",
          seen["body"]["model"] == "my-model" and seen["body"]["stream"] is True, str(seen["body"]))
    check("body 原樣帶上 messages",
          seen["body"]["messages"] == [{"role": "user", "content": "誰在吃 CPU"}], str(seen["body"]))


# --- 4. 錯誤處理：不 crash、不外洩 key ---

async def test_http_error_raises_llmerror_without_key() -> None:
    client = llm.Client("https://x/api/v1", "sk-secret", "m", transport=transport(
        lambda request: httpx.Response(401, json={"error": {"message": "No auth credentials found"}})))
    try:
        await collect(client)
    except llm.LLMError as exc:
        msg = str(exc)
        check("401 轉成 LLMError", "401" in msg, msg)
        check("錯誤訊息含 API 回傳原因", "No auth credentials found" in msg, msg)
        check("錯誤訊息不含 API key", "sk-secret" not in msg, msg)
    else:
        check("401 轉成 LLMError", False, "沒有拋出例外")


async def test_network_error_raises_llmerror() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nodename nor servname provided")

    client = llm.Client("https://x/api/v1", "sk-secret", "m", transport=transport(boom))
    try:
        await collect(client)
    except llm.LLMError as exc:
        check("斷網轉成 LLMError", "sk-secret" not in str(exc), str(exc))
    else:
        check("斷網轉成 LLMError", False, "沒有拋出例外")


async def test_broken_json_does_not_crash() -> None:
    body = sse('data: {"choices":[{"delta":{"content":"a"}}]}', "data: {not json", "data: [DONE]")
    client = llm.Client("https://x/api/v1", "sk-secret", "m", transport=transport(
        lambda request: httpx.Response(200, content=body)))
    check("壞掉的 data 行被略過而非中斷", await collect(client) == ["a"])


async def main() -> None:
    for test in (
        test_stream_yields_content_deltas,
        test_ignores_sse_comments,
        test_request_shape,
        test_http_error_raises_llmerror_without_key,
        test_network_error_raises_llmerror,
        test_broken_json_does_not_crash,
    ):
        print(test.__name__)
        await test()
    print(f"\n{ok} 通過 / {failed} 失敗")
    sys.exit(1 if failed else 0)


asyncio.run(main())
