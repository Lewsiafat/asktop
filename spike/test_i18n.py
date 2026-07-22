"""i18n catalog 驗證（不需 root、不打網路）。

跑法：.venv/bin/python spike/test_i18n.py

確認 en/zh 鍵集合對齊、format 佔位符一致、fallback 行為正確。
en 是回退基準，缺鍵會靜默用英文，很難察覺——所以這裡把「兩語對齊」當硬性條件。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import i18n

ok, failed = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok, failed
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name} {detail}")


def placeholders(s: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", s))


en, zh = i18n.MESSAGES["en"], i18n.MESSAGES["zh"]

check("en/zh 鍵集合完全一致", en.keys() == zh.keys(),
      f"僅 en：{en.keys() - zh.keys()}；僅 zh：{zh.keys() - en.keys()}")

for key in en.keys() & zh.keys():
    check(f"{key} 兩語 format 佔位符一致",
          placeholders(en[key]) == placeholders(zh[key]),
          f"en={placeholders(en[key])} zh={placeholders(zh[key])}")

# fallback：切到未知語言退回英文；缺鍵退回英文；再缺退回 key 本身
i18n.set_lang("zh")
check("set_lang 切換生效", i18n.current() == "zh" and i18n.t("btn_kill") == "終止")
i18n.set_lang("fr")
check("未知語言退回英文預設", i18n.current() == "en" and i18n.t("btn_kill") == "Kill")
check("缺鍵退回 key 本身", i18n.t("__no_such_key__") == "__no_such_key__")

# format 帶參數
i18n.set_lang("en")
check("format 代入具名參數", i18n.t("kill_sent", pid=42) == "Sent SIGTERM to PID 42",
      i18n.t("kill_sent", pid=42))

print(f"\n{ok} 通過 / {failed} 失敗")
sys.exit(1 if failed else 0)
