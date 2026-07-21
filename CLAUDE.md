# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案現況

**v0.0.1 —— Phase 1 MVP、Phase 2（per-process 流量）、Phase 3（AI 詢問）已實作。** 剩下的是 Phase 4 非承諾項目。

變更記錄見 `CHANGELOG.md`（Keep a Changelog 格式），發版流程用 `/release`。

per-process 流量只在 Linux + root + 有 nethogs 時啟用，其餘情況流量欄整欄不建立（填 0 會讓「沒資料」看起來像「沒流量」）。

`PLAN.md` 是唯一的權威規格來源，第 10 節記錄 Phase 0 實測數據。任何實作決策若與 PLAN.md 衝突，先向使用者確認，並同步更新 PLAN.md。

## 指令

```bash
uv sync                              # 安裝依賴
sudo .venv/bin/python asktop.py      # 執行（預設 sudo，非 root 會降級）
sudo .venv/bin/python asktop.py setup  # 重跑設定精靈
uv run spike/spike_psutil_root.py    # Phase 0 驗證腳本，見 spike/ 各檔 docstring
```

**不要用 `sudo uv run`**——會在 `.venv`／cache 留下 root 所有權檔案，之後一般帳號 `uv sync` 會踩權限錯誤。

**沒有測試框架**（不裝 pytest，維持三個依賴的目標）。驗證腳本放在 `spike/test_*.py`，用純 assert + `✓/✗` 輸出、失敗時 exit 1：

```bash
for t in mask llm summary tools ai_ui; do .venv/bin/python spike/test_$t.py; done
```

其中 `test_mask`／`test_llm`／`test_tools` 不需 root 也不打網路（httpx `MockTransport`），`test_phase2` 需 Linux + sudo。

UI 部分靠 Textual 的 headless 模式（`App.run_test()`），例如：

```python
async with app.run_test() as pilot:
    await pilot.pause()
    ...
```

注意 headless 下連續快速點擊同一個 widget 時第二次會被吞掉（Textual 事件合併），測多步流程時改用直接呼叫 handler 方法。另外連續呼叫刷新函式量到的自身 CPU% 不具參考價值。**非啟用中分頁的 widget 點不到**（`pilot.click` 靜默失效），測 AI 分頁前要先 `query_one(TabbedContent).active = "tab-ai"`。

## 模組結構

- `collectors.py` — 系統資料採集 + AI 用的壓縮摘要，**不 import textual**（風險 #7 要求的分層）
- `mask.py` — cmdline 機密遮罩，純函式、零依賴
- `tools.py` — AI 的 6 個唯讀 tool 與 schema，**不 import textual**
- `llm.py` — OpenRouter streaming client 與 agent loop，**不 import textual**
- `config.py` — 設定讀寫，含 sudo 家目錄解析
- `wizard.py` — 首次啟動設定精靈
- `asktop.py` — UI 與主迴圈

PLAN.md 原本寫「單檔起步」，Phase 1 實作時已改為此結構（第 2.2 節已同步）。

## 產品定位

asktop = 「看得到網路、問得了 AI 的 htop」。差異化不在把監控做得比 btop 漂亮，而在兩件既有工具都沒有的事：

1. **Process × 網路的整合視圖**——同一列看到 CPU、記憶體、per-process 流量、開了哪些 port（取代在 htop / nethogs / `ss -tunlp` 之間手動 join）
2. **AI 調查介面**——用自然語言問「現在系統怎麼了」

## 已定案的架構決策

這些是 PLAN.md 中已經權衡過的決定，實作時直接遵循，不要重新發明：

- **TUI，不做 web 服務**。理由：SSH 進 VPS 排查是主要場景；能 kill process 的服務掛公網是風險。web 版是 Phase 4 非承諾選項（`textual serve` 或唯讀檢視層）。
- **依賴總量目標三個：psutil + textual + httpx**。不引入 langchain、FastAPI、資料庫（歷史資料用 in-memory ring buffer）。Python ≥ 3.12，`uv` 管理。
- **UI 層與 collectors 層分離**——Textual 有 breaking change 風險，資料採集不該被綁死。
- **平台範圍釘死**：Linux 一級（VPS 主戰場）、macOS 二級（可降級）、Windows 明確不承諾。跨平台承諾失控是本案最大的膨脹風險。
- **LLM 走 OpenRouter**（OpenAI-compatible + tools），httpx 直打，model id 由設定檔決定。

## 開發路線圖（階段順序有意義）

- **Phase 0 — spike**：驗證 nethogs 輸出解析、psutil root/無 root 差異、Textual DataTable 200+ 列流暢度。**此 phase 結論直接決定 Phase 2 走向，不要跳過。**
- **Phase 1 — MVP**：process 表格（排序/篩選/kill）、全域流量 sparkline、port 占用分頁、首次啟動設定精靈。交付判準：能用它在 VPS 排查一次真實問題而不切回 htop/ss。
- **Phase 2 — per-process 流量（已完成）**：nethogs 包裝，流量欄併入表格。驗證需在 Linux + sudo 下跑 `spike/test_phase2.py`。
- **Phase 3 — AI 詢問**：OpenRouter client + streaming、摘要 + 6 個唯讀 tools + cmdline 遮罩。
- **Phase 4 — 非承諾**：macOS 轉正、`uv tool install` 打包、web 層評估。

## 實作時的硬性約束

這幾條是安全/隱私相關，違反了會出事：

- **AI 沒有任何寫入或 kill 的 tool**。LLM 只能調查與建議；破壞性操作永遠由人類在 UI 確認執行。
- **cmdline 送 LLM 前必須遮罩**（`--api-key=`、token、password、DB 連線字串等樣式）。AI 功能可整個關閉。
- **AI 只能引用 tool 回傳的數據**，prompt 明令不知道就說不知道，避免幻覺數字。tool 回傳做上限裁切（≤30 列），tool call 輪數上限建議 4。
- **DataTable 一律用 PID 當 row key**（`add_row(key=pid)`）。這是游標不漂移、kill 不殺錯的根本解（PLAN.md 10.3 實測），與採用增量或重建更新無關。確認框需顯示 PID + 名稱 + cmdline。
- **API key 一律不進畫面/log/debug 輸出**。設定檔 `~/.config/asktop/config.json` 建立時設 `600`。
- **監控工具自己不能成為負載**。分層輪詢（NIC counters 1s、process 2s、`net_connections()` 全表 3–5s 且僅當前分頁可見時查）、可見性驅動採集、UI 顯示自身 CPU%。
- **預設以 sudo 執行**。非 root 的降級行為**分平台**（PLAN.md 10.1 實測）：Linux 仍列得出 port 但只有 36% 有 pid，擁有者欄標「不明」；macOS 是整個 AccessDenied，只能顯示「需 root」。不要寫成同一套文案。同理 AI 未設定時，對話分頁顯示引導而非錯誤。
- **nethogs 輸出是累計 KB 不是速率**，必須自行差分；差分為負視為 counter 重置。`pid=0` 的流量歸入「未歸屬」列，不可靜默丟棄，否則 per-process 加總對不上全域 NIC 流量。
- **cmdline 遮罩與是否 root 無關**：Linux `/proc` 預設 world-readable，非 root 也讀得到全部使用者的 cmdline。
- **sudo 下 `$HOME` 會變成 `/root`**——讀寫 `~/.config/asktop/config.json` 必須解析回呼叫者的家目錄（`SUDO_USER`），否則設定會存錯地方。

## 語言慣例

使用者溝通、程式碼註解、AI 回覆預設語言皆為**繁體中文**。UI 預設 dark theme。

## Agent skills

### Issue tracker

Issues 追蹤於此 repo 的 GitHub Issues（使用 `gh` CLI）。See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context：repo 根目錄的 `CONTEXT.md` + `docs/adr/`。See `docs/agents/domain.md`.
