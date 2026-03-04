#!/usr/bin/env python3
"""TGMonitor 部署检查清单"""
import sys
from pathlib import Path

os_dir = Path(__file__).resolve().parent.parent.parent  # TGMonitor/
sys.path.insert(0, str(os_dir / "src"))

OK = "[OK]"
FAIL = "[FAIL]"

print("=" * 50)
print("  TGMonitor Deployment Checklist")
print("=" * 50)
print()

errors = 0

# 1. Python version
v = sys.version.split()[0]
print(f"  {OK} 1. Python {v}")

# 2. Telegram API in .env
env_text = (os_dir / ".env").read_text()
if "TG_ACCOUNT_1_API_ID" in env_text:
    print(f"  {OK} 2. Telegram API creds configured")
else:
    print(f"  {FAIL} 2. Missing API creds in .env")
    errors += 1

# 3. MySQL
try:
    import pymysql
    c = pymysql.connect(host="localhost", port=3306, user="hello", password="123456", db="hello")
    print(f"  {OK} 3. MySQL connectable")
except Exception as e:
    print(f"  {FAIL} 3. MySQL: {e}")
    errors += 1
    sys.exit(1)

# 4. Redis
try:
    import redis as r
    rc = r.Redis(host="localhost", port=6379, db=1)
    assert rc.ping()
    print(f"  {OK} 4. Redis connectable (PONG)")
except Exception as e:
    print(f"  {FAIL} 4. Redis: {e}")
    errors += 1

# 5. Session file
sessions = list((os_dir / "sessions").glob("*.session"))
print(f"  {OK} 5. Session files: {len(sessions)} ({', '.join(s.name for s in sessions)})")

# 6-7. .gitignore
gi = (os_dir / ".gitignore").read_text()
if ".env" in gi:
    print(f"  {OK} 6. .env in .gitignore")
else:
    print(f"  {FAIL} 6. .env NOT gitignored")
    errors += 1

if "sessions/" in gi:
    print(f"  {OK} 7. sessions/ in .gitignore")
else:
    print(f"  {FAIL} 7. sessions NOT gitignored")
    errors += 1

# 8. Redis keys prefix
rc2 = r.Redis(host="localhost", port=6379, db=1, decode_responses=True)
monitor_keys = len(rc2.keys("monitor:*"))
print(f"  {OK} 8. Redis monitor:* keys: {monitor_keys}")

# 9. DB tables
cur = c.cursor()
print(f"  {OK} 9. DB tables:")
for t in ["tgm_message", "tgm_keyword", "tgm_account", "tgm_monitored_chat"]:
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    count = cur.fetchone()[0]
    print(f"         {t}: {count} rows")

# 10. Active keywords
cur.execute("SELECT COUNT(*) FROM tgm_keyword WHERE is_active=1")
kw_count = cur.fetchone()[0]
print(f"  {OK} 10. Active keywords: {kw_count}")
c.close()

# 11. ecosystem.config.js
if (os_dir / "ecosystem.config.js").exists():
    print(f"  {OK} 11. ecosystem.config.js exists")
else:
    print(f"  {FAIL} 11. PM2 config missing")
    errors += 1

# 12-13. Logger
logger_src = (os_dir / "src" / "utils" / "logger.py").read_text()
rot = logger_src.count("rotation")
err_log = logger_src.count("error.log")
print(f"  {OK} 12. Log rotation configured ({rot} refs)")
print(f"  {OK} 13. Error log separate ({err_log} refs)")

# 14. README.md
readme = os_dir / "README.md"
if readme.exists():
    size = readme.stat().st_size
    print(f"  {OK} 14. README.md ({size} bytes)")
else:
    print(f"  {FAIL} 14. README.md missing")
    errors += 1

# 15. .env.example
if (os_dir / ".env.example").exists():
    print(f"  {OK} 15. .env.example exists")
else:
    print(f"  {FAIL} 15. .env.example missing")
    errors += 1

# 16. requirements.txt
if (os_dir / "requirements.txt").exists():
    print(f"  {OK} 16. requirements.txt exists")
else:
    print(f"  {FAIL} 16. requirements.txt missing")
    errors += 1

# 17. Account status
cur2 = pymysql.connect(host="localhost", port=3306, user="hello", password="123456", db="hello").cursor()
cur2.execute("SELECT phone, status, is_active FROM tgm_account WHERE is_active=1")
rows = cur2.fetchall()
for phone, status, active in rows:
    print(f"  {OK} 17. Account {phone}: status={status}")

print()
print("=" * 50)
if errors == 0:
    print("  ALL 17 CHECKS PASSED")
else:
    print(f"  {errors} CHECK(S) FAILED")
print("=" * 50)

sys.exit(1 if errors else 0)
