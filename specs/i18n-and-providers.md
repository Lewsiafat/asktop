# i18n 英文語系 ＋ wizard 語系選擇 ＋ LLM provider 多選

- **分支:** `feat/i18n-and-providers`
- **日期:** 2026-07-22

## 描述
三件相關功能一起做（都動到 wizard/config，避免重複編輯）：

- **Item 2 — 英文語系**：新增輕量 dict-based i18n（不引入依賴），預設英文、可切繁中。所有畫面可見字串經 `i18n.t()` 取用。
- **Item 4 — wizard 語系選擇**：wizard 預設英文，新增「語言」為第一步，選擇後即時套用並記入 `config["lang"]`。
- **Item 5 — LLM provider 多選**：wizard 服務商改為 preset 選單 `openrouter / openai / claude / gemini / custom`，各帶預設 `base_url`（走各家 OpenAI-compatible endpoint，`llm.py` 核心不改）。

## 範圍界定
- i18n 只涵蓋**畫面可見字串**：`asktop.py`（notice／status／kill／欄標題等）、`wizard.py`（全部）、`tools.py` 的 `STATUS` 狀態行、`llm.py` 的 AI 回覆語言指示。
- **不涵蓋**：tool 回傳給 LLM 的資料字串（不直接顯示給人，模型可讀任一語言）、程式碼註解／docstring、PLAN.md 等文件（文件英文化屬 Item 3，另分支）。
- **已知邊界**：Footer 的快捷鍵說明（`BINDINGS`）固定英文——類別層級屬性於 import 時定版，早於讀設定；英文為預設語言故可接受。

## Provider preset（config.PROVIDERS）
| provider | base_url | model 提示 |
|---|---|---|
| openrouter | `https://openrouter.ai/api/v1` | anthropic/claude-sonnet-4.5 |
| openai | `https://api.openai.com/v1` | gpt-4o-mini |
| claude | `https://api.anthropic.com/v1`（Anthropic OpenAI 相容層） | claude-sonnet-4-5 |
| gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | gemini-2.0-flash |
| custom | 使用者自填 | provider/model-id |

## 任務清單
- [x] 新增 `i18n.py`：`set_lang` / `current` / `t(key, **kw)` + en/zh catalog（缺鍵回退 en→key）
- [x] `config.py`：`DEFAULTS` 加 `lang: "en"`；新增 `PROVIDERS` 與 `PROVIDER_ORDER`
- [x] `llm.py`：`system_prompt` 依目前語言（`i18n.t("ai_reply_rule")`）指示 AI 回覆語言
- [x] `tools.py`：`STATUS` 狀態行改走 `i18n.t()`（於 `describe` 呼叫時查）
- [x] `asktop.py`：所有畫面字串改 `i18n.t()`；`__init__`／`FirstRun`／`action_setup` 依 `cfg["lang"]` `set_lang`；欄標題、Windows 訊息 i18n
- [x] `wizard.py`：新增語言步（step 0）＋即時 retranslate；provider RadioSet 改 5 preset、選擇時套 base_url 與 model 提示；step 編號與跳過邏輯順移；全字串 i18n
- [x] 測試：`spike/test_i18n.py`（79 通過）；`spike/test_wizard.py` 新增語言步與 provider preset（29 通過）；回歸 headless 測試全綠
