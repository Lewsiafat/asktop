# Ports 分頁游標刷新漂移修復 — Walkthrough

- **分支:** `fix/ports-cursor`
- **日期:** 2026-07-22

## 變更摘要
修復 Ports 分頁每 2 秒刷新時、選中列會跳回最上方的問題。將 `tick_ports()` 從「整表 `clear()` + 無 key 重建」改為增量更新，並以穩定 row key 於刷新後還原游標——對齊 Process 分頁 `tick_procs()` 早已落實的紀律。

## 修改的檔案
- `asktop.py` — `tick_ports()` 改為增量更新：以 `proto|addr|port|pid` 作為穩定 row key，diff 出新增／移除的列，刷新前用 `cursor_pid()` 存游標、刷新後 `move_cursor()` 依 key 還原；`__init__` 新增 `self.port_keys` 狀態。
- `spike/test_ports.py`（新增）— headless 游標驗證，monkeypatch `collectors.listening_ports` 回固定清單，不需 root、不打網路，4/4 通過。
- `specs/ports-cursor.md`（新增）— 本任務規格。

## 技術細節
- **為何選增量而非「重建 + 還原游標」**：Ports 表格資料列天然唯一鍵是 `proto|addr|port|pid`，非 PID（CLAUDE.md「一律用 PID 當 row key」僅適用於 Process 表格）。以 dict comprehension 建 `fresh` 天然去重，避免 `add_row(key=…)` 在 SO_REUSEPORT／IPv4-IPv6 等罕見重複時拋 `DuplicateKey` 而讓 timer 迴圈崩掉。增量更新也順帶消除整表重建的閃爍，且列序穩定不再每次跳動。
- **游標還原**：沿用既有 `cursor_pid()`（回傳目前列的 row_key.value，與鍵是否為 PID 無關），`if key and key in fresh: move_cursor(row=get_row_index(key), scroll=False)`。
- **未觸及錯誤路徑**：`ConnectionError_`（macOS 非 root）分支維持原樣，只改成功路徑，符合 surgical change。
- **測試資料修正**：驗證用 `ports()` helper 最初以列序決定 port，導致移除頂列時所有 port 位移；改為 port 綁 pid，符合「port 跟著 process 走」的真實情況。
- **回歸**：`mask/llm/tools/summary/ai_ui/wizard` 六支既有 headless 測試全綠。
