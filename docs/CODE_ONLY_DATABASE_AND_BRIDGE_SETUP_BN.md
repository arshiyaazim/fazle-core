# ডাটাবেস ছাড়া রান, নতুন DB স্কিমা ও WhatsApp MCP Bridge প্রস্তুতি

এই ডকুমেন্টটি তিনটি আলাদা বিষয় পরিষ্কার করে:

1. PostgreSQL ছাড়াই repository/app shell চালানো;
2. পরে নতুন PostgreSQL database তৈরি ও schema apply করা;
3. বিদ্যমান WhatsApp MCP/whatsmeow bridge-এর SQLite database নিরাপদে যুক্ত করা।

## ১) Code-only mode (কোনো business DB নেই)

Fresh checkout-এ `.env` না থাকলেও এখন app import/start হবে। Explicit config:

```dotenv
DATABASE_MODE=disabled
DATABASE_URL=
OUTBOUND_ENABLED=false
AUTO_REPLY_ENABLED=false
```

Run:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
DATABASE_MODE=disabled .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8200
```

Check:

```bash
curl http://127.0.0.1:8200/health
curl http://127.0.0.1:8200/api/runtime/capabilities
```

`/health`-এ `status=limited` এবং `runtime_mode=code_only` আসবে। Static UI,
OpenAPI, module imports ও bridge preflight কাজ করবে। Business data read/write,
scheduler, bridge poller এবং outbound worker ইচ্ছাকৃতভাবে বন্ধ থাকবে। কোনো write
নীরবে success দেখাবে না; DB-dependent call `503 database_disabled` পাবে।

> এটি demo database নয় এবং production business mode-ও নয়। Persistence দরকার
> হলে PostgreSQL configure করতেই হবে।

`DATABASE_MODE=auto` default। `DATABASE_URL` থাকলে এটি `postgres`, না থাকলে
`disabled` resolve হয়। Production-এ ambiguity এড়াতে explicit
`DATABASE_MODE=postgres` ব্যবহার করুন।

## ২) নতুন PostgreSQL database ও schema

Schema source-of-truth:

- `db/schema/000_foundation.sql` — pre-migration production/test-certified base;
- `db/migrations/*.sql` — canonical Core migrations;
- `modules/fazle_payroll_engine/migrations/*.sql` — historical FPE migrations;
- `db/schema/900_runtime_support.sql` — আগে startup-এ তৈরি হওয়া support objects;
- `db/bootstrap.py` — নতুন empty DB-তে deterministic order, checksum ও validation।

প্রথমে plan দেখুন (DB লাগে না):

```bash
python db/bootstrap.py --plan
```

নতুন empty database তৈরি করে apply করুন:

```bash
createdb fazle_core
python db/bootstrap.py \
  --database-url postgresql://USER:PASSWORD@HOST:5432/fazle_core \
  --apply
```

Validate:

```bash
python db/bootstrap.py \
  --database-url postgresql://USER:PASSWORD@HOST:5432/fazle_core \
  --check
```

এরপর `.env`:

```dotenv
DATABASE_MODE=postgres
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/fazle_core
```

### নিরাপত্তা

- `bootstrap.py` শুধু **new/empty database**-এর জন্য। Existing DB-তে defaultভাবে
  refuse করবে।
- Existing deployment upgrade-এ `db/migrate.py` ও deployment runbook ব্যবহার
  করুন।
- Applied file checksum বদলালে bootstrap fail করবে; পুরোনো migration edit করে
  history rewrite করা যাবে না।
- `086_k32_recruitment_reconciliation.sql` schema নয়; এটি fixed legacy
  production row-ID যাচাই করা pending data-reconciliation। তাই new empty DB
  bootstrap plan থেকে ইচ্ছাকৃতভাবে বাদ।
- Database URL বা password Git-এ commit করবেন না।

### অন্য database engine

বর্তমান SQL PostgreSQL-specific (`JSONB`, arrays, partial indexes, PL/pgSQL)।
`app/database.py` এখন persistence boundary এবং `DATABASE_MODE` adapter seam দেয়,
কিন্তু MySQL/SQLite business backend এখনো implemented নয়। অন্য engine যোগ করতে:

1. `app/database.py` contract অনুযায়ী backend adapter লিখুন;
2. PostgreSQL SQL-কে engine-specific migrations-এ port করুন;
3. transaction, locking, JSON/array, partial unique index semantics-এর parity
   test করুন;
4. নতুন mode activate করার আগে DB integration suite চালান।

Bridge-এর SQLite store আর Core business database এক জিনিস নয়। Bridge SQLite
read-only input source; business state PostgreSQL-এ persist হয়।

## ৩) WhatsApp MCP/whatsmeow bridge database

Expected files সাধারণত:

```text
/path/to/bridge/store/messages.db
/path/to/bridge/store/whatsapp.db
```

Core bridge DB-তে migration বা write করে না। `mode=ro` এবং
`PRAGMA query_only=ON` দিয়ে preflight চলে। প্রথমে check:

```bash
python scripts/check_bridge_db.py \
  --name bridge1 \
  --messages /path/to/bridge/store/messages.db \
  --whatsapp /path/to/bridge/store/whatsapp.db
```

বা `.env`-এর তিন bridge একসাথে:

```bash
python scripts/check_bridge_db.py --configured
python scripts/check_bridge_db.py --configured --json
```

Success report-এ `compatible`, canonical-to-physical column mapping এবং
`schema_fingerprint` থাকবে। CI/deployment gate-এ JSON output ব্যবহার করা যায়।

Supported message table names:

- `messages` (stock);
- `message`;
- `whatsapp_messages`.

Canonical fields-এর জন্য stock names ছাড়াও conservative aliases support করা
হয়, যেমন `message_id`, `remote_jid`, `sender_jid`, `body`, `created_at`,
`from_me`, `message_type`, `media_url`। Core poller canonical aliases-এ project
করে, তাই downstream code একই row shape পায়।

Live inbound poller এই canonical aliases-এ project করে। Historical payroll
sync/outgoing escort scanners stock `messages` shape-ই ধরে; preflight-এ stock
shape হলে সব scanner-compatible। Alternate table-name profile ব্যবহার করলে ওই
optional scanner-গুলোর জন্য আলাদা adapter test/port করতে হবে।

`processed_text`/`ocr_text`, `from_history_sync`, filename/media URL optional।
কিন্তু `id`, chat JID, sender, content, timestamp ও from-me field required।
`whatsapp.db`-এর known LID/contact table না থাকলে warning হবে; direct
`@s.whatsapp.net` JID চলবে, unresolved LID mapping সীমিত হতে পারে।

`.env` example:

```dotenv
BRIDGE1_URL=http://127.0.0.1:8082
BRIDGE1_DB_PATH=/path/to/bridge1/store/messages.db
BRIDGE1_WHATSAPP_DB_PATH=/path/to/bridge1/store/whatsapp.db

BRIDGE2_URL=http://127.0.0.1:8081
BRIDGE2_DB_PATH=/path/to/bridge2/store/messages.db
BRIDGE2_WHATSAPP_DB_PATH=/path/to/bridge2/store/whatsapp.db
```

### Activation order

1. `DATABASE_MODE=disabled` অবস্থায় bridge DB preflight করুন;
2. নতুন PostgreSQL bootstrap + `--check` করুন;
3. `DATABASE_MODE=postgres`, কিন্তু `AUTO_REPLY_ENABLED=false` এবং
   `OUTBOUND_ENABLED=false` রেখে app চালান;
4. `/health/deep` ও poller heartbeat যাচাই করুন;
5. inbound archive/draft যাচাইয়ের পরেই owner approval অনুযায়ী outbound চালু
   করুন।

এই order bridge schema mismatch, history replay এবং accidental send—তিনটি risk
আলাদা করে নিয়ন্ত্রণ করে।
