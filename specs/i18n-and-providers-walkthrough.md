# i18n 英文語系 ＋ wizard 語系選擇 ＋ LLM provider 多選 — Walkthrough

- **分支:** `feat/i18n-and-providers`
- **日期:** 2026-07-22

## 變更摘要
新增輕量 dict-based i18n（預設英文、可切繁中，零新依賴），把所有畫面可見字串改走 `i18n.t()`；wizard 新增「語言」為第一步並支援即時 retranslate；LLM 服務商改為 `openrouter / openai / claude / gemini / custom` 五個 preset，選擇即帶入對應 OpenAI-compatible `base_url`。

## 修改的檔案
- `i18n.py`（新增）— i18n 核心：`set_lang` / `current` / `t(key, **kw)`，en/zh 兩語 catalog。缺鍵回退 en→key，永不 KeyError；不 import textual（與 collectors/llm/tools 同分層）。
- `config.py` — `DEFAULTS` 新增 `lang: "en"`；新增 `PROVIDERS`（label/base_url/model 提示）與 `PROVIDER_ORDER`。
- `wizard.py`（大幅改寫）— 六步流程（language/provider/model/key/theme/confirm）；語言步即時 `retranslate()`；provider 改 5-preset RadioSet，選擇時套用 base_url、model placeholder、唯讀顯示 endpoint；step 編號與「跳過 AI 設定」目標順移；全字串 i18n。
- `asktop.py` — 所有畫面字串改 `i18n.t()`（notice/status/kill/欄標題/quick 問題/Windows 訊息）；`__init__`、`FirstRun.on_mount`、`action_setup` 依 `cfg["lang"]` `set_lang`；`BINDINGS` 描述改英文字面量。
- `llm.py` — `system_prompt` 的 AI 回覆語言指示改由 `i18n.t("ai_reply_rule")` 提供（隨 UI 語言）。
- `tools.py` — 移除硬編碼 `STATUS` dict，`describe()` 於呼叫時以 `i18n.t("tool_<name>")` 查狀態行。
- `spike/test_i18n.py`（新增）— catalog 對齊（en/zh 鍵集合、format 佔位符一致）與 fallback 驗證（79 通過）。
- `spike/test_wizard.py` — 修正預設英文造成的中文斷言；新增語言步 retranslate 與 provider preset 兩項覆蓋（29 通過）。
- `spike/test_ai_ui.py` — 未設定引導文案斷言改對英文預設。

## 技術細節
- **為何自建而非 gettext**：維持 psutil+textual+httpx 三依賴目標。dict catalog + `t()` 足夠，`test_i18n.py` 以「兩語鍵集合必須一致」當硬性條件，補上 en-fallback 靜默掩蓋缺鍵的風險。
- **Provider 走 OpenAI-compatible endpoint**（使用者拍板）：Claude 用 Anthropic 相容層 `https://api.anthropic.com/v1`、Gemini 用 `.../v1beta/openai/`，`llm.py` 核心（打 `/chat/completions`）完全不動，切 provider 的實際效果就是換 `base_url`。
- **wizard 即時 retranslate**：精靈是唯一支援語言即時切換的畫面。以 `self._ready` 旗標擋掉 compose 期間 RadioSet 的初始 `Changed` 事件，避免 retranslate 在 widget 尚未就緒時 query 失敗。
- **已知邊界**：Footer 快捷鍵說明固定英文——`BINDINGS` 為類別屬性，於 import 時定版、早於讀設定；英文為預設語言故可接受。執行中透過 `s` 改語言時，動態文字即時跟隨，靜態版面（分頁/欄標題/placeholder）下次啟動全面套用。
- **設定相容**：舊 config.json 無 `lang` 欄，`load()` 的 `{**DEFAULTS, **data}` 自動補為 `en`，不需 migration。
- **驗證**：mask/llm/tools/summary/ai_ui/wizard/i18n/ports 全套 headless 測試綠；另以 inline headless 冒煙確認 en/zh 兩語主畫面組建與字串切換正常。
