# asktop

一個「看得到網路、問得了 AI」的 htop——把 process 監控、per-process 網路流量、port 占用整合成單一 TUI 介面，並可用自然語言詢問「現在系統怎麼了」。

**狀態：v0.1.0 —— Phase 1–3 已實作，Phase 4 起步**（process 表格／全域流量／per-process 流量／port 分頁／設定精靈／AI 詢問；macOS per-process 流量已轉正）。
剩下的是 PLAN.md 第 6 節的其他 Phase 4 非承諾項目。per-process 流量：Linux 需 root + nethogs，macOS 用內建 `nettop`（不需 root）。

```bash
uv sync
sudo .venv/bin/python asktop.py        # 預設 sudo，非 root 會降級（行為分平台）
sudo .venv/bin/python asktop.py setup  # 重跑設定精靈
```

**不要用 `sudo uv run`**——會在 `.venv`／cache 留下 root 所有權檔案，之後一般帳號 `uv sync` 會踩權限錯誤。

完整規劃文件見 [PLAN.md](./PLAN.md)（Fable5 model 產出，2026-07-21）、變更記錄見 [CHANGELOG.md](./CHANGELOG.md)。

## 架構與檔案

| 檔案 | 說明 |
|---|---|
| `asktop.py` | UI 與主迴圈（Textual）。三分頁：Process／Ports／AI |
| `collectors.py` | 系統資料採集 + AI 用的壓縮系統摘要。**不 import textual** |
| `mask.py` | cmdline 機密遮罩。純函式、零依賴 |
| `tools.py` | AI 的六個唯讀 tool 與 schema。**不 import textual** |
| `llm.py` | OpenRouter streaming client 與 agent loop。**不 import textual** |
| `config.py` | 設定讀寫，含 sudo 家目錄解析 |
| `wizard.py` | 首次啟動設定精靈 |
| `spike/` | 驗證腳本（無測試框架，純 assert + `✓/✗`，失敗 exit 1） |

UI 層與採集層分離是刻意的：Textual 有 breaking change 風險，資料採集不該被綁死。

```bash
for t in mask llm summary tools ai_ui wizard; do .venv/bin/python spike/test_$t.py; done
```

## AI 詢問

設定 model 與 API key（精靈第 2、3 步，或環境變數 `ASKTOP_API_KEY`）後，AI 分頁可用自然語言詢問系統狀況。

- **小摘要打底 + 六個唯讀 tool 按需深挖**：`get_top_processes`、`get_process_detail`、`get_connections`、`get_listening_ports`、`get_net_rates`、`search_process`
- **AI 沒有任何寫入或 kill 的能力**——只做調查與建議，破壞性操作永遠由人類在 UI 確認執行
- **cmdline 送出前一律遮罩**（`--api-key=`、token、password、DB 連線字串等），與是否 root 無關
- tool 回傳裁切 ≤30 列、tool call 輪數上限 4 輪

## TL;DR

- 形式：TUI（Python + Textual），不做 web 服務
- 依賴：psutil + textual + httpx
- 最難的坑：Linux per-process 流量監控（需 root，nethogs 優先）
- AI：OpenRouter + function calling，唯讀工具，kill 永遠人類確認
- 平台：Linux 一級、macOS 二級、Windows 不承諾
