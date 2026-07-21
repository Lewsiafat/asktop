# Changelog

本檔案記錄 asktop 的所有重要變更。

格式依循 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)，
版號依循 [語意化版本](https://semver.org/lang/zh-TW/)。

## [0.0.1] - 2026-07-21

第一個標記版本，涵蓋 PLAN.md 承諾的 Phase 1–3 全部範圍。

### Added

**Process 監控（Phase 1）**

- process 表格：PID／使用者／CPU%／MEM%／名稱，任一欄排序、即時篩選
- kill（SIGTERM + 二次確認）。確認框綁 PID 不綁列位置，顯示 PID + 名稱 + cmdline
- 全域網路流量即時速率與 sparkline（保留約 2 分鐘）
- Port 占用分頁：listening ports 表格，可對照 `port-registry.json` 標註所屬專案
- 首次啟動設定精靈（provider／model／API key／theme／確認五步）。AI 相關步驟可整組跳過，不擋住監控功能
- 暫停鍵、自身 CPU% 顯示（監控工具自己不能成為負載）

**Per-process 流量（Phase 2）**

- 包裝 `nethogs -t`，上下行速率併入 process 表格
- 累計 KB 自行差分成速率；差分為負視為 counter 重置
- `pid=0` 的流量歸入「未歸屬」列顯示，不靜默丟棄——否則 per-process 加總對不上全域數字
- 僅 Linux + root + 有 nethogs 時啟用；其餘情況流量欄整欄不建立（填 0 會讓「沒資料」看起來像「沒流量」）

**AI 詢問（Phase 3）**

- AI 對話分頁：OpenRouter（OpenAI-compatible）streaming，Markdown 逐字呈現，繁體中文
- 壓縮系統摘要注入 system prompt：hostname／uptime／load／CPU-mem 總覽／CPU 與記憶體前 5 名／目前速率／listening port 數
- Function calling agent loop 搭配六個**唯讀** tool：`get_top_processes`、`get_process_detail`、`get_connections`、`get_listening_ports`、`get_net_rates`、`search_process`
- cmdline 機密遮罩（`mask.py`）：`--api-key=`、`KEY=VALUE`、`--token VALUE`、`Bearer`、`scheme://user:pass@`、`sk-`／`ghp_`／`AKIA` 等裸 token
- tool call 進行中於對話區顯示狀態行；四個一鍵送出的快捷問題
- 未設定 API key／model 時顯示引導文案而非錯誤

**驗證腳本**

- `spike/` 下新增 `test_mask`／`test_llm`／`test_summary`／`test_tools`／`test_ai_ui` 共 167 項檢查，不裝 pytest（維持三個依賴的目標）
- LLM 相關測試以 `httpx.MockTransport` 進行，不打真實網路
- Phase 0 技術驗證腳本：`spike_psutil_root`／`spike_nethogs`／`spike_datatable`／`test_phase2`

### Security

- AI 沒有任何寫入或 kill 的 tool。破壞性操作永遠由人類在 UI 確認執行
- cmdline 送 LLM 前一律遮罩，與是否 root 無關（Linux `/proc` 預設 world-readable，非 root 也讀得到所有使用者的完整命令列）
- tool 回傳裁切 ≤30 列、cmdline 截斷；tool call 輪數上限 4 輪
- API key 不進畫面／log／debug 輸出；錯誤訊息只取例外類別與訊息，不用 `repr`（httpx 的 repr 會帶 request 物件，含授權標頭）
- 設定檔 `~/.config/asktop/config.json` 建立時設權限 600；sudo 執行時解析回呼叫者家目錄並歸還檔案所有權

### Known limitations

- per-process 流量僅 Linux + root + nethogs；macOS 的 `nettop` 路線尚未實作
- Windows 明確不支援
- `asktop.py setup` 從預設值重新開始，不載入現有設定檔（主畫面按 `s` 則正確帶入現值）
- 高連線數（數百至上千條）下的 `net_connections()` 耗時尚無實測資料
