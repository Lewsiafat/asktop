"""極簡 i18n：dict-based message catalog，預設英文、可切繁中。

不引入任何依賴（維持 psutil + textual + httpx 三個依賴的目標）。UI 字串一律
經 t(key, **kw) 取用；缺鍵時回退英文、再回退 key 本身，永不 KeyError。
不 import textual——與 collectors／llm／tools 同一條分層紀律。
"""

DEFAULT_LANG = "en"
LANGS = {"en": "English", "zh": "繁體中文"}   # 選單顯示用；順序即選項順序

_lang = DEFAULT_LANG


def set_lang(lang: str) -> None:
    global _lang
    _lang = lang if lang in MESSAGES else DEFAULT_LANG


def current() -> str:
    return _lang


def t(key: str, **kw: object) -> str:
    s = MESSAGES.get(_lang, {}).get(key) or MESSAGES[DEFAULT_LANG].get(key) or key
    return s.format(**kw) if kw else s


MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        # --- quick questions（同時是送給 AI 的提問文字）---
        "q_status": "What's going on?",
        "q_cpu": "Who's eating CPU?",
        "q_bw": "Who's eating bandwidth?",
        "q_ports": "Which ports, used by whom?",
        # --- process tab ---
        "rate_measuring": "Measuring traffic…",
        "filter_ph": "Filter processes (name / PID / cmdline)",
        "ask_ph": "Ask a question, e.g. What's going on?",
        # --- AI notices ---
        "ai_no_key": "API key not set. Press s to run the setup wizard and enable AI.",
        "ai_no_model": "API key set but no model specified. Press s to run the setup wizard.",
        "ai_empty": "> ⚠️ The model returned no content; check that the model id is correct.",
        # --- flow / net ---
        "flow_disabled": "per-process traffic disabled: {error}",
        "unattributed": "unattributed ↑ {up} ↓ {down}",
        # --- ports ---
        "ports_no_conn": ("Cannot read the connection table (root required).\n"
                          "This platform exposes no connection data without root; run asktop with sudo."),
        "ports_unknown": "{n} port(s) have an unknown owner (root required to see the PID).",
        # --- status bar ---
        "status_line": "{n} processes | self CPU {cpu} | {state}",
        "state_paused": "paused (p to resume)",
        "state_running": "running",
        # --- kill ---
        "kill_select": "Select a row in the Process tab first",
        "kill_sent": "Sent SIGTERM to PID {pid}",
        "kill_failed": "Kill failed: {error}",
        "kill_confirm": "Send SIGTERM to PID {pid} ({name})?",
        "btn_cancel": "Cancel",
        "btn_kill": "Kill",
        # --- setup ---
        "setup_saved": "Settings saved to {path}",
        # --- column headers（PID / CPU% / MEM% / ↑KB/s / ↓KB/s / Port 兩語相同，不列）---
        "col_user": "USER",
        "col_name": "NAME",
        "col_proto": "PROTO",
        "col_addr": "ADDRESS",
        "col_program": "PROGRAM",
        "col_project": "PROJECT",
        # --- misc ---
        "win_unsupported": "Windows is out of scope (see PLAN.md §2.3)",
        # --- tool status lines（tools.STATUS）---
        "tool_get_top_processes": "Querying top resource-using processes…",
        "tool_get_process_detail": "Querying process detail…",
        "tool_get_connections": "Querying network connections…",
        "tool_get_listening_ports": "Querying listening ports…",
        "tool_get_net_rates": "Querying network rates…",
        "tool_search_process": "Searching processes…",
        "tool_generic": "Running {name}…",
        # --- wizard step names（title = "{i}/{n} {name}"）---
        "wiz_s_lang": "Language",
        "wiz_s_provider": "Provider",
        "wiz_s_model": "Model",
        "wiz_s_key": "API Key",
        "wiz_s_theme": "Appearance",
        "wiz_s_confirm": "Confirm",
        # --- wizard labels ---
        "wiz_pick_lang": "Choose a language:",
        "wiz_pick_provider": "Choose an LLM provider:",
        "wiz_provider_custom": "Custom (OpenAI-compatible endpoint)",
        "wiz_base_ph": "base URL",
        "wiz_model_label": "Model id to use:",
        "wiz_key_label": "API Key:",
        "wiz_key_ph": "your API key",
        "wiz_key_hint_have": "A key is already set; leave blank to keep it, or enter a new one to replace it.",
        "wiz_key_hint_none": "Leave blank to skip for now; you can run asktop setup later.",
        "wiz_theme_label": "Appearance (applied immediately):",
        "wiz_theme_dark": "Dark (default)",
        "wiz_theme_light": "Light",
        "btn_back": "Back",
        "btn_next": "Next",
        "btn_save": "Save",
        "btn_skip": "Skip AI setup",
        "wiz_env_key": "Detected the ASKTOP_API_KEY env var; it takes precedence — you can skip the API Key step.",
        "wiz_custom_need_url": "A custom endpoint needs a base URL.",
        "wiz_verifying": "Verifying…",
        "wiz_verify_ok": "✓ Works, press Next to continue",
        "wiz_verify_bad": "✗ Verification failed (HTTP {code}); you can still press Next to skip",
        "wiz_verify_err": "✗ Connection failed ({err}); you can still press Next to skip",
        "wiz_ai_off": "AI: disabled (run asktop setup later to configure)",
        "wiz_sum_provider": "Provider: {provider}",
        "wiz_sum_model": "Model: {model}",
        "wiz_sum_key": "API Key: {masked}",
        "wiz_model_blank": "(blank)",
        "wiz_sum_theme": "Appearance: {theme}",
        "wiz_sum_path": "Settings will be written to {path} (mode 600)",
        # --- AI 回覆語言指示（llm.system_prompt）---
        "ai_reply_rule": "Always reply in English, concise and direct, no small talk.",
    },
    "zh": {
        "q_status": "現在系統怎麼了",
        "q_cpu": "誰在吃 CPU",
        "q_bw": "誰在吃頻寬",
        "q_ports": "哪些 port 被誰占用",
        "rate_measuring": "流量量測中…",
        "filter_ph": "篩選 process（名稱／PID／cmdline）",
        "ask_ph": "問問題，例如：現在系統怎麼了",
        "ai_no_key": "尚未設定 API Key，按 s 執行設定精靈即可啟用 AI 詢問。",
        "ai_no_model": "已設定 API Key 但未指定 model，按 s 執行設定精靈補上。",
        "ai_empty": "> ⚠️ 模型沒有回傳任何內容，請確認 model id 是否正確。",
        "flow_disabled": "per-process 流量未啟用：{error}",
        "unattributed": "未歸屬 ↑ {up} ↓ {down}",
        "ports_no_conn": ("無法取得連線表（需 root）。\n"
                          "此平台在非 root 下完全拿不到連線資料，請改用 sudo 執行 asktop。"),
        "ports_unknown": "{n} 個 port 的擁有者不明（需 root 才看得到 PID）。",
        "status_line": "{n} 個 process | 自身 CPU {cpu} | {state}",
        "state_paused": "已暫停（p 恢復）",
        "state_running": "執行中",
        "kill_select": "請先在 Process 分頁選一列",
        "kill_sent": "已送出 SIGTERM 給 PID {pid}",
        "kill_failed": "終止失敗：{error}",
        "kill_confirm": "送出 SIGTERM 給 PID {pid}（{name}）？",
        "btn_cancel": "取消",
        "btn_kill": "終止",
        "setup_saved": "設定已儲存至 {path}",
        "col_user": "使用者",
        "col_name": "名稱",
        "col_proto": "協定",
        "col_addr": "位址",
        "col_program": "程式",
        "col_project": "專案",
        "win_unsupported": "Windows 不在支援範圍內（見 PLAN.md 第 2.3 節）",
        "tool_get_top_processes": "查詢資源用量最高的 process…",
        "tool_get_process_detail": "查詢 process 詳情…",
        "tool_get_connections": "查詢網路連線…",
        "tool_get_listening_ports": "查詢 listening ports…",
        "tool_get_net_rates": "查詢網路速率…",
        "tool_search_process": "搜尋 process…",
        "tool_generic": "執行 {name}…",
        "wiz_s_lang": "語言",
        "wiz_s_provider": "服務商",
        "wiz_s_model": "Model",
        "wiz_s_key": "API Key",
        "wiz_s_theme": "外觀",
        "wiz_s_confirm": "確認",
        "wiz_pick_lang": "選擇語言：",
        "wiz_pick_provider": "選擇 LLM 服務商：",
        "wiz_provider_custom": "自訂（OpenAI-compatible endpoint）",
        "wiz_base_ph": "base URL",
        "wiz_model_label": "要使用的 model id：",
        "wiz_key_label": "API Key：",
        "wiz_key_ph": "你的 API key",
        "wiz_key_hint_have": "已設定過 key，留空即保留現有的；要換才輸入新的。",
        "wiz_key_hint_none": "留空代表暫不設定，日後可再執行 asktop setup。",
        "wiz_theme_label": "外觀（選擇後立即套用）：",
        "wiz_theme_dark": "Dark（預設）",
        "wiz_theme_light": "Light",
        "btn_back": "上一步",
        "btn_next": "下一步",
        "btn_save": "儲存",
        "btn_skip": "跳過 AI 設定",
        "wiz_env_key": "偵測到環境變數 ASKTOP_API_KEY，將優先使用——API Key 步驟可直接跳過。",
        "wiz_custom_need_url": "自訂 endpoint 需要填 base URL。",
        "wiz_verifying": "驗證中…",
        "wiz_verify_ok": "✓ 可用，按「下一步」繼續",
        "wiz_verify_bad": "✗ 驗證失敗（HTTP {code}），仍可按「下一步」略過",
        "wiz_verify_err": "✗ 連線失敗（{err}），仍可按「下一步」略過",
        "wiz_ai_off": "AI 功能：未啟用（可日後執行 asktop setup 設定）",
        "wiz_sum_provider": "服務商：{provider}",
        "wiz_sum_model": "Model：{model}",
        "wiz_sum_key": "API Key：{masked}",
        "wiz_model_blank": "（未填）",
        "wiz_sum_theme": "外觀：{theme}",
        "wiz_sum_path": "設定將寫入 {path}（權限 600）",
        "ai_reply_rule": "一律以繁體中文回答，語氣精簡直接，不寒暄。",
    },
}
