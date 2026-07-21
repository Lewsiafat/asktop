# 📍 專案狀態報告 — asktop

> 產生時間: 2026-07-21

## 🔀 Git 概況
- **分支:** `main`（共 1 個本地分支）
- **未提交變更:** 0 staged / 1 modified / 4 untracked
  - modified: `CLAUDE.md`（新增 Agent skills 區塊）
  - untracked: `.agents/`、`.claude/`、`docs/`、`skills-lock.json`（皆為 agent skills 設定產物）
- **最近 commit:**
  - `196690e` merge: Phase 0–2 —— 技術驗證、MVP、per-process 流量
  - `266f8ec` docs(phase0-spike): 新增 Phase 0–2 walkthrough 交接文件
  - `e0b7af4` feat: Phase 2 —— per-process 流量（nethogs 包裝）

## 📋 進行中任務
（目前沒有進行中的任務——`specs/phase0-spike-walkthrough.md` 已有 walkthrough，代表 Phase 0–2 已收尾；`temp/` 無進度檔）

依 CLAUDE.md 路線圖，下一個階段是 **Phase 3 — AI 詢問**（OpenRouter client + streaming、摘要 + 6 個唯讀 tools + cmdline 遮罩），尚未開始。

## 🧠 Memory 摘要
（尚未建立 memory 記錄）

## 📁 近期變更檔案
最近一次 merge（Phase 0–2）共 15 檔、+1632/-12：
- `asktop.py` +321、`collectors.py` +264、`wizard.py` +181
- `spike/` 4 支驗證腳本、`PLAN.md` +99、`CLAUDE.md` +85
- ...及 pyproject / uv.lock / README 等

## 💡 建議下一步
1. **Commit skills 設定變更** —— `CLAUDE.md` 修改與 `docs/agents/`、`.claude/`、`skills-lock.json` 等新檔案還在工作區，建議先 commit 保存這次 setup 成果。
2. **開始 Phase 3** —— 用 `/task` 建立「AI 詢問」任務分支，規格來源為 `PLAN.md`（注意硬性約束：唯讀 tools、cmdline 遮罩、tool 回傳 ≤30 列）。
