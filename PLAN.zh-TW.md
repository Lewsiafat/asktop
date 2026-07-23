[English](PLAN.md) | **繁體中文**

# asktop — 類 htop 全能系統監控工具 規劃文件

> 狀態：Phase 1（MVP）、Phase 2（per-process 流量）、Phase 3（AI 詢問）已實作
> 日期：2026-07-21（第 10 節為後續實測補記）
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
| 檔案結構 | `asktop.py`(UI) / `collectors.py` / `config.py` / `wizard.py` | 原規劃單檔起步，Phase 1 實作時直接拆成四個模組：`collectors` 是風險 #7 要求的 UI／採集分層（不 import textual），`wizard` 是一次性流程與主畫面無關，`config` 含 sudo 家目錄解析需獨立測試 |

依賴總量目標：**psutil + textual + httpx 三個**。不用 FastAPI、不用資料庫（in-memory ring buffer）。

### 2.3 各平台系統資料取得方式

| 資料 | Linux | macOS | Windows |
|------|-------|-------|---------|
| Process 列表 / CPU / mem | psutil | psutil | psutil |
| 全域 NIC 流量 | psutil `net_io_counters()` delta | 同左 | 同左 |
| 連線 / port 占用 | psutil `net_connections()`；無 root 仍拿得到連線與完整 LISTEN 清單，但僅 36% 有 pid（見第 10 節） | 同上但無 root 直接 AccessDenied，全有全無 | 需實測驗證 |
| **Per-process 流量** | 無現成 psutil API。三條路：(a) 包裝 nethogs（最省工，需 root）；(b) python-bcc/eBPF（正統但環境敏感）；(c) 自己 pcap sniff + socket inode→pid 對映 | `nettop -x -P -l 1` 有原生 per-process bytes（輸出穩定性需實測） | ETW 正規做法，Python 生態沒有好走的路，**建議明確標為不支援** |

**Linux per-process 流量建議**：走 (a) nethogs 包裝——第 10.2 節已實測解析可行，不需轉 eBPF。三條路都需要 root。**注意 nethogs trace mode 輸出的是累計 KB 而非速率，需自行差分。**

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
| `net_connections()` 全表 | 實測遠低於預期（見第 10 節） | 2s；「僅當前分頁可見時查」暫緩實作，待 VPS 高連線數複測後再決定 |
| per-process 流量（nethogs） | 常駐 stream | 每秒聚合 |

其他機制：可見性驅動採集、in-memory ring buffer（近 5-10 分鐘）、暫停鍵、自我監控（自身 CPU% 顯示，若 nethogs 開銷過高改 lazy 模式）。

---

## 6. 分階段開發路線圖

**Phase 0 — 技術驗證 spike**：驗證 nethogs 解析可行性、psutil root/無 root 差異、Textual DataTable 200+ 列流暢度、macOS nettop 解析（可延後）。此 phase 結論直接決定 Phase 2 走向。

**Phase 1 — MVP（已實作）**：process 表格（排序/篩選/kill）、全域流量 sparkline、Port 占用分頁（含 port-registry 標註）、**首次啟動設定精靈**（見第 9 節，theme 部分必須在 MVP 就做，provider/model/API key 部分至少要能設定、跳過也不擋住監控功能）、`uv run asktop.py` 可跑。交付判準：SSH 進 VPS 用它排查一次真實問題，不需切回 htop/ss。

**Phase 2 — Per-process 流量（已實作，見 10.4）**：nethogs 包裝，**累計值差分成速率**、濾除診斷雜訊列、`pid=0` 併為「未歸屬」列，流量欄併入表格；無 root/無 nethogs 時優雅降級。

**Phase 3 — AI 詢問（已實作）**：OpenRouter client + streaming、摘要生成器 + 6 個唯讀 tools + cmdline 遮罩、對話分頁、快捷問題。tool 輪數上限 4（第 5 次請求收回 tools，逼模型用現有資料作答）；tool 結果只活在單輪，不進長期歷史，避免追問時拿舊快照當現況。

**Phase 4 — 打磨與延伸（非承諾）**：macOS 支援轉正、process 詳情頁、`textual serve` 或唯讀 web 層評估、`uv tool install` 打包。

---

## 7. 潛在風險與技術挑戰（誠實清單）

| # | 風險 | 說明 | 對策 |
|---|------|------|------|
| 1 | **Per-process 流量是全案最難的部分** | Linux 無免特權現成 API，nethogs/eBPF/pcap 都要 root 且各有依賴 | Phase 0 先 spike；設計成可降級 |
| 2 | **Root 權限需求** | 看全部使用者 pid↔socket、抓封包都需要 root | **預設以 sudo 執行（全功能）**；無 root 為降級模式且**行為分平台**（見 10.1）：Linux 仍可列出 port 但擁有者欄標「不明」，macOS 則整個分頁顯示「需 root」。設定檔路徑用絕對路徑（sudo 下 `$HOME` 會變成 `/root`，讀寫 config 必須解析成呼叫者的家目錄） |
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

## 9. 首次啟動設定精靈（Setup Wizard）

**觸發時機**：
- 第一次執行 `asktop`，且找不到設定檔 → 自動進入精靈，不能跳過（至少要跑完 theme 這一步才會進主畫面）
- 之後隨時可用 `asktop setup` 或主畫面內按鍵（建議 `s`）手動重新進入精靈，修改任一項設定

**設定檔位置與格式**：`~/.config/asktop/config.json`（沿用 XDG 慣例；不用 `.env`，因為 asktop 是全域安裝的 CLI 工具，不像典型專案有固定工作目錄）。檔案建立時設權限 `600`（含 API key，比照一般 CLI 工具憑證檔慣例）。

**四個設定項目**：

| 步驟 | 內容 | UI 設計 | 備註 |
|---|---|---|---|
| 1. Model Provider | 選擇 LLM 服務商 | Textual `RadioSet`：**OpenRouter**（預設/主推）、自訂 OpenAI-compatible endpoint（需另外輸入 base URL，為未來擴充留活路，MVP 可先只做 OpenRouter，UI 骨架先留著) | 對齊第 2 節既有選型（OpenRouter），不引入額外 SDK |
| 2. Model | 輸入/選擇要用的 model id | `Input` 文字框 + 幾個常用建議值當 placeholder/快捷鍵帶入（例如 `anthropic/claude-sonnet-4.5`、`openai/gpt-4o-mini`），不做即時抓 model list（避免精靈階段就要求先有 key 才能往下走） | 純文字輸入，不驗證 model 是否存在——留給第 3 步驗證時一併確認 |
| 3. API Key | 輸入服務商金鑰 | `Input(password=True)` 遮罩輸入；確認後立即打一個最小成本的驗證請求（如 OpenRouter `/models` 或極短 completion），畫面顯示「驗證中…」→「✓ 可用」或「✗ 驗證失敗，請重新輸入」 | Key 一律不印在畫面/log／debug 輸出；若偵測到環境變數 `ASKTOP_API_KEY` 已設定，本步驟顯示「偵測到環境變數，將優先使用」並可直接跳過 |
| 4. Theme | 深色／淺色 | `RadioSet`：**Dark**（預設）、Light；選擇當下即時套用預覽（**Textual 8.x 已移除 `App.dark`，改用 `App.theme = "textual-dark" / "textual-light"`**），不用等到精靈結束才看得到效果 | 對齊 Lewis 一貫的「dark mode 預設」偏好（見全域 CLAUDE.md 慣例） |

**流程細節**：
- 精靈用 Textual 多個 `Screen` 串接（或單一 Screen 內用 `Steps`/index 切換），每步都能上一步/下一步，最後一步顯示總結（provider / model / theme，key 只顯示遮罩後幾碼）+「儲存」
- **AI 相關設定（步驟 1–3）可以整組跳過**，不阻擋監控功能——asktop 的 process/流量/port 監控本來就不需要 LLM。跳過後主畫面「AI 詢問」分頁顯示「尚未設定 API Key，按 `s` 執行設定精靈」而非報錯或整個功能消失
- theme（步驟 4）**不可跳過**，因為它是精靈本身就要用的呈現方式，必須有預設值落地（預設 dark，即使使用者直接按 Enter 全部用預設值也算完成）
- 設定完成後寫回 `~/.config/asktop/config.json`，往後啟動直接讀取，不再進精靈（除非手動 `asktop setup`）
- 驗證失敗時不阻塞——允許使用者選擇「先跳過，之後再設」，一樣落地到「AI 功能未啟用」狀態

**與現有章節的關聯**：本節填補第 4.4 節「API、成本與延遲」原本沒講清楚的「key 從哪裡設定」缺口，也讓第 6 節 Phase 1 MVP 的交付範圍更完整（原本只到監控功能，沒有涵蓋『使用者第一次打開要怎麼把 AI 功能設起來』）。

---

## 10. Phase 0 實測記錄

> 環境：macOS（Darwin 23.6.0）本機 + Linux VPS（lewsi.ddns.net，小型機：140 process / 28 連線）。腳本見 `spike/`。

### 10.1 psutil root vs 無 root（`spike/spike_psutil_root.py`）

| 指標 | macOS 一般使用者 | macOS root | Linux 一般使用者 | Linux root |
|---|---|---|---|---|
| `net_connections(kind="inet")` | **AccessDenied，整個拿不到** | 145 條 / 3ms | 28 條 / 5ms | 27 條 / 7ms |
| 其中 pid 可解析 | — | 145（100%） | **10（36%）** | 27（100%） |
| LISTEN | — | 13 | **16** | 16 |
| `process_iter()` | 742 個 / 41ms | 725 個 / 29ms | 140 個 / 32ms | 139 個 / 29ms |
| cmdline 取不到 | 156 個 | 0 個 | **0 個** | 0 個 |

**結論**：

1. **降級行為分平台，不能寫成同一套文案**：
   - **macOS 無 root = 全有全無**，連線表整個 AccessDenied，port 分頁只能顯示「需 root」。
   - **Linux 無 root = 部分可見**，連線拿得到、**LISTEN 數量甚至完全相同（16 = 16）**，只是 36% 才有 pid。所以 Linux 降級模式下 port 分頁仍有實用價值：照常列出 port，PID/程式名欄位標示「不明（需 root）」。
2. **root 下 pid 解析率兩平台皆 100%**，process × 連線的 join 不需要 fallback；原規劃的「解析 `ss -tunlp` 當備援」不必實作。
3. **`net_connections()` 成本被高估一個量級**（3–7ms，非原估的「高」）。第 5 節輪詢策略已據此放寬。**但兩台都是小樣本（145 / 28 條），高連線數情境仍未驗證**，「可見性驅動採集」維持暫緩而非否決。
4. **Linux 無 root 也讀得到全部 cmdline**（`/proc` 預設 world-readable，除非掛 `hidepid`）。隱私遮罩（4.3 節）因此與是否 root 無關，一律必要——asktop 會看到所有使用者的完整命令列，含其中的 key 與連線字串。

### 10.2 nethogs 解析（`spike/spike_nethogs.py`，Linux VPS，15 秒）

原始結果：refresh 16 次（≈1/s，符合 `-d 1`）、解析成功 29 列、失敗 21 列。

1. **數值是累計 KB，不是速率**——這是本節最重要的發現，原規劃隱含假設能直接取得速率。證據：`unknown TCP` 一列連續多次取樣 recv 皆為 `0.0119141`（小數點後七位完全相同，速率不可能如此），而 sshd 的 sent 單調遞增 `0.335 → 0.731 → 0.782 → 0.903 → 1.00`。
   **設計影響**：Phase 2 必須自行對相鄰取樣做差分才能得到速率，並處理 counter 重置（process 結束、nethogs 重啟）與首次取樣無前值的情況。差分為負時視為重置而非負流量。
2. **解析失敗的 21 列全是診斷雜訊，不是格式例外**：`Adding local address: ...`、`Ethernet link detected`、`Unknown connection: <ip:port-ip:port>`。濾掉已知前綴即可，正則本身不需改。
3. **存在無法歸屬的流量**：`pid=0` 搭配程式名 `unknown TCP`。表格需要一個「未歸屬」聚合列，不能靜默丟棄，否則 per-process 流量加總會對不上全域 NIC 流量，使用者會以為工具在說謊。
4. **結論：nethogs 包裝路線可行**，Phase 2 不需要轉 eBPF。

### 10.3 Textual DataTable（`spike/spike_datatable.py`）

VPS 上目測正常，但該機只有 139 個 process，沒測到「200+ 列」情境。改在 macOS（747 列）以 headless（`App.run_test()`）量測增量更新與整表重建：

| 模式 | psutil 採集 | 表格更新 | 游標 |
|---|---|---|---|
| 增量（`update_cell`，只改變動的 25–33 格） | 20–27ms | **1ms** | 黏住原 PID |
| 整表重建（`clear` + `add_row`） | 22–23ms | 6–8ms | 黏住原 PID |

**結論**：

1. **游標穩定性取決於「用 PID 當 row key」，與增量／重建無關。** 兩種模式都不漂移，因為都用 `add_row(key=pid)` + `get_row_index(pid)` 定位。風險 #9 的正解是 row key 綁 PID，不是非用增量不可。
2. **表格更新不是瓶頸，psutil 採集才是**（20–27ms，比渲染貴 3–4 倍）。增量雖快 6–8 倍，絕對差距僅 ~5ms，2 秒刷新無感。**後續若要優化效能，方向在採集端而非渲染端。**
3. 747 列規模下 Textual 無效能疑慮，Phase 1 可自由選擇實作方式；選增量的理由應是避免閃爍與保留 UI 狀態，而非效能。

**量測污染須知**：spike 狀態列顯示的「自身 CPU 37–73%」取自 headless 測試中不間隔連續呼叫 `refresh_table` 的壓測情境，**不代表 2 秒輪詢下的實際負載**，真實數字需互動執行後重新採計。

### 10.4 Phase 2 端到端驗證（`spike/test_phase2.py`，VPS + sudo）

背景下載 20MB 製造流量，nethogs 正確把它歸屬到發起的 process：

```
3s  pid86111:↑6.1 ↓3777.5KB/s   ← curl
    pid81874:↑0.1 ↓0.1KB/s      ← sshd
4s  下載結束後 pid86111 歸零，該列仍留在清單中
未歸屬流量: ↑0.0 ↓0.0 KB/s
ports: 17 個，全部有 PID（root 下無「擁有者不明」）
```

**結論**：

1. **per-process 歸屬正確**，累計值差分成速率的做法成立，Phase 2 主要路徑打通。
2. **流量停止後該列不消失、速率歸零**——回答了 10.4 原本列的一半問題（真正的「process 結束」情境仍未測到，curl 當時尚未退出）。
3. **首次出現的 process 速率可能被高估**：新 pid 第一次進入快照時沒有前值，會拿「累計量 ÷ 單一間隔」當速率。因為 nethogs 自身也是從啟動開始累計，實務上誤差有限，但突發流量的第一秒數字偏高是已知行為。
4. **排序驗證一度得到無效結果**：VPS 上依 ↑KB/s 排序時前幾列是 systemd/kthreadd，看似壞掉——實則當下所有值都是 0.0，穩定排序保留插入順序所致。改用注入固定速率的確定性測試後確認排序正確（50→40→30→20）。**教訓：全零資料無法驗證排序。**

### 10.5 仍待驗證

- **高連線數下的 `net_connections()` 耗時**：兩台實測機都是小樣本（≤145 條），數百至上千條連線的情境尚無資料。
- **nethogs counter 的極端行為**：process 真正結束後該列是否消失、pid 重用時的重置、長時間執行是否溢位。
- ~~**macOS `nettop` 解析**（2.3 節的二級平台路線）完全未碰。~~ 已於 Phase 4 實作，見 10.7。

### 10.6 issue #5 —— tools.py per-process 流量路徑補驗（VPS + sudo，`spike/test_phase5.py`）

macOS 上 `flow()` 恆為 None，`tools._flow_rows` / `_net_rates` / `_top_processes(sort_by="net")` 這條「餵給 AI」的路徑從未真實執行過。在 VPS 以節流 curl（50MB @ 3MB/s）製造已知 pid 的下載後：

1. **歸屬正確**：nethogs 把下載歸回 curl 的 pid，tool 輸出的 `PID + 程式名` 對得上。
2. **未歸屬流量（pid=0）有列出**，不被靜默丟棄。
3. **流量停止後該 pid 歸零**（差分對 counter 停止的處理正確）。
4. `get_net_rates` / `get_top_processes(net)` 走的是 nethogs 分支，而非 macOS 那套降級文案。

**觀察**：nethogs 差分出的速率（curl 113.5K/s）明顯低於全域 NIC 下行（2.6M/s），是首次取樣／平均的已知取樣特性（見 10.4 結論 3），非歸屬錯誤。

**cloudflare speed 端點須知**：`__down?bytes=` 超過上限（實測 300MB）回 403，製造流量用 50MB。

**AI 端到端（2026-07-22 人工確認）**：在 VPS 實際問 AI「誰在吃頻寬」，AI 正確引用 curl 的 per-process 流量。至此 issue #5（tool-data 層自動化）＋ issue #3 主情境（AI 引用，人工）兩軸皆通過。

### 10.7 macOS per-process 流量轉正（Phase 4，`collectors.Nettop` + `spike/test_nettop.py`）

原規劃 macOS 是二級平台、per-process 流量押後（2.3 節）。實測 macOS 內建的 `nettop` 完全可用，遂實作 `Nettop` 類（對稱 `Nethogs`），`asktop` 改由 `flow_monitor()` 依平台選用。實測結論：

1. **nettop 不需要 root**——這是與 Linux 最大的反差。macOS 上 `net_connections()`（port／連線擁有者）非 root 是整個 AccessDenied（10.1），但**流量**經 nettop 一般帳號就拿得到。所以 macOS 非 root 也能有 per-process 流量欄，只是 port 分頁仍需 root。
2. **`-d` delta 模式直接給區間 bytes**，不必像 nethogs 對累計值差分、也不必處理 counter 重置（process 結束就不再出現在樣本裡）。
3. **`nettop -P -x -d -s 1 -J bytes_in,bytes_out -l 0`** 是選定的呼叫：per-process 聚合、關格式化、只留兩個 bytes 欄、持續輸出。樣本以 `time …` 標頭行分隔。
4. **名稱欄含空白且被截斷**（"Google Chrome H"），故 `Nettop` 只回傳 `pid→速率`，名稱一律由 psutil 的 process 清單解析——與 nethogs 路徑一致。
5. **`bytes_in`=下行、`bytes_out`=上行**，映射成 `(up, down)` 對齊 `Nethogs`。
6. `spike/test_nettop.py`（免 root）驗證：節流 curl 精準歸屬到其 pid（↓ 對上 3M 節流）、走流量分支而非降級文案、停止後輪詢最終歸零。headless 亦確認 macOS app 會建立 ↑/↓KB/s 欄、隱藏「未啟用」提示。

**已知取捨**：pid 0 在 macOS 是 kernel_task（真核心流量），會沿用 tools 的「未歸屬」列顯示，語意略有出入但流量通常趨近 0，不特別處理。

---

## TL;DR

- **形式**：TUI（Python + Textual），不做 web 服務——SSH 場景零摩擦、零安全暴露面
- **依賴**：psutil + textual + httpx 三個；`uv` 管理；單檔起步
- **最難的坑**：Linux per-process 流量——**Phase 0 已驗證 nethogs 包裝可行**（但輸出是累計值，需自行差分）。root 需求無法繞過，**預設就以 sudo 執行**，非 root 降級行為分平台（見第 10 節）
- **AI**：OpenRouter + function calling（小摘要+唯讀 tools+輪數上限+cmdline 遮罩，kill 永遠人類確認）
- **設定**：首次啟動精靈引導設定 provider/model/API key/theme，存 `~/.config/asktop/config.json`（600 權限）；AI 設定可跳過不擋監控功能，theme 不可跳過（預設 dark）
- **範圍紀律**：Linux 優先、Windows 不承諾、web 檢視層押後
