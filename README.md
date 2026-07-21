# asktop

一個「看得到網路、問得了 AI」的 htop——把 process 監控、per-process 網路流量、port 占用整合成單一 TUI 介面，並可用自然語言詢問「現在系統怎麼了」。

**狀態：Phase 1 MVP 已實作**（process 表格／全域流量／port 分頁／設定精靈）。
per-process 流量（Phase 2）與 AI 詢問（Phase 3）尚未實作。

```bash
uv sync
sudo .venv/bin/python asktop.py
```

完整規劃文件見 [PLAN.md](./PLAN.md)（Fable5 model 產出，2026-07-21）。

## TL;DR

- 形式：TUI（Python + Textual），不做 web 服務
- 依賴：psutil + textual + httpx
- 最難的坑：Linux per-process 流量監控（需 root，nethogs 優先）
- AI：OpenRouter + function calling，唯讀工具，kill 永遠人類確認
- 平台：Linux 一級、macOS 二級、Windows 不承諾
