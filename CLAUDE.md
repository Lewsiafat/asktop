# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案現況

**規劃階段，尚未有任何程式碼。** repo 目前只有 `README.md` 與 `PLAN.md`（Fable5 產出，2026-07-21）。
沒有 `pyproject.toml`、沒有建置/測試/lint 設定——這些要在 Phase 1 開工時才建立。
**不要編造建置或測試指令**；若需要執行任何東西，先確認對應設定檔已存在。

`PLAN.md` 是唯一的權威規格來源。任何實作決策若與 PLAN.md 衝突，先向使用者確認，並同步更新 PLAN.md。

## 產品定位

asktop = 「看得到網路、問得了 AI 的 htop」。差異化不在把監控做得比 btop 漂亮，而在兩件既有工具都沒有的事：

1. **Process × 網路的整合視圖**——同一列看到 CPU、記憶體、per-process 流量、開了哪些 port（取代在 htop / nethogs / `ss -tunlp` 之間手動 join）
2. **AI 調查介面**——用自然語言問「現在系統怎麼了」

## 已定案的架構決策

這些是 PLAN.md 中已經權衡過的決定，實作時直接遵循，不要重新發明：

- **TUI，不做 web 服務**。理由：SSH 進 VPS 排查是主要場景；能 kill process 的服務掛公網是風險。web 版是 Phase 4 非承諾選項（`textual serve` 或唯讀檢視層）。
- **依賴總量目標三個：psutil + textual + httpx**。不引入 langchain、FastAPI、資料庫（歷史資料用 in-memory ring buffer）。Python ≥ 3.12，`uv` 管理。
- **單檔 `asktop.py` 起步**，超過負荷才拆。第一刀切在 collectors（因平台分支而複雜化）。
- **UI 層與 collectors 層分離**——Textual 有 breaking change 風險，資料採集不該被綁死。
- **平台範圍釘死**：Linux 一級（VPS 主戰場）、macOS 二級（可降級）、Windows 明確不承諾。跨平台承諾失控是本案最大的膨脹風險。
- **LLM 走 OpenRouter**（OpenAI-compatible + tools），httpx 直打，model id 由設定檔決定。

## 開發路線圖（階段順序有意義）

- **Phase 0 — spike**：驗證 nethogs 輸出解析、psutil root/無 root 差異、Textual DataTable 200+ 列流暢度。**此 phase 結論直接決定 Phase 2 走向，不要跳過。**
- **Phase 1 — MVP**：process 表格（排序/篩選/kill）、全域流量 sparkline、port 占用分頁、首次啟動設定精靈。交付判準：能用它在 VPS 排查一次真實問題而不切回 htop/ss。
- **Phase 2 — per-process 流量**：nethogs 包裝，流量欄併入表格。這是本專案的靈魂功能，也是最難的部分。
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
