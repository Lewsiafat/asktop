# asktop Phase 0–2（技術驗證 → MVP → per-process 流量）— Walkthrough

- **分支:** `phase0-spike`
- **日期:** 2026-07-21

## 變更摘要

把 asktop 從純規劃文件推進到可用工具：先跑 Phase 0 技術驗證 spike 取得真實數據，再據此實作 Phase 1 MVP（process 表格／全域流量／port 分頁／設定精靈）與 Phase 2（per-process 流量）。所有實測結論回寫 PLAN.md 第 10 節，並修正了原規劃中被實測推翻的假設。Phase 3（AI 詢問）未開始。

> 分支名稱只反映起點（Phase 0 spike），實際內容涵蓋 Phase 0/1/2。

## 修改的檔案

**程式碼**

| 檔案 | 說明 |
|---|---|
| `asktop.py` | UI 與主迴圈。三分頁（Process／Ports／AI）、kill 確認框、排序／篩選／暫停 |
| `collectors.py` | 採集層，**不 import textual**（風險 #7 的分層要求）。process、全域流量、listening ports、`Nethogs` per-process 流量、port-registry 解析 |
| `config.py` | 設定讀寫。sudo 下解析回呼叫者家目錄、權限 600、歸還檔案所有權 |
| `wizard.py` | 五步設定精靈（provider／model／API key／theme／確認），AI 步驟可跳過 |
| `pyproject.toml`／`uv.lock`／`.gitignore` | 專案骨架。依賴維持 psutil + textual + httpx 三個 |

**驗證腳本**

| 檔案 | 驗證什麼 |
|---|---|
| `spike/spike_psutil_root.py` | root／無 root 下 psutil 拿得到多少資料 |
| `spike/spike_nethogs.py` | nethogs trace mode 輸出可否穩定解析（Linux only） |
| `spike/spike_datatable.py` | DataTable 增量更新 vs 整表重建、游標穩定性 |
| `spike/test_phase2.py` | per-process 流量端到端（需 Linux + sudo） |

**文件**

- `PLAN.md` — 新增第 10 節實測記錄；修正 2.2／2.3／5／6／7／9 節中被推翻的假設
- `CLAUDE.md` — 新增（專案現況、指令、模組結構、硬性約束）
- `README.md` — 狀態與執行方式

## 技術細節

### Phase 0 實測推翻的原規劃假設

| 原假設 | 實測結果 |
|---|---|
| 非 root 只是「看不到別人的連線」 | **分平台**：Linux 部分可見（28 條中 10 條有 pid，LISTEN 清單完整）；macOS 直接 AccessDenied，全有全無 |
| `net_connections()` 成本高，需 3–5s 且僅可見時查 | 實測 3–7ms，成本高估一個量級。輪詢放寬到 2s，可見性驅動採集暫緩 |
| nethogs 輸出可直接當速率用 | **是累計 KB**，必須自行差分。證據：同一列連續取樣值到小數點後七位完全相同 |
| 需要 `ss -tunlp` 當 pid 解析的 fallback | root 下 pid 解析率 100%，fallback 不必實作 |
| cmdline 遮罩是 root 專屬問題 | Linux `/proc` 預設 world-readable，非 root 也讀得到全部 cmdline，遮罩一律必要 |
| Textual `App.dark` 切換 theme | 8.x 已移除，改用 `App.theme = "textual-dark"／"textual-light"` |
| 單檔 `asktop.py` 起步 | 實作時直接拆四模組，因為 UI／採集分層本來就是硬性架構決策 |

### 關鍵實作決策

**DataTable 一律以 PID 當 row key。** 實測顯示游標穩定性取決於此，與採用增量或整表重建更新無關——兩種模式只要有 key 都不漂移。這是 kill 不殺錯的根本解（風險 #9）。順帶測到：psutil 採集（20–27ms）比表格渲染（1–8ms）貴 3–4 倍，要優化效能該往採集端下手。

**拿不到資料時整欄不建立，而非填 0。** per-process 流量欄在非 Linux／非 root／無 nethogs 時完全不出現，並顯示原因。填 0 會讓「沒資料」看起來像「沒流量」。同理 port 分頁在 Linux 無 root 時照常列出 port 但擁有者標「不明」，在 macOS 則整個提示需 root。

**nethogs 累計值差分。** 差分為負視為 counter 重置，輸出 0 而非負流量。`pid=0` 的未歸屬流量顯示在流量列，不靜默丟棄——否則 per-process 加總對不上全域 NIC 數字，使用者會以為工具在說謊。

**sudo 下的設定檔路徑。** `$HOME` 會變成 `/root`，必須用 `SUDO_USER` 解析回真正的呼叫者家目錄，否則不用 sudo 跑時會讀不到設定、重複跳精靈。寫入後把檔案所有權歸還給該使用者。

### 驗證方式與已知限制

沒有測試框架，驗證靠 Textual headless（`App.run_test()`）手寫腳本。兩個踩過的坑：

- **headless 下連續快速點擊同一 widget，第二次會被吞掉**（Textual 事件合併）。測多步流程改用直接呼叫 handler。
- **全零資料無法驗證排序**。VPS 上依流量排序時前幾列是 systemd/kthreadd，看似壞掉，實則當下所有值都是 0.0，穩定排序保留插入順序。改用注入固定速率的確定性測試才確認正確。

**仍未驗證**（PLAN.md 10.5）：高連線數下的 `net_connections()` 耗時（兩台實測機都 ≤145 條）、process 真正結束後 nethogs 該列是否消失、macOS `nettop` 路線完全未碰。

### 交接給 Phase 3 的注意事項

AI 詢問功能的硬性約束已寫入 CLAUDE.md：AI 沒有任何寫入或 kill 的 tool、cmdline 送 LLM 前必須遮罩、只能引用 tool 回傳的數據、tool 回傳裁切 ≤30 列、輪數上限 4。設定精靈已能設定 provider／model／API key，`config.api_key()` 讓環境變數 `ASKTOP_API_KEY` 優先於設定檔。AI 分頁目前是佔位提示。
