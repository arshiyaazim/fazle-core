# Fazle Core — ফাইনাল অডিট ও গো-লাইভ রানবুক

**তারিখ:** ২০২৬-১০-২৭
**ব্র্যাঞ্চ:** `arena/b61ea405-fazle-core` (base `3eabdd3`)
**পদ্ধতি:** সোর্স-কোড রিভিউ নয় — আসল PostgreSQL 16.2-এ ফ্রেশ বিল্ড, আসল
অ্যাপ বুট, আসল HTTP কল, আসল টেস্ট রান। সব সংখ্যা নিচে পুনরুৎপাদনযোগ্য।

---

## ০. এক লাইনে রায়

> **অ্যাপটা জীবন্ত ও কাজ করে — কিন্তু এই রিপো থেকে শূন্য (empty) ডেটাবেসে
> নতুন ডিপ্লয়মেন্ট করা oggi অসম্ভব, আর CI এখন সম্পূর্ণ বন্ধ (GitHub billing
> lock)। লাইভ করতে হলে আগে ডেটাবেস তৈরি/রিস্টোর আর CI—এই দুটো পথ ঠিক করতে হবে।**

যা যাচাই হয়েছে:

| যাচাই | ফল |
|---|---|
| `compileall` (app, modules, scripts, shared) | ✅ ত্রুটি নেই |
| অ্যাপ বুট (`uvicorn app.main:app`) | ✅ `Application startup complete` |
| `/` ড্যাশবোর্ড, `/docs` | ✅ 200 |
| API auth (`X-Internal-Key`) | ✅ ঠিক key=200, key নেই/ভুল=403 |
| RAG স্টার্টআপ বিল্ড | ✅ ১৪,২৩১ ডক ইনডেক্স হলো |
| **ফ্রেশ DB-তে `db/migrate.py`** | ❌ **৯৬টির মধ্যে ৫৫টি মাইগ্রেশন ফেল** |
| `/health` | ⚠️ 503 (আংশিক স্কিমা) — নিচে ৫ নম্বর ফলাফল দেখুন |
| CI (GitHub Actions) | ❌ **কোনো জব-ই চলে না** — billing lock |

---

## ১. P0 — ফ্রেশ ডেটাবেস এই রিপো থেকে তৈরি হয় না (গো-লাইভ ব্লকার #১)

README §4-এর ধাপ ৪ বলছে:

```bash
python db/migrate.py --dry-run
python db/migrate.py
```

খালি PostgreSQL 16.2-এ ঠিক এটাই চালালাম:

```
applied 001, 002
FAIL 003_kb_schema_fix_and_recruitment.sql
     -> UndefinedColumnError: column "status" does not exist
```

**কারণ:** `002_align_tables.sql` আগেই `fazle_recruitment_sessions` টেবিল বানায়
(`collection_step`/`funnel_stage` সহ, `status` ছাড়া)। ফলে 003-এর
`CREATE TABLE IF NOT EXISTS` কিছুই করে না, কিন্তু তার পরের
`CREATE UNIQUE INDEX ... WHERE status = 'active'` অচেনা কলামে আছড়ে পড়ে।
`migrate.py` ফেল করলে সেখানেই থামে।

> **এই একটা বাগ এখন ঠিক করা হয়েছে** (§৭ দেখুন)।

কিন্তু ০০৩ ঠিক করার পরেও ছবিটা ভালো নয়। টেস্ট-হারনেসের base schema
(`tests/conftest.py`-এর `_BASE_SCHEMA_SQL`) দিয়ে DB ভরে আবার চালালাম:

```
with base schema: applied 73/96, failed 23      (০০৩ ফিক্সের পরে 74/96)
public tables: 89
```

### ১.ক যেসব টেবিল কোনো মাইগ্রেশনই তৈরি করে না

`db/migrations/`-এ `CREATE TABLE` নেই, কিন্তু মাইগ্রেশনগুলো এদের ধরে এগোয়:

| টেবিল | কে ধরে | ফলাফল |
|---|---|---|
| `fpe_employees` → `fazle_employees` | 030, 046, 063, 066, 096 | ফেল |
| `fpe_cash_transactions` → `fazle_cash_transactions` | 039, 063, 094 | ফেল |
| `fpe_employee_ledger` → `fazle_employee_ledger` | 095 | ফেল |
| `fpe_income_transactions` | 023 | ফেল |
| `wbom_candidates` | 062, 072, 077 | ফেল |
| `escort_order_lighters` | 024 | ফেল |
| `wbom_employees_legacy` | 066, 093 | ফেল |

এগুলো এখন শুধু **প্রোডাকশন ডাম্পে** আছে। এমনকি `_BASE_SCHEMA_SQL`-এর মধ্যেও
এদের সব নেই — তাই base stub দিয়েও ২২টি মাইগ্রেশন ফেলে।

**অর্থাৎ এই রিপো একা একটি সম্পূর্ণ স্কিমা বর্ণনা করে না।**
`db/MIGRATION_INVENTORY.md`-এ লেখা আছে “Verified end to end on PostgreSQL 16.2:
fresh build” — বাস্তবে শূন্য DB থেকে fresh build হয় না। এই ডকুমেন্টটা
সংশোধন করা দরকার।

### ১.খ দুইটা সমাধান-পথ (একটা বেছে নিতে হবে)

**পথ A — স্কিমা স্ন্যাপশট (দ্রুত, নিরাপদ, সুপারিশকৃত):**

```bash
# প্রোডাকশনে (read-only)
pg_dump --schema-only --no-owner --no-privileges "$PROD_URL" > db/schema_baseline.sql
# রিপোতে কমিট করে db/migrate.py-কে প্রথমে সেটা অ্যাপ্লাই করান (শুধু ফাঁকা DB-তে)
```

**পথ B — base schema-কে প্রথম-শ্রেণির নাগরিক বানানো:**
`tests/conftest.py`-এর ২০ KB `_BASE_SCHEMA_SQL` কে `db/base_schema.sql`-এ তুলে
আনুন, বাকি ৭টি টেবিলের `CREATE TABLE` প্রোডাকশন থেকে নিয়ে তাতে যোগ করুন, আর
`migrate.py` ফাঁকা DB পেলে আগে সেটাই চালাক। এতে স্কিমা সত্যিই
রিপো-থেকে-পুনরুৎপাদনযোগ্য হবে।

> দুটোর কোনোটাই এখনো করা হয়নি — এটা মালিকের সিদ্ধান্ত (A না B), তাই শুধু
> রিপোর্ট করা হলো। ০০৩-এর মতো নির্বিঘ্ন বাগ শুধু ঠিক করেছি।

---

## ২. P0 — CI সম্পূর্ণ বন্ধ (গো-লাইভ ব্লকার #২)

`main`-এর সর্বশেষ commit-এ দুইটা ওয়ার্কফ্লো fail: `CI` (ci.yml) এবং
`CI — Test Suite` (ci-test.yml)। কিন্তু **ফেলটা কোডের নয়** — GitHub-এর
annotation হুবহু বলছে:

```
The job was not started because your account is locked due to a billing issue.
```

মানে: গত ২৭ তারিখে `main`-এ merge হওয়া PR-সহ **কোনো commit-ই আর
টেস্ট/লিন্ট গেট পাচ্ছে না**। অন্ধকারে ডিপ্লয় হচ্ছে।

**করতে হবে:** GitHub Billing ঠিক করুন (অথবা self-hosted runner-এ ওই দুই
ওয়ার্কফ্লো চালান)। এটা ঠিক হওয়ার আগে “CI pass” দিয়ে কোনো সিদ্ধান্ত নেওয়া যাবে না।

দ্বিতীয় সমস্যা: `ci-test.yml`-এর `working-directory: core/` — কিন্তু রিপো
রুটেই অ্যাপ, `core/` ডিরেক্টরি নেই। billing ঠিক হলেও ওই ওয়ার্কফ্লো
“No such directory”-তে ফেল করবে।

---

## ৩. P0 — `pg_trgm` এক্সটেনশন ছাড়া বুটস্ট্র্যাপ মাইগ্রেশন 029 ফেলে

`029_bootstrap_core_tables_schema_record.sql` (২,৪০৭ লাইন) হলো আসল
বুটস্ট্র্যাপ — `fazle_outbound_queue`, `fazle_contacts`,
`fazle_whatsapp_messages`, `wbom_relation_types` ইত্যাদি এটাই বানায়। এর
৪৮ নম্বর লাইন:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

আমার স্যান্ডবক্সের PostgreSQL বিল্ডে contrib নেই, তাই:

```
029 -> FeatureNotSupportedError: extension "pg_trgm" is not available
```

**ফলে যা ঘটে:** `fazle_outbound_queue` তৈরি হয় না → outbound worker আর
`/health` — দুটোই critical।

**গো-লাইভ চেকলিস্টে যোগ করুন:** `postgresql-contrib` ইনস্টল থাকতে হবে এবং
মাইগ্রেশন চালানো ইউজারের `CREATE EXTENSION` (সুপারইউজার/`rds_superuser`)
অনুমতি থাকতে হবে। এটা কোথাও ডকুমেন্টেড নেই।

---

## ৪. P1 — `.env`-এর মান `os.getenv()`-এ পৌঁছায় না (নীরব কনফিগ-ফাঁদ)

অ্যাপ কনফিগ পড়ে `pydantic-settings` দিয়ে (`.env` ফাইল পড়ে), কিন্তু কিছু
সুইচ **সরাসরি** `os.getenv()` দিয়ে পড়া হয়। কোথাও `load_dotenv()` কল হয় না।
প্রমাণ (`.env`-এ `OUTBOUND_ENABLED=true` রাখা সত্ত্বেও):

```
Settings sees DATABASE_URL      : True
Settings sees INTERNAL_API_KEY  : True
os.getenv OUTBOUND_ENABLED      : None      <-- .env পড়া হয়নি
os.getenv USE_OUTBOUND_QUEUE    : None
os.getenv QDRANT_HOST           : None
```

যে সেটিংস এভাবে পড়া হয় (অর্থাৎ `.env`-এ রাখলে **কাজ করবে না**):
`OUTBOUND_ENABLED`, `USE_OUTBOUND_QUEUE`, `SOCIAL_AUTO_REPLY_SINGLE_ENGINE`,
`QDRANT_HOST`, `QDRANT_PORT`, `BACKUP_DIR`, `AGENT_PROACTIVE_OUTBOUND_ENABLED`।

**ফল:** আপনি `.env`-এ `OUTBOUND_ENABLED=true` দিয়ে ভাববেন পাঠানো চালু হয়েছে,
কিন্তু `app/bridge.py` তখনো “send-control enable skipped: OUTBOUND_ENABLED is
not true” লগ করবে।

**সমাধান (এখনই):** `.env` কে প্রসেস-এনভায়রনমেন্টে তুলুন —
systemd-এ `EnvironmentFile=/home/azim/core/.env` (service ফাইলে আছে ✅), বা
Docker-এ `--env-file`, বা শেল-এ `set -a; . ./.env; set +a`।
**স্থায়ী সমাধান:** `app/config.py`-এ ওই কী-গুলো `Settings`-এ সরান, বা
`app/main.py`-এর শুরুতে `load_dotenv()` ডাকুন।

---

## ৫. P1 — `/health` 503 মানে “ডাউন” নয়, কিন্তু মনিটরিং বিভ্রান্ত হবে

আংশিক স্কিমায় চালানো অ্যাপের `/health`:

```json
{"status":"critical","probes":{
  "db":{"status":"ok","value":1},
  "bridge1_db":{"status":"critical","error":"bridge1 db not found"},
  "bridge_poller_b1":{"status":"critical","error":"column \"service\" does not exist"},
  "outbound":{"status":"critical","error":"relation \"fazle_outbound_queue\" does not exist"}}}
```

HTTP কোড **503**। অর্থাৎ bridge/outbound যেকোনো একটা না থাকলেই লোড-ব্যালেন্সার
বা uptime বট সার্ভিসটাকে ডাউন ভাববে, যদিও ড্যাশবোর্ড, API, পে-রোল সব চলছে।

**গো-লাইভে করুন:** readiness-এর জন্য `/health` আর liveness-এর জন্য আলাদা
এন্ডপয়েন্ট (বা `/` ধরে চেক) — এবং মনিটরিংকে জানান 503-এর অর্থ degraded।

---

## ৬. বাকি ফলাফল (P1/P2)

| # | সমস্যা | প্রমাণ | করণীয় |
|---|---|---|---|
| 6.1 | **হার্ডকোডেড প্রোডাকশন পাথ** — `app`+`modules`+`shared`-এ ২৯ জায়গায় `/home/azim/...` (পুরো রিপোতে ১৫১)। bridge DB ডিফল্ট, `BACKUP_DIR` ডিফল্ট `/home/azim/backups` | `modules/backup/__init__.py:47` | নতুন হোস্টে `.env`-এ সব `BRIDGE*_DB_PATH`, `BACKUP_DIR` ওভাররাইড করুন |
| 6.2 | **পাথ-বিসঙ্গতি**: `install.sh` `cd /home/azim/fazle-core`, README ক্লোন `/home/azim/core`, systemd `WorkingDirectory=/home/azim/core` | `install.sh:5`, `fazle-core.service` | একটাই পাথ ঠিক করুন (`/home/azim/core`) |
| 6.3 | `086_k32_recruitment_reconciliation.sql` শর্ত দেয় “৬৬টি FAQ ID থাকতেই হবে” → ফ্রেশ DB-তে সব সময় ফেল | `RaiseError: K3.2 precondition failed: 66 expected FAQ IDs are missing` | KB সিড আগে চালান, বা ফাঁকা টেবিলে চেকটা এড়িয়ে যাওয়ার গার্ড যোগ করুন |
| 6.4 | `045_ai_read_billing_outstanding.sql` রোল `fazle_ai_reader` ধরে নেয়, কেউ বানায় না | `UndefinedObjectError: role "fazle_ai_reader" does not exist` | `CREATE ROLE fazle_ai_reader NOLOGIN;` আগে চালান (ডকের অংশ করুন) |
| 6.5 | **দুইটা মাইগ্রেশন ডিরেক্টরি** — `db/migrations/` (৯৬) আর `migrations/` (৫) | `db/migrate.py` শুধু প্রথমটা পড়ে; `tests/conftest.py` ১১১টা ফাইল খুঁজে পায় | legacy `migrations/`-কে `archive/`-এ সরান |
| 6.6 | **টেস্ট স্যুট আর গেট হিসেবে নির্ভরযোগ্য নয়** — DB ছাড়া ৩৭ failed + ২৩৯ error; DB সহ ~৮০ failed, চালাতে >২৫ মিনিট; কিছু টেস্ট প্রোডাকশন `.env`-এর মান ধরে (`admin_bridge2_number must be configured…`), কিছু টেস্টের `_FakeSettings` নতুন সেটিংসের অ্যাট্রিবিউট জানে না (`hermes_admin_grant_timeout_seconds`) | `/tmp/unit_db.log` | টেস্টগুলোকে ফ্যাক্টরি-সেটিংসে বাঁধুন; ধীর স্যুট প্যারালাল করুন (`-n auto`) |
| 6.7 | **লিন্ট ২৮৮ এরর** (`ruff`, `main`-এও একই) — সবই F401/E402/E702/E701 কসমেটিক; F821 (undefined name) শূন্য | `ruff check app/ modules/` | `pyflakes` গেট (undefined-name) আগে থেকেই পাস; `ruff --fix` দিয়ে ১১৬টা নিজে থেকে ঠিক হবে |
| 6.8 | **ডিপেন্ডেন্সি পিন되지 않음** — `openai>=1.40`, `qdrant-client>=1.9`, `sentence-transformers>=2.7` (ভারী, ~২ GB টর্চ) | `requirements.txt` | গো-লাইভের আগে `pip freeze` দিয়ে লকফাইল বানান |
| 6.9 | **Dockerfile** root হিসেবে চলে, `HEALTHCHECK` নেই, `.env` বান্ডল করে না | `Dockerfile` | non-root USER + HEALTHCHECK + `--env-file` |
| 6.10 | এই ব্র্যাঞ্চে `.env.example` নেই (main-এ merge হয়েছে `30dcc0d`) | `git status` | main থেকে merge/rebase করুন |

---

## ৭. এই পাসে যা ঠিক করলাম

`db/migrations/003_kb_schema_fix_and_recruitment.sql` — ০০৩-এর টেবিল-তৈরির
পরে দুটি guarded `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (`status`,
`candidate_id`) যোগ করা হলো, তারপর इंডেক্স। প্রোডাকশনে ০০৩ আগেই অ্যাপ্লাই হয়ে
গেছে বলে ওখানে এটা no-op; ফ্রেশ বিল্ডে আর থামবে না।

যাচাই (একই ফ্রেশ DB-তে, base schema সহ):

```
fix-এর আগে : applied 73/96, failed 23
fix-এর পরে: applied 74/96, failed 22   ← 003 এখন অ্যাপ্লাই হয়
```

বাকি P0 দুটো (স্কিমা বেসলাইন, CI) কোড-পরিবর্তনে মেটে না — মালিকের সিদ্ধান্ত
ও অ্যাকাউন্ট-অ্যাকশন দরকার।

---

## ৮. গো-লাইভ রানবুক

### ধাপ ০ — সিদ্ধান্ত

- **নতুন খালি সার্ভার?** → §১.খ-এর **পথ A** (প্রোডাকশন `pg_dump --schema-only`)
  ছাড়া কিছুই করবেন না। মাইগ্রেশন লুপে ঢুকবেন না।
- **পুরোনো প্রোডাকশন আপগ্রেড?** → সোজা §৮.খ।

### ৮.ক সার্ভার প্রস্তুতি (Ubuntu 22/24)

```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv postgresql-16 \
     postgresql-contrib-16 redis-server nginx curl git
sudo -u postgres psql -c "CREATE USER fazle PASSWORD '…long…';"
sudo -u postgres psql -c "CREATE DATABASE fazle_core OWNER fazle;"
sudo -u postgres psql -d fazle_core -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"   # §৩
sudo -u postgres psql -d fazle_core -c "CREATE ROLE fazle_ai_reader NOLOGIN;"      # §6.4

sudo useradd -m -s /bin/bash azim
sudo -u azim git clone https://github.com/arshiyaazim/fazle-core.git /home/azim/core
cd /home/azim/core
sudo -u azim python3.11 -m venv /home/azim/.venv
sudo -u azim /home/azim/.venv/bin/pip install -r requirements.txt
sudo -u azim mkdir -p logs
```

### ৮.খ স্কিমা

```bash
# পথ A (নতুন DB)
pg_restore --schema-only ...        # অথবা: psql -f db/schema_baseline.sql
sudo -u azim DATABASE_URL='postgresql://fazle:…@127.0.0.1:5432/fazle_core' \
     /home/azim/.venv/bin/python db/migrate.py --dry-run    # কী pending দেখুন
# পুরোনো DB: ব্যাকআপ নিয়ে তারপর
pg_dump -Fc "$DATABASE_URL" > /home/azim/backups/pre_deploy_$(date +%F).dump
sudo -u azim ... /home/azim/.venv/bin/python db/migrate.py
```

### ৮.গ কনফিগ (`/home/azim/core/.env`, mode 600)

```env
DATABASE_URL=postgresql://fazle:…@127.0.0.1:5432/fazle_core
INTERNAL_API_KEY=<secrets.token_urlsafe(32)>
BRIDGE1_DB_PATH=/home/azim/whatsapp1/store/messages.db      # §6.1
BRIDGE2_DB_PATH=/home/azim/whatsapp2/store/messages.db
BRIDGE3_DB_PATH=/home/azim/whatsapp3/store/messages.db
BRIDGE1_URL=http://127.0.0.1:8082
BRIDGE2_URL=http://127.0.0.1:8081
BRIDGE3_URL=http://127.0.0.1:8083
ADMIN_NUMBERS=8801XXXXXXXXX
OUTBOUND_ENABLED=false          # §৪ — systemd EnvironmentFile লাগবে
AUTO_REPLY_ENABLED=false
OLLAMA_URL=http://127.0.0.1:11434
```

systemd রিলোড (এর `EnvironmentFile=` থাকায় §৪-এর ফাঁদ এড়ানো যাবে):

```bash
sudo cp fazle-core.service /etc/systemd/system/   # পাথ ঠিক করে নিন (§6.2)
sudo systemctl daemon-reload && sudo systemctl enable --now fazle-core
sudo journalctl -u fazle-core -n 50 --no-pager
```

### ৮.ঘ স্মোক টেস্ট (এগুলো সত্যিই চালিয়েছি, স্যান্ডবক্সে)

```bash
curl -s  -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8200/            # 200
curl -s  -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8200/docs        # 200
curl -s  http://127.0.0.1:8200/health | python3 -m json.tool                # 200 চাই
K='X-Internal-Key: <key>'
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8200/rag/stats    # 403 (key ছাড়া)
curl -s -H "$K" http://127.0.0.1:8200/rag/stats | head -c 200               # 200 + stats
```

`/health`-এ প্রতিটি probe `ok` হতে হবে। ব্রিজ পোলে মেসেজ আসছে কি না:
`sudo journalctl -u fazle-core | grep -i "bridge"`।

### ৮.ঙ নিরাপত্তা

- `INTERNAL_API_KEY` খালি রাখবেন না (খালি থাকলে fail-closed, কিন্তু কেউ
  অ্যাডমিন করতে পারবে না)।
- সব সার্ভিস `127.0.0.1`-এ; পাবলিক শুধু Nginx TLS।
- `.env` → `chmod 600`, মালিক `azim`; `.gitignore`-এ আছে ✅।
- প্রথম দিনগুলো: `OUTBOUND_ENABLED=false`, `AUTO_REPLY_ENABLED=false`,
  `DRAFT_CREATION_ENABLED=true` — ড্রাফট জমবে, পাঠানো যাবে না, অ্যাডমিন
  `APPROVE` করলেই যাবে।
- `WEBHOOK_SIGNATURE_ENFORCEMENT=false` রাখুন যতক্ষণ সব bridge HMAC পাঠাচ্ছে
  না (audit mode)।

### ৮.ছ রোলব্যাক

```bash
sudo systemctl stop fazle-core
pg_restore -c -d fazle_core /home/azim/backups/pre_deploy_….dump
cd /home/azim/core && git checkout <previous-sha>
sudo systemctl start fazle-core
```

---

## ৯. পুনরুৎপাদন (আমি ঠিক যা চালিয়েছি)

```bash
# ফ্রেশ বিল্ড যাচাই
psql -c "CREATE DATABASE fazle_probe;"
DATABASE_URL=postgresql://…/fazle_probe .venv/bin/python db/migrate.py

# বুট + auth
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8200/health

# লিন্ট
.venv/bin/python -m ruff check app/ modules/ --statistics

# টেস্ট (PostgreSQL ১৬ :৫৪৩৩ সহ)
TEST_DATABASE_URL=postgresql://postgres:x@127.0.0.1:5433/fazle_test \
  .venv/bin/python -m pytest tests/unit/ -m unit --timeout=30 -q
```

---

## ১০. অগ্রাধিকার তালিকা

| অগ্রাধিকার | কাজ | কে |
|---|---|---|
| **P0** | GitHub billing ঠিক করা → CI আবার চালু | মালিক / অ্যাকাউন্ট |
| **P0** | `db/schema_baseline.sql` (প্রোডাকশন `pg_dump --schema-only`) কমিট + `migrate.py`-এ প্রয়োগ | ডেভেলপার |
| **P0** | `postgresql-contrib` + `CREATE EXTENSION pg_trgm` ডকুমেন্ট ও ইনস্টলে যোগ | ডেভেলপার |
| P1 | `.env` → `os.environ` (load_dotenv বা `Settings`-এ সরানো) | ডেভেলপার |
| P1 | `fazle_ai_reader` রোল, ০৮৬-এর precondition | ডেভেলপার |
| P1 | হার্ডকোডেড `/home/azim` পাথ অপসারণ / ওভাররাইড ডক | ডেভেলপার |
| P1 | `/health` (readiness) বনাম liveness আলাদা করা | ডেভেলপার |
| P2 | ruff `--fix`, ডুপ্লিকেট `migrations/` সরানো, ডিপেন্ডেন্সি লক, Dockerfile hardening | ডেভেলপার |
