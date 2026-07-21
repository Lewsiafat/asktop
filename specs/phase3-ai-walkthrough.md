# asktop Phase 3（AI 詢問）— Walkthrough

- **分支:** `feat/phase3-ai`
- **日期:** 2026-07-21

## 變更摘要

把 AI 分頁從佔位文字做成可用的系統診斷助手：OpenRouter streaming 對話（Phase 3-1）、cmdline 遮罩與壓縮系統摘要（3-2）、function calling agent loop 搭配六個唯讀 tools 與快捷問題（3-3）。對應 GitHub issues #1 / #2 / #3，三張都已 `Closes`。

依賴維持 psutil + textual + httpx 三個——LLM 走 httpx 直打 OpenAI-compatible API，不引入 openai SDK 或 langchain。

> **尚未做真實模型實測。** 167 項驗證全部走 `httpx.MockTransport`，證明的是「請求 payload、tool schema、遮罩、輪數上限、UI 行為」正確，**不包含模型的實際回答品質**。見文末「待驗證」。

## 修改的檔案

**新增模組**

| 檔案 | 說明 |
|---|---|
| `mask.py` | cmdline 機密遮罩。純函式、零依賴、冪等，可選截斷。系統數據出境的唯一過濾器 |
| `llm.py` | OpenRouter streaming client（SSE 解析）+ agent loop `converse()`。**不 import textual** |
| `tools.py` | 六個唯讀 tool 的 schema 與實作、狀態行文案。**不 import textual** |

**修改**

| 檔案 | 說明 |
|---|---|
| `asktop.py` | AI 分頁改為對話介面（Markdown 串流、快捷問題、tool 狀態行）；新增 `prompt()`／`ask()` worker／`run_tool()`；`tick_net` 增採 `cpu_percent`，`tick_procs`／`tick_ports` 保留未篩選結果供摘要與 tool 使用 |
| `collectors.py` | 新增 `summary()`（壓縮系統摘要）與 `_gb`／`_duration` |
| `CLAUDE.md` | 專案現況、模組結構、測試指令與 headless 測試的兩個陷阱 |
| `PLAN.md` | 狀態列與第 6 節 Phase 3 標記為已實作 |
| `.gitignore` | 加入 `temp/` |

**驗證腳本**（純 assert + `✓/✗`，失敗 exit 1，不裝 pytest）

| 檔案 | 項數 | 驗證什麼 |
|---|---|---|
| `spike/test_mask.py` | 42 | 各種機密樣式遮得掉、正常命令列不誤遮、冪等、截斷 |
| `spike/test_llm.py` | 11 | SSE 解析、請求格式、401／斷網／壞 JSON 不外洩 key 不中斷 |
| `spike/test_summary.py` | 29 | 摘要內容與排序、遮罩、生成成本、prompt 組裝 |
| `spike/test_tools.py` | 54 | 六個 tool 的行為、≤30 列裁切、無破壞性能力、agent loop 輪數上限與追問重查 |
| `spike/test_ai_ui.py` | 31 | headless UI：串流、未設定引導、錯誤不退出、UI 不凍結、快捷問題、狀態行 |

```bash
for t in mask llm summary tools ai_ui; do .venv/bin/python spike/test_$t.py; done
```

## 技術細節

### 架構

`llm.converse()` 是 agent loop，就地累積 `messages`；tool 的資料來源是 `tools.Source`（四個 callable，不是快照）——追問時 tool 必須拿到當下數據，沿用開場快照等於回答上一分鐘的系統。UI 層只消費 `Text`／`Status` 兩種事件，換掉 Textual 不影響 `llm`／`tools`／`mask` 三個模組。

### 硬性約束的落實位置

| 約束 | 落實 |
|---|---|
| AI 無寫入／kill 能力 | `tools._HANDLERS` 六個全唯讀；`test_tools.py` 掃 `tools.py` 原始碼擋下 `os.kill`／`send_signal`／`subprocess` 等字樣，防止日後回頭加進來 |
| cmdline 必經遮罩 | 兩個出境入口：`collectors.summary()` 與 `tools._proc_line`／`_process_detail`，皆呼叫 `mask.cmdline()` |
| API key 不外洩 | `stream()` 的例外處理只取 `type(exc).__name__` 與 `str(exc)`，不用 repr（httpx 的 repr 會帶 request 物件，含授權標頭） |
| tool 回傳 ≤30 列 | `MAX_ROWS = 30`，`_cut()` 統一裁切並標示總數 |
| tool 輪數上限 4 | `MAX_TOOL_ROUNDS = 4`；第 5 次請求不再帶 `tools`，逼模型用手上的資料作答 |
| 摘要不拖慢 UI | `summary()` 是純格式化，process 與 port 由呼叫端傳入既有採集結果，不重掃（實測 0.3ms） |

### 實作過程中踩到與修掉的問題

**1. prompt 與 tools 互相矛盾（code review 抓到，最嚴重）**

Phase 3-2 寫的 system prompt 說「快照是你唯一的數據來源，快照沒寫的（例如某個 port 是誰在用）你就是不知道」。3-3 掛上 tools 後沒回頭改，等於一邊給工具一邊叫模型別查——正好打中 issue #3「問誰在占 8080，AI 呼叫 port tool」那條驗收條件。schema 與接線都正確，壞的是措辭。

教訓：**單元測試全綠但功能實質失效**，因為所有測試驗的都是「payload 正確」，沒有一項驗 prompt 語意。修正後在 `test_summary.py` 加了三條回歸斷言釘住措辭（要有「用工具查」、要點名「port 是誰在用」、不得出現「唯一的數據來源」）。

**2. `MarkdownStream` 的 task 提早取消會連坐 worker**

`Markdown.get_stream()` 建的背景 task 若在首次排程前就 `stop()`，`CancelledError` 會傳回呼叫端把整個 Textual worker 取消——401 這種「一個 chunk 都還沒到就失敗」的路徑必然踩到，症狀是錯誤訊息完全不顯示。解法是延遲到第一個 chunk 才建 stream。

**3. `_process_detail` 的 CPU% 恆為 0**

每次呼叫都新建 `psutil.Process`，`cpu_percent()` 首呼叫依 psutil 定義必回 `0.0`。AI 會據此回報「這個 process 沒在吃 CPU」，屬於編造數字。改用主畫面那份採集的數值。

**4. `httpx.InvalidURL` 不是 `HTTPError` 子類**

設定檔 `base_url` 打錯時它會直接逃出 worker，違反 issue #1「程式不退出」。已一併捕捉。

**5. 遮罩的取捨：寧可漏遮也不誤遮**

參數名採「結尾比對」——`--api-key` 中、`--keyfile-path` 不中、`--monkey=banana` 不中。把 `/usr/bin/python3 manage.py` 遮成 `***` 會讓 AI 完全看不懂系統，比漏遮一個罕見樣式傷害更大。`test_mask.py` 第 5 節專門守這條界線。

**6. headless 測試：非啟用中分頁的 widget 點不到**

`pilot.click()` 對不可見的 widget 會靜默失效（不報錯），測 AI 分頁前要先 `query_one(TabbedContent).active = "tab-ai"`。已寫進 CLAUDE.md。

### 刻意不做

- **tool 結果不進長期歷史**——只活在單輪。留著會讓下一次追問拿舊快照當現況，與「追問時重新查詢」的驗收條件衝突。
- **`_connections`／`_process_detail` 直呼 psutil 而非走 collectors**——這兩個要的是「當下、單一 PID」的資料，塞進採集層會讓 collectors 長出只有 AI 會用的入口。頻率由 AI 觸發、單次 3–7ms。
- **快捷問題不做帶參數的「port XXXX 是誰在用」**——一鍵送出無法填參數，改為「哪些 port 被誰占用」覆蓋同一條 tool 路徑。

## 待驗證

**需要真實 API key（本次未做）**

- issue #2：「AI 對摘要外的數字回答不知道而非編造」
- issue #3：「問誰在占 8080，AI 呼叫 port 相關 tool 並引用真實 PID/程式名回答」

這兩條的本質是模型行為，MockTransport 驗不到。上面第 1 點正是「測試全綠、真跑起來壞掉」的實例，所以這兩條在真實模型上跑過之前，不能視為已達成。驗法：設好 key 與 model 後 `sudo .venv/bin/python asktop.py`，點快捷問題「哪些 port 被誰占用」，看它是回真實 PID 還是回「我看不到」。

**需要 Linux + sudo + nethogs**

- `get_net_rates` 與 `get_top_processes(sort_by="net")` 有 nethogs 的分支（macOS 只走得到「不可用」那條）
- issue #3：「問誰在吃頻寬，AI 引用 per-process 流量的真實數據」

**已知落差（非本次範圍）**

`asktop.py setup` 從預設值重新開始，不會載入現有設定檔（`main()` 把 `cfg` 設成 `None`，`FirstRun` 用無參數的 `SetupWizard()`）；主畫面按 `s` 走的是 `SetupWizard(self.cfg)`，行為正確。PLAN.md 第 9 節寫的是「可用 `asktop setup` 修改任一項設定」，「修改」的語意要求看得到現值。
