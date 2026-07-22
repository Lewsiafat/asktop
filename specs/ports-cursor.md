# Ports 分頁游標刷新漂移修復

- **分支:** `fix/ports-cursor`
- **日期:** 2026-07-22

## 描述
Ports 分頁每 2 秒刷新時，使用者選中的列會跳回最上方。根因在 `tick_ports()`（`asktop.py:336-366`）：以 `table.clear()` 整表重建、`add_row()` 未傳 `key=`、也沒有存/還原游標位置——與 CLAUDE.md「DataTable 用穩定 row key、游標不漂移」的紀律不符（Process 分頁 `tick_procs()` 已正確落實，此處為對照缺口）。

修法：改成增量更新（沿用 `tick_procs` 模式），以 `proto|addr|port|pid` 作為穩定 row key，刷新後依 key 還原游標。此舉同時避免整表重建的閃爍與潛在 DuplicateKey。

## 任務清單
- [x] 新增 `self.port_keys` 狀態（`__init__`，對照 `self.port_rows`）
- [x] `tick_ports()` 改為增量更新：diff 新增/移除 row，`add_row(..., key=…)` 用 `proto|addr|port|pid`
- [x] 刷新前 `cursor_pid(table)` 存游標、刷新後 `move_cursor` 還原
- [x] 驗證：`spike/test_ports.py` headless 驗證游標刷新不漂移（4/4 通過，不需 root）
