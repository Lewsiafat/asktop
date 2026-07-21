"""OpenRouter（OpenAI-compatible）streaming client。

與 collectors 同一條紀律：**不 import textual**。UI 只消費本模組吐出的字串，
框架換掉也不影響這裡（PLAN.md 風險 #7）。

不引入 openai SDK——httpx 直打，維持 psutil + textual + httpx 三個依賴的目標。
"""

import json
import socket
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx

TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)


ROLE = """你是 asktop 的系統診斷助手，asktop 是一個在終端機執行的系統監控工具。
使用者是這台主機的管理者，正在排查系統狀況。

規則：
- 一律以繁體中文回答，語氣精簡直接，不寒暄。
- 只根據本對話中實際提供給你的數據回答。**沒有拿到的數據就說不知道，絕對不要編造數字、PID 或程式名稱。**
- 你沒有任何可以修改系統的能力（不能 kill process、不能改設定）。需要動手的操作請說明步驟，
  由使用者自己在 asktop 介面或終端機執行。
- 數據中的命令列已經過機密遮罩，`***` 代表被遮蔽的金鑰或密碼，那是正常的，不要當成異常回報。"""

NO_DATA = """- 你目前只有下列主機資訊，沒有任何 process、連線或流量數據。
  使用者問到這些內容時，直接說明你這邊看不到，請他看 asktop 的 Process／Ports 分頁。"""

WITH_SUMMARY = """- 下方系統快照是你唯一的數據來源，且是問題送出當下的瞬時值。
  快照沒寫的東西（例如某個特定 PID 的細節、某個 port 是誰在用、歷史趨勢）你就是不知道，
  請直說「快照裡沒有這項資料」，不要推測，也不要拿前幾輪的舊快照當現況。"""


def system_prompt(summary: str | None = None) -> str:
    """組出 system prompt。

    summary 為 None 時（未提供系統數據）明確告訴模型它什麼都看不到，
    否則它會拿常識瞎編——這是 PLAN.md 風險 #6 的主要對策。
    """
    return "\n".join([
        ROLE,
        NO_DATA if summary is None else WITH_SUMMARY,
        "",
        f"主機名稱：{socket.gethostname()}",
        f"目前時間：{datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}",
        *(["", summary] if summary else []),
    ])


class LLMError(Exception):
    """對外的統一錯誤型別。訊息保證不含 API key，可直接顯示在畫面上。"""


class Client:
    """一次對話請求 = 一次 stream()。不持有 session 狀態，訊息歷史由呼叫端維護。"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._transport = transport   # 測試用 MockTransport 注入點

    async def stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        """逐字吐出回覆內容。任何失敗一律轉成 LLMError，呼叫端不必認得 httpx。"""
        payload = {"model": self.model, "messages": messages, "stream": True}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/completions", json=payload, headers=headers
                ) as response:
                    if response.status_code != 200:
                        raise LLMError(_error_message(response.status_code, await response.aread()))
                    async for line in response.aiter_lines():
                        for chunk in _parse_line(line):
                            yield chunk
        except httpx.HTTPError as exc:
            # 只帶例外類別與訊息：httpx 的 repr 可能帶上 request 物件（含授權標頭）
            raise LLMError(f"連線失敗（{type(exc).__name__}）：{exc}") from None


def _parse_line(line: str) -> list[str]:
    """解析單行 SSE，回傳 0 或 1 段內容。

    非 `data:` 開頭的行（OpenRouter 會週期性送 `: OPENROUTER PROCESSING` keep-alive）
    與解析不出來的 JSON 一律略過——串到一半 crash 比少一個 token 嚴重得多。
    """
    if not line.startswith("data:"):
        return []
    data = line[len("data:"):].strip()
    if not data or data == "[DONE]":
        return []
    try:
        choices = json.loads(data).get("choices") or []
    except json.JSONDecodeError:
        return []
    content = (choices[0].get("delta") or {}).get("content") if choices else None
    return [content] if content else []


def _error_message(status: int, body: bytes) -> str:
    """把 API 的錯誤 body 濃縮成一行。body 是對方回的內容，不含我方 key。"""
    text = body.decode(errors="replace")
    try:
        payload = json.loads(text)
        detail = payload.get("error", {}).get("message") or text
    except json.JSONDecodeError:
        detail = text
    hint = "（API key 無效或未授權）" if status == 401 else ""
    return f"API 回應 {status}{hint}：{detail.strip()[:300]}"
