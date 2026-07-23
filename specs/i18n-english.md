# 文件英文化（英文為主 + 中文版連結）

- **分支:** `docs/i18n-english`
- **日期:** 2026-07-22

## 描述
把面向人類的文件改為**英文為主**，中文版另存 `*.zh-TW.md` 並在兩份頂部互相連結（方案 a）。範圍：`README.md` / `PLAN.md` / `CHANGELOG.md` / `CLAUDE.md`。**排除** `docs/` 與 `specs/`（開發文件維持中文）。

## 佈局
每個 `FILE.md`：
- `FILE.md` — 英文主檔，頂部語言切換列 `**English** | [繁體中文](FILE.zh-TW.md)`
- `FILE.zh-TW.md` — 現有中文內容，頂部 `[English](FILE.md) | **繁體中文**`
- 章節編號／anchors／程式碼區塊逐字保留，確保內部連結不斷。

## 任務清單
- [x] `README.zh-TW.md` = 現有中文；`README.md` 改英文；互連
- [x] `CHANGELOG.zh-TW.md` = 現有中文；`CHANGELOG.md` 改英文；互連
- [x] `CLAUDE.zh-TW.md` = 現有中文；`CLAUDE.md` 改英文；互連
- [x] `PLAN.zh-TW.md` = 現有中文；`PLAN.md` 改英文（章節 1–10／10.1–10.7／4.1–4.4／風險 #1–#9 逐一保留）；互連
- [x] 驗證：8 檔齊備、切換列互連正確、PLAN.md 僅程式碼區塊樣本輸出保留中文

## 備註
- 「英文化」為忠實翻譯，未順手更新已過期內容（例如 README 提到「精靈第 2、3 步」「OpenRouter streaming」——i18n 分支後精靈已有語言步、provider 已多選）。中英兩版保持同步過期，內容更新屬另案。
