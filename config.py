"""設定檔讀寫。

sudo 執行時 `$HOME` 會變成 `/root`，設定必須落在真正呼叫者的家目錄，
否則使用者不用 sudo 跑的時候會讀不到、重複跳設定精靈（見 PLAN.md 風險 #2）。
"""

import json
import os
import pwd
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "lang": "en",
    "provider": "openrouter",
    "base_url": "https://openrouter.ai/api/v1",
    "model": "",
    "api_key": "",
    "theme": "textual-dark",
    "port_registry_path": "/srv/projects/port-registry.json",
}

# LLM 服務商 preset：全走各家的 OpenAI-compatible endpoint，llm.py 核心不變，
# 切 provider 的實際效果就是換 base_url。custom 由使用者自填 base_url。
PROVIDERS: dict[str, dict[str, str]] = {
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
                   "hint": "anthropic/claude-sonnet-4.5"},
    "openai":     {"label": "OpenAI", "base_url": "https://api.openai.com/v1",
                   "hint": "gpt-4o-mini"},
    "claude":     {"label": "Claude (Anthropic)", "base_url": "https://api.anthropic.com/v1",
                   "hint": "claude-sonnet-4-5"},
    "gemini":     {"label": "Gemini",
                   "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                   "hint": "gemini-2.0-flash"},
    "custom":     {"label": "Custom", "base_url": "", "hint": "provider/model-id"},
}
PROVIDER_ORDER = ["openrouter", "openai", "claude", "gemini", "custom"]


def caller_home() -> Path:
    """sudo 下解析回原呼叫者的家目錄。"""
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except KeyError:
            pass
    return Path.home()


def config_path() -> Path:
    return caller_home() / ".config" / "asktop" / "config.json"


def load() -> dict[str, Any] | None:
    """回傳設定；檔案不存在或壞掉時回 None，由呼叫端決定要不要跑精靈。"""
    path = config_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return {**DEFAULTS, **data} if isinstance(data, dict) else None


def save(cfg: dict[str, Any]) -> Path:
    """寫入設定，權限 600。sudo 執行時把檔案歸還給原使用者。"""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    path.chmod(0o600)

    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and os.geteuid() == 0:
        try:
            entry = pwd.getpwnam(sudo_user)
            os.chown(path, entry.pw_uid, entry.pw_gid)
            os.chown(path.parent, entry.pw_uid, entry.pw_gid)
        except (KeyError, OSError):
            pass  # 歸還失敗不影響功能，只是檔案留在 root 名下
    return path


def api_key(cfg: dict[str, Any]) -> str:
    """環境變數優先於設定檔（見 PLAN.md 第 9 節步驟 3）。"""
    return os.environ.get("ASKTOP_API_KEY") or cfg.get("api_key", "")
