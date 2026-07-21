# asktop — 類 htop 全能系統監控工具 規劃文件

> 狀態：規劃階段（未實作）
> 日期：2026-07-21
> 對象：Lewis 個人開發工具（非商業 SaaS，無多租戶、無帳號系統）
> 產出：Fable5 model

---

## 1. 產品定位與核心價值主張

**一句話**：一個「看得到網路、問得了 AI」的 htop——把 process 監控、per-process 網路流量、port 占用整合成單一介面，並且可以直接用自然語言問「現在系統發生什麼事」。

### 與既有工具的差異化

| 工具 | Process 監控 | 全域流量 | Per-process 流量 | Port 占用視圖 | 管理操作 (kill 等) | AI 詢問 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| htop / btop / bottom | ✅ 強 | 部分（btop 有 NIC 圖） | ❌ | ❌ | ✅ | ❌ |
| glances | ✅ | ✅ | ❌（核心版沒有） | 部分 | 弱 | ❌ |
| nethogs | ❌ | ❌ | ✅（Linux） | ❌ | ❌ | ❌ |
| iftop / bandwhich | ❌ | ✅ | bandwhich 有（per-process/connection） | ❌ | ❌ | ❌ |
| `ss` / `lsof -i` | ❌ | ❌ | ❌ | ✅（但是一次性指令，非即時視圖） | ❌ | ❌ |
| **本工具** | ✅ | ✅ | ✅（Linux 優先） | ✅（即時、可排序篩選） | ✅ | ✅ |

核心洞察：現在要回答「為什麼網路慢／誰在占 8080」需要在 htop、nethogs、`ss -tunlp` 三個工具之間切換、自己在腦中做 join。**這個工具的價值就是把這個 join 做掉，而且最後一哩（解讀數據）交給 AI。**

差異化不是「監控做得比 btop 漂亮」——btop 在視覺上已經很難超越——而是：
1. **Process × 網路的整合視圖**（同一列看到 CPU、記憶體、流量、開了哪些 port）
2. **AI 調查介面**（既有工具全部沒有）

---

## 2. 技術架構建議

### 2.1 TUI vs Web Dashboard 取捨分析

| 面向 | TUI | Web Dashboard |
|------|-----|---------------|
| 「類 htop」使用情境（SSH 進 VPS 直接跑） | ✅ 天生契合 | ❌ 要 port forwarding 或掛 nginx |
| 安全面 | ✅ 無網路暴露面 | ❌ 能 kill process 的 web 服務掛公網是風險 |
| 部署複雜度 | ✅ 單一指令，無 systemd/nginx/port | ❌ 需要 port registry、nginx conf、systemd |
| 多機使用 | ✅ 各自 SSH 進去跑，天然隔離 | 每台都要各架一份服務 |
| 圖表豐富度 | 中 | ✅ 強 |
| AI 對話 UX | 可以 | ✅ 略優 |
| 符合 Lewis 的 Vue 3 熟悉度 | ❌ 用不到 | ✅ |

**建議：TUI，Python + Textual。**

理由：主要使用時刻是「SSH 進 VPS 排查問題」，開瀏覽器連 dashboard 是額外摩擦；kill process 用 TUI 完全不用處理認證與暴露面；部署 = `uv tool install` 或直接跑，不占 port registry、不寫 nginx、不開 systemd。

Web 版降級為未來選項（Phase 4）：唯讀檢視層或 `textual serve` 直接把 TUI 投到瀏覽器。

### 2.2 技術選型

| 層 | 選型 | 理由 |
|----|------|------|
| 語言 | Python ≥ 3.12，`uv` 管理 | 符合 Lewis 慣例 |
| TUI 框架 | **Textual** | DataTable、reactive 更新、Markdown widget、async 原生支援 |
| 系統資料 | **psutil** | 跨平台事實標準 |
| Per-process 流量 | Linux：包裝 **nethogs**（trace mode）或 eBPF（python-bcc）；macOS：解析 **nettop** | 詳見 2.3 與第 7 節 |
| LLM 呼叫 | **httpx** 直打 **OpenRouter** | 符合 Lewis 既有慣例，不引入 langchain 等重依賴 |
| 設定 | `.env` + `os.getenv()` | 符合慣例 |
| 檔案結構 | 單檔 `asktop.py` 起步，超過負荷才拆 | 單檔優先；collectors 含平台分支是合理的第一刀 |

依賴總量目標：**psutil + textual + httpx 三個**。不用 FastAPI、不用資料庫（in-memory ring buffer）。

### 2.3 各平台系統資料取得方式

| 資料 | Linux | macOS | Windows |
|------|-------|-------|---------|
| Process 列表 / CPU / mem | psutil | psutil | psutil |
| 全域 NIC 流量 | psutil `net_io_counters()` delta | 同左 | 同左 |
| 連線 / port 占用 | psutil `net_connections()`，看全部使用者需 root；降級 fallback 解析 `ss -tunlp` | 同樣多半需要 root | 需實測驗證 |
| **Per-process 流量** | 無現成 psutil API。三條路：(a) 包裝 nethogs（最省工，需 root）；(b) python-bcc/eBPF（正統但環境敏感）；(c) 自己 pcap sniff + socket inode→pid 對映 | `nettop -x -P -l 1` 有原生 per-process bytes（輸出穩定性需實測） | ETW 正規做法，Python 生態沒有好走的路，**建議明確標為不支援** |

**Linux per-process 流量建議**：MVP 先走 (a) nethogs 包裝；Phase 2 若精度不滿意再評估 (b)。三條路都需要 root。

**平台策略**：**Linux 一級支援（VPS 主戰場），macOS 二級（可降級），Windows 明確不承諾**——一開始就把範圍釘死，避免專案膨脹失控。

---

## 3. 核心功能模組拆解

### 3.1 Process 監控模組
- **MVP**：表格（PID/名稱/使用者/CPU%/MEM%/狀態）、任一欄排序、即時篩選、kill（SIGTERM + 二次確認）
- **進階**：其他 signal、process tree、單一 process 詳情頁、CPU/mem sparkline 歷史、nice 調整

### 3.2 網路流量監控模組
- **MVP**：全域即時上下行速率（per-NIC）+ sparkline
- **進階（Phase 2 核心）**：per-process 上下行速率併入 process 表格（整合視圖的靈魂）、per-connection 流量、依流量排序

### 3.3 Port 占用整合視圖
- **MVP**：獨立分頁，listening ports 表格（port/協定/位址/PID/process 名稱）= 常駐版 `ss -tunlp`；點選跳到對應 process
- **進階**：全部連線視圖、連線狀態統計；**與 Lewis 的 `/srv/projects/port-registry.json` 對照**——port 旁標註「這是 agent-arena」，實作成本極低，殺手級小功能

### 3.4 AI 詢問介面
- **MVP**：對話分頁，function calling 查詢即時狀態 → streaming 回覆（Markdown），預設 zh-TW
- **進階**：多輪追問、引用歷史 ring buffer、AI 建議操作（kill 永遠人類按下）、快捷問題

---

## 4. AI 詢問功能具體設計

### 4.1 核心決策：Function calling，不要一次性塞全部快照
一次性 dump 完整系統快照的問題：VPS 上動輒 200+ process、數百條連線，多數與問題無關；送出當下就過時，無法針對追問拿新資料。

**架構：小摘要打底 + tools 按需深挖**
1. System prompt 附「壓縮摘要」（hostname/uptime/load/CPU-mem 總覽/top5 CPU/top5 mem/目前速率/listening port 數），目標幾百 token
2. 唯讀 tools：`get_top_processes` / `get_process_detail` / `get_connections` / `get_listening_ports` / `get_net_rates` / `search_process`
3. tool 回傳做上限裁切（最多 30 列，cmdline 截斷）
4. 限制 tool call 輪數（建議上限 4 輪）

### 4.2 Prompt 設計要點
- 角色設定：系統診斷助手，只根據工具查到的數據回答，不知道就說不知道
- 註明快照時間戳與主機身分（Lewis 有多台機器）
- **AI 沒有任何寫入/kill tool**——只做調查與建議，破壞性操作永遠人類在 UI 確認執行
- 回答語言：繁體中文

### 4.3 隱私注意
cmdline 常含機密（`--api-key=xxx`、DB 連線字串）。送 LLM 前做遮罩（regex 遮 key/token/password 樣式參數值）。

### 4.4 API、成本與延遲
- OpenRouter（OpenAI-compatible + tools），model 走 `.env` 設定
- 具體 token/成本數字**需要實測驗證**，不預先寫死
- 延遲對策：streaming 輸出、tool call 進行中顯示狀態行、UI 全程 async

---

## 5. 資料更新機制

原則：**監控工具自己不能成為負載**。

| 資料 | 成本 | 建議間隔 |
|------|------|----------|
| NIC counters | 極低 | 1s |
| process CPU/mem | 中 | 2s（可調） |
| `net_connections()` 全表 | 高 | 3–5s，僅當前分頁可見時查 |
| per-process 流量（nethogs） | 常駐 stream | 每秒聚合 |

其他機制：可見性驅動採集、in-memory ring buffer（近 5-10 分鐘）、暫停鍵、自我監控（自身 CPU% 顯示，若 nethogs 開銷過高改 lazy 模式）。

---

## 6. 分階段開發路線圖

**Phase 0 — 技術驗證 spike**：驗證 nethogs 解析可行性、psutil root/無 root 差異、Textual DataTable 200+ 列流暢度、macOS nettop 解析（可延後）。此 phase 結論直接決定 Phase 2 走向。

**Phase 1 — MVP**：單檔 `asktop.py`，process 表格（排序/篩選/kill）、全域流量 sparkline、Port 占用分頁（含 port-registry 標註）、`uv run asktop.py` 可跑。交付判準：SSH 進 VPS 用它排查一次真實問題，不需切回 htop/ss。

**Phase 2 — Per-process 流量（本專案靈魂功能）**：nethogs 包裝，流量欄併入表格；無 root/無 nethogs 時優雅降級。

**Phase 3 — AI 詢問**：OpenRouter client + streaming、摘要生成器 + 6 個唯讀 tools + cmdline 遮罩、對話分頁、快捷問題。

**Phase 4 — 打磨與延伸（非承諾）**：macOS 支援轉正、process 詳情頁、`textual serve` 或唯讀 web 層評估、`uv tool install` 打包。

---

## 7. 潛在風險與技術挑戰（誠實清單）

| # | 風險 | 說明 | 對策 |
|---|------|------|------|
| 1 | **Per-process 流量是全案最難的部分** | Linux 無免特權現成 API，nethogs/eBPF/pcap 都要 root 且各有依賴 | Phase 0 先 spike；設計成可降級 |
| 2 | **Root 權限需求** | 看全部使用者 pid↔socket、抓封包都需要 root | 支援無 root（降級模式）與 sudo（全功能）兩種；設定檔路徑用絕對路徑 |
| 3 | 跨平台承諾失控 | 三平台全功能會讓 collectors 變成最大複雜度來源 | 一開始釘死 Linux 一級/macOS 二級/Windows 不承諾 |
| 4 | AI 延遲影響體驗 | tool calling 多輪往返數秒起跳 | streaming + 進度提示 + 輪數上限 |
| 5 | 系統資料外送 LLM 的隱私面 | cmdline/連線遠端位址可能含機密 | cmdline 遮罩；AI 功能可整個關閉 |
| 6 | AI 幻覺數字 | LLM 可能編造沒查過的數值 | prompt 明令只引用 tool 結果；重要結論可對照原始表格 |
| 7 | Textual 相依風險 | 框架仍活躍演進，偶有 breaking change | lock 版本；UI 與 collectors 層分離 |
| 8 | 監控工具自身開銷 | `net_connections()` 全表 + pcap 成本不明 | 分層輪詢 + 可見性驅動 + 自身 CPU% 顯示；具體開銷需實測 |
| 9 | kill 誤操作 | 表格刷新瞬間選錯列殺錯 process | 確認框顯示 PID+名稱+cmdline；確認期間綁定 PID 不綁列位置 |

---

## 8. 專案命名建議

1. **`asktop`**（主推）——「ask + top」，好打、點出差異化
2. **`omnitop`**（備選）——強調整合定位，但沒點出 AI 賣點

---

## TL;DR

- **形式**：TUI（Python + Textual），不做 web 服務——SSH 場景零摩擦、零安全暴露面
- **依賴**：psutil + textual + httpx 三個；`uv` 管理；單檔起步
- **最難的坑**：Linux per-process 流量（nethogs 優先，Phase 0 先驗證），root 需求無法繞過
- **AI**：OpenRouter + function calling（小摘要+唯讀 tools+輪數上限+cmdline 遮罩，kill 永遠人類確認）
- **範圍紀律**：Linux 優先、Windows 不承諾、web 檢視層押後
