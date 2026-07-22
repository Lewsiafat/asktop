# Changelog

本檔案記錄 asktop 的所有重要變更。

格式依循 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)，
版號依循 [語意化版本](https://semver.org/lang/zh-TW/)。

## [0.1.0] - 2026-07-22

### Added

- **macOS per-process 流量**（Phase 4）：新增 `collectors.Nettop`，包裝 macOS 內建的 `nettop`。此前 macOS 上流量欄整欄不建立、只顯示「僅支援 Linux」的提示；現在 macOS 也能在 process 表格看到每支程式的 ↑/↓ 速率，並供 AI 的 `get_net_rates`／`get_top_processes(sort_by="net")` 引用。

  關鍵差異：nettop **不需要 root**（連線／port 擁有者才需要 root），且 `-d` delta 模式直接給區間 bytes，不必像 nethogs 自行差分。`asktop` 改用 `collectors.flow_monitor()` 依平台選 nethogs／nettop，介面相同。新增 `spike/test_nettop.py`（macOS、免 root）驗證歸屬正確與停止後歸零。tools 的 net 描述不再寫死「僅 Linux」。

- `spike/test_phase5.py`（需 Linux + root + nethogs）：補驗 `tools.py` 的 per-process 流量路徑（`_flow_rows` / `_net_rates` / `_top_processes(sort_by="net")`），在 macOS 上永遠走不到、Phase 3 的自動化驗證從未觸及。以節流 curl 製造已知 pid 的下載，確認 nethogs 歸屬正確、pid=0 未歸屬列不被丟棄、流量停止後歸零、走的是 nethogs 分支而非降級文案。對應 [#5](https://github.com/Lewsiafat/asktop/issues/5)，於 VPS 實測通過（PLAN.md 10.6）。

## [0.0.2] - 2026-07-21

### Fixed

- **重跑設定精靈會靜默清掉已設定的 model**（[#4](https://github.com/Lewsiafat/asktop/issues/4)）。在主畫面按 `s` 進精靈、一路按「下一步」到儲存，`model` 會被空字串覆寫，AI 分頁退回「尚未設定」引導文案。API key 反而存活（步驟 3 把空值視為跳過），所以症狀是「key 還在但 AI 突然不能用了」，不容易聯想到是精靈造成的。

  成因是兩個缺陷疊加：輸入框只有 placeholder 沒有回填現值，而「下一步」無條件用輸入框的值覆寫設定。`model`／`base_url`／`provider`／`theme` 四個 widget 改為由現有設定帶入。

- `asktop setup` 原本從預設值重新開始，連 theme 與 port_registry_path 一起重置；改為帶入現有設定，與主畫面按 `s` 行為一致。

### Changed

- API key 欄位刻意不以明文回填（精靈是拿來改設定的，不是拿來看 key 的），改在第 3 步顯示「留空即保留現有的」。「跳過 AI 設定」仍會明確清掉 model 與 key——那是使用者的意圖。

### Added

- `spike/test_wizard.py`（19 項）：涵蓋回填現值、一路按下一步不得改動任何設定、真的編輯要生效、換 key、跳過仍清乾淨、首次啟動不受回填影響、`asktop setup` 與按 `s` 行為一致。驗證腳本總數增至 186 項。

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
