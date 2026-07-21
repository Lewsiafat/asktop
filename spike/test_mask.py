"""Phase 3-2 驗證：cmdline 遮罩。

跑法：.venv/bin/python spike/test_mask.py

遮罩與是否 root 無關——/proc 預設 world-readable，asktop 看得到所有使用者的
完整命令列（PLAN.md 10.1 結論 4）。凡 cmdline 出境必經這裡。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mask

ok, failed = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok, failed
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name} {detail}")


def masked(raw: str, secret: str, keep: str = "") -> None:
    """秘密必須消失，但周邊資訊（參數名、程式名）要留著，否則 AI 無從判讀。"""
    out = mask.cmdline(raw)
    check(f"{raw[:52]!r} 遮住秘密", secret not in out, f"→ {out}")
    if keep:
        check(f"{raw[:52]!r} 保留 {keep!r}", keep in out, f"→ {out}")


print("1. 常見參數樣式")
masked("myapp --api-key=sk-live-abc123XYZ --port 8080", "sk-live-abc123XYZ", "--api-key")
masked("myapp --token abc123secret --verbose", "abc123secret", "--token")
masked("mysql -u root --password=hunter2 db", "hunter2", "--password")
masked("app --secret=s3cr3t", "s3cr3t", "--secret")
masked("node server.js --auth-token=eyJhbGciOi.J9", "eyJhbGciOi.J9", "--auth-token")
masked("aws --access-key AKIAIOSFODNN7EXAMPLE s3 ls", "AKIAIOSFODNN7EXAMPLE", "s3 ls")

print("\n2. 環境變數樣式（常出現在 wrapper script 的命令列）")
masked("env DB_PASSWORD=hunter2 python app.py", "hunter2", "python app.py")
masked("env OPENAI_API_KEY=sk-proj-xxx node .", "sk-proj-xxx", "OPENAI_API_KEY")
masked("sh -c 'GITHUB_TOKEN=ghp_abcdef1234 make deploy'", "ghp_abcdef1234", "make deploy")

print("\n3. 連線字串")
masked("psql postgres://admin:sup3rs3cret@db.internal:5432/prod", "sup3rs3cret", "db.internal")
masked("app --dsn mongodb+srv://u:p%40ss@cluster0.net/db", "p%40ss", "cluster0.net")
masked("celery -b redis://:redispw@127.0.0.1:6379/0 worker", "redispw", "127.0.0.1")

print("\n4. Bearer 與裸 token")
masked("curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9' https://api.x/v1", "eyJhbGciOiJIUzI1NiJ9", "api.x")
masked("deploy.sh sk-ant-api03-LONGTOKENVALUE", "sk-ant-api03-LONGTOKENVALUE", "deploy.sh")
masked("gh auth login --with-token ghp_16CharsAtLeastHere", "ghp_16CharsAtLeastHere")

print("\n5. 不該過度遮罩（誤傷會讓 AI 看不懂系統）")
for safe in (
    "/usr/bin/python3 /srv/app/manage.py runserver 0.0.0.0:8000",
    "nginx: worker process",
    "sshd: lewsi@pts/0",
    "ssh -i /home/lewsi/.ssh/id_ed25519 --keyfile-path /etc/x user@host",
    "docker run --monkey=banana -p 8080:80 nginx",
    "postgres: checkpointer process",
):
    check(f"{safe[:48]!r} 原樣保留", mask.cmdline(safe) == safe, f"→ {mask.cmdline(safe)}")

print("\n6. 邊界情況")
check("空字串不炸", mask.cmdline("") == "")
check("遮罩可重複套用（冪等）",
      mask.cmdline(mask.cmdline("app --api-key=abc")) == mask.cmdline("app --api-key=abc"),
      mask.cmdline(mask.cmdline("app --api-key=abc")))
check("大小寫不敏感", "S3CRET" not in mask.cmdline("app --API-KEY=S3CRET"),
      mask.cmdline("app --API-KEY=S3CRET"))
check("多個秘密同時遮掉",
      "aaa" not in (m := mask.cmdline("app --token=aaa --password=bbb")) and "bbb" not in m, m)
long = "app " + "x" * 500
check("可選截斷", len(mask.cmdline(long, limit=100)) <= 100, str(len(mask.cmdline(long, limit=100))))
check("截斷有省略記號", mask.cmdline(long, limit=100).endswith("…"))
check("未超長不加省略記號", not mask.cmdline("app -v", limit=100).endswith("…"))

print(f"\n{ok} 通過 / {failed} 失敗")
sys.exit(1 if failed else 0)
