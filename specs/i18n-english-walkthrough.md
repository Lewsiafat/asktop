# 文件英文化（英文為主 + 中文版連結） — Walkthrough

- **分支:** `docs/i18n-english`
- **日期:** 2026-07-23

## 變更摘要
把面向人類的文件改為英文為主：`README.md` / `PLAN.md` / `CHANGELOG.md` / `CLAUDE.md` 四份主檔英文化，現有中文內容另存為對應 `*.zh-TW.md`，兩份於頂部以語言切換列互相連結（方案 a）。`docs/` 與 `specs/` 依指示排除。

## 修改的檔案
- `README.md` / `CHANGELOG.md` / `CLAUDE.md`（改英文）— 忠實英文化並在頂部加 `**English** | [繁體中文](*.zh-TW.md)`。
- `PLAN.md`（改英文，321→323 行）— 由子代理忠實翻譯：章節 1–10、10.1–10.7、4.1–4.4、風險 #1–#9、表格與程式碼區塊逐一 1:1 對應。
- `README.zh-TW.md` / `CHANGELOG.zh-TW.md` / `CLAUDE.zh-TW.md` / `PLAN.zh-TW.md`（新增）— 現有中文原文，頂部加 `[English](*.md) | **繁體中文**`。
- `specs/i18n-english.md`（新增）— 本任務規格。

## 技術細節
- **佈局**：`FILE.md`（英文主）＋ `FILE.zh-TW.md`（中文），互為鏡像；章節編號／anchors／程式碼區塊逐字保留，內部與外部連結不斷。
- **PLAN.md 委派子代理**（321 行權威規格）以節省主脈絡；嚴格指示「忠實翻譯、不更新過期內容、不重排」。唯一保留中文處是第 269 行程式碼區塊內的樣本輸出（`未歸屬流量: …`），屬「code blocks 不動」規則的正確結果。
- **CLAUDE.md 一併英文化**（依使用者「其他都要」）：現在 Claude Code 讀取的專案指令為英文版，`CLAUDE.zh-TW.md` 為對照。「語言慣例」一節仍載明溝通/註解/AI 回覆預設繁中，行為不變。
- **翻譯忠實、未更新內容**：README/PLAN 仍寫「精靈第 2、3 步」「OpenRouter streaming」等——`feat/i18n-and-providers` 後精靈已有語言步、provider 已多選。中英兩版保持同步過期，內容更新屬另案（可另開 `docs/refresh-content`）。
- **驗證**：8 檔齊備；`head -1` 抽查各檔切換列互連正確；PLAN.md 除樣本輸出外無殘留中文段落；`*.zh-TW.md` 確認仍為中文。
