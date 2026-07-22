"""OpenRouter（OpenAI-compatible）streaming client。

與 collectors 同一條紀律：**不 import textual**。UI 只消費本模組吐出的字串，
框架換掉也不影響這裡（PLAN.md 風險 #7）。

不引入 openai SDK——httpx 直打，維持 psutil + textual + httpx 三個依賴的目標。
"""

import json
import socket
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

import i18n

TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)

# tool call 輪數上限（PLAN.md 4.1）。超過就收回 tools，逼模型用手上的資料作答，
# 而不是無限往下查——延遲與成本都是使用者在付。
MAX_TOOL_ROUNDS = 4


@dataclass
class Text:
    """一段回覆內容。"""
    text: str


@dataclass
class Status:
    """tool call 進行中的狀態行，只給 UI 顯示，不進對話歷史。"""
    text: str


ROLE = """你是 asktop 的系統診斷助手，asktop 是一個在終端機執行的系統監控工具。
使用者是這台主機的管理者，正在排查系統狀況。

規則：
- {reply_rule}
- 只根據系統快照與工具回傳的數據回答。**查不到的就說不知道，絕對不要編造數字、PID 或程式名稱。**
- 你沒有任何可以修改系統的能力（不能 kill process、不能改設定）。需要動手的操作請說明步驟，
  由使用者自己在 asktop 介面或終端機執行。
- 數據中的命令列已經過機密遮罩，`***` 代表被遮蔽的金鑰或密碼，那是正常的，不要當成異常回報。"""

DATA_RULES = """- 你有一組唯讀查詢工具。系統快照只是打底，**快照沒有的細節一律用工具查**：
  某個 PID 的詳情、某個 port 是誰在用、目前有哪些連線、誰在吃頻寬——這些都查得到，
  不要用「我看不到」搪塞，也不要憑快照推測。
- 使用者追問時重新呼叫工具取最新數據，不要拿前幾輪的舊結果當現況。
- 只引用快照與工具實際回傳的內容。工具回報拿不到（例如需要 root、沒有 nethogs）時，
  據實轉述那個限制，不要改用猜的補上。"""

NO_SUMMARY = "（系統快照尚未就緒，需要任何系統數據請直接呼叫工具。）"


def system_prompt(summary: str | None = None) -> str:
    """組出 system prompt。

    數據紀律是 PLAN.md 風險 #6（AI 幻覺數字）的主要對策：講清楚「什麼要用工具查」
    跟「不知道就說不知道」一樣重要——只講後者，模型會把查得到的東西也回答成不知道。
    """
    return "\n".join([
        ROLE.format(reply_rule=i18n.t("ai_reply_rule")),
        DATA_RULES,
        "",
        f"主機名稱：{socket.gethostname()}",
        f"目前時間：{datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}",
        "",
        summary or NO_SUMMARY,
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

    async def stream(self, messages: list[dict[str, Any]],
                     tool_specs: list[dict] | None = None,
                     calls_out: list[dict] | None = None) -> AsyncIterator[str]:
        """逐字吐出回覆內容。任何失敗一律轉成 LLMError，呼叫端不必認得 httpx。

        模型改為呼叫 tool 時內容會是空的，累積出來的 tool call 放進 `calls_out`。
        """
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "stream": True}
        if tool_specs:
            payload["tools"] = tool_specs
        headers = {"Authorization": f"Bearer {self.api_key}"}
        calls: dict[int, dict] = {}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/completions", json=payload, headers=headers
                ) as response:
                    if response.status_code != 200:
                        raise LLMError(_error_message(response.status_code, await response.aread()))
                    async for line in response.aiter_lines():
                        delta = _parse_line(line)
                        if delta is None:
                            continue
                        if delta.get("tool_calls"):
                            _accumulate(calls, delta["tool_calls"])
                        if content := delta.get("content"):
                            yield content
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # InvalidURL 不是 HTTPError 的子類，但設定檔的 base_url 打錯就會拋它
            # 只帶例外類別與訊息：httpx 的 repr 可能帶上 request 物件（含授權標頭）
            raise LLMError(f"連線失敗（{type(exc).__name__}）：{exc}") from None
        if calls_out is not None:
            calls_out.extend(calls[i] for i in sorted(calls))

    async def converse(self, messages: list[dict[str, Any]], tool_specs: list[dict],
                       run_tool: Callable[[str, str], str],
                       describe: Callable[[str, str], str],
                       ) -> AsyncIterator[Text | Status]:
        """跑完整個 agent loop，逐步吐出 Text／Status 事件。

        `messages` 會就地累積 assistant 與 tool 訊息——一輪對話結束後，呼叫端可以
        自行決定要保留哪些進長期歷史（asktop 只留最後的文字回覆，避免下一輪追問時
        模型拿舊的 tool 結果當現況）。
        """
        for round_ in range(MAX_TOOL_ROUNDS + 1):
            # 最後一輪不給 tools：逼模型用手上的資料作答，而不是再查一次
            specs = None if round_ == MAX_TOOL_ROUNDS else tool_specs
            calls: list[dict] = []
            text = ""
            async for chunk in self.stream(messages, specs, calls):
                text += chunk
                yield Text(chunk)
            if not calls:
                if text:
                    messages.append({"role": "assistant", "content": text})
                return
            messages.append({"role": "assistant", "content": text or None, "tool_calls": calls})
            for call in calls:
                name = call["function"]["name"]
                arguments = call["function"]["arguments"]
                yield Status(describe(name, arguments))
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": run_tool(name, arguments)})


def _parse_line(line: str) -> dict[str, Any] | None:
    """解析單行 SSE，回傳 delta 物件或 None。

    非 `data:` 開頭的行（OpenRouter 會週期性送 `: OPENROUTER PROCESSING` keep-alive）
    與解析不出來的 JSON 一律略過——串到一半 crash 比少一個 token 嚴重得多。
    """
    if not line.startswith("data:"):
        return None
    data = line[len("data:"):].strip()
    if not data or data == "[DONE]":
        return None
    try:
        choices = json.loads(data).get("choices") or []
    except json.JSONDecodeError:
        return None
    return (choices[0].get("delta") or {}) if choices else None


def _accumulate(calls: dict[int, dict], deltas: list[dict]) -> None:
    """tool call 是分段串流過來的：name 通常一次到齊，arguments 則是逐塊拼接。"""
    for delta in deltas:
        slot = calls.setdefault(delta.get("index", 0), {
            "id": "", "type": "function", "function": {"name": "", "arguments": ""}})
        if delta.get("id"):
            slot["id"] = delta["id"]
        function = delta.get("function") or {}
        if function.get("name"):
            slot["function"]["name"] += function["name"]
        if function.get("arguments"):
            slot["function"]["arguments"] += function["arguments"]


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
