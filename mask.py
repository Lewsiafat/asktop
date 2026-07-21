"""cmdline 遮罩——任何命令列出境（送 LLM）前的必經關卡。

為什麼一律必要：Linux `/proc` 預設 world-readable，**非 root 也讀得到所有使用者的
完整命令列**（PLAN.md 10.1 結論 4）。asktop 看得到的東西遠比使用者以為的多，
`--api-key=`、DB 連線字串、Bearer token 全都在裡面。

設計取捨：**寧可漏遮一點也不能誤遮太多**——把 `/usr/bin/python3 manage.py` 遮成
`***` 會讓 AI 完全看不懂系統。因此參數名採「結尾比對」（`--api-key` 中，
`--keyfile-path` 否），不做無差別的長字串遮蔽。

純函式、無 I/O、不 import 任何專案模組，方便獨立驗證（spike/test_mask.py）。
"""

import re

REDACTED = "***"

# 參數名結尾若是這些字，其值視為機密。順序由長到短，讓 `api_key` 先於 `key` 命中。
_SENSITIVE = (
    r"(?:api[_-]?key|access[_-]?key|secret[_-]?key|private[_-]?key|auth[_-]?token|"
    r"refresh[_-]?token|client[_-]?secret|password|passwd|credentials?|token|secret|pwd|key)"
)
# 允許 `DB_PASSWORD`、`--api-key`、`OPENAI_API_KEY` 這類前綴，但前綴必須以分隔符收尾，
# 否則 `--monkey` 會被當成 `key`
_NAME = rf"(?:[\w.]+[-_.])?{_SENSITIVE}"

# scheme://user:pass@host —— 只遮密碼，主機仍要看得見，否則 AI 無法判斷連的是哪台
_URL_CRED = re.compile(r"([a-z][\w+.-]*://[^:@/\s]*:)([^@/\s]+)@", re.I)
_BEARER = re.compile(r"\b(bearer\s+)\S+", re.I)
_ASSIGN = re.compile(rf"\b({_NAME})=(\S+)", re.I)
_FLAG_VALUE = re.compile(rf"(--?{_NAME})(\s+)(?!-)\S+", re.I)
# 沒有參數名包裝、單憑前綴就認得出來的 token
_BARE_TOKEN = re.compile(
    r"\b(sk-|ghp_|gho_|ghs_|ghu_|github_pat_|glpat-|xox[baprs]-|hf_|npm_|AIza|ya29\.)"
    r"[\w.\-]{8,}"
)
_AWS_KEY = re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{12,}")


def cmdline(text: str, limit: int | None = None) -> str:
    """遮蔽命令列中的機密值；`limit` 給定時一併截斷（tool 回傳用）。

    冪等：對已遮罩過的字串再跑一次結果相同。
    """
    if not text:
        return text
    text = _URL_CRED.sub(rf"\1{REDACTED}@", text)
    text = _BEARER.sub(rf"\1{REDACTED}", text)
    text = _ASSIGN.sub(rf"\1={REDACTED}", text)
    text = _FLAG_VALUE.sub(rf"\1\2{REDACTED}", text)
    text = _BARE_TOKEN.sub(rf"\1{REDACTED}", text)
    text = _AWS_KEY.sub(rf"\1{REDACTED}", text)
    if limit is not None and len(text) > limit:
        text = text[: limit - 1] + "…"
    return text
