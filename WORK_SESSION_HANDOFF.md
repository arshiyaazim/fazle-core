# Fazle Core — Work Session Handoff

> **প্রতিটি coding session-এর বাধ্যতামূলক নিয়ম**
>
> 1. কাজ শুরুর আগে এই ফাইল এবং `README.md`-এর “Session continuation” অংশ পড়তে হবে।
> 2. এখানে থাকা বর্তমান অবস্থা, ঝুঁকি ও next-session queue যাচাই করে তারপর code change করতে হবে।
> 3. কাজ শেষে এই ফাইলের **Current state**, **Validation**, **Known gaps** এবং
>    **Next session** আপডেট করতে হবে।
> 4. পরিবর্তন commit করে শুধু session-এর নির্ধারিত branch-এ push করতে হবে।
> 5. secret, production `.env`, database dump বা WhatsApp session data commit করা যাবে না।

**Last updated:** 2026-11-06 (Asia/Dhaka)

**Working branch:** `arena/af5c3ad4-fazle-core`

**Primary objective:** Fazle Core-কে business database provision করার আগেও
নিরাপদ code-only mode-এ runnable করা, নতুন database bootstrap contract তৈরি
করা, এবং WhatsApp MCP/whatsmeow bridge SQLite store integration preflight ও
schema tolerance যোগ করা।

---

## 1. Current state

### A. Database-optional code mode

- `DATABASE_MODE=auto|postgres|disabled` যোগ হয়েছে।
- `DATABASE_URL` আর config-validation-এর সময় বাধ্যতামূলক নয়।
- `auto` mode-এ URL থাকলে PostgreSQL, না থাকলে `disabled` resolve হয়।
- Disabled mode-এ app startup সফল হয়, কিন্তু DB workers, pollers, scheduler,
  outbound worker ও business persistence ইচ্ছাকৃতভাবে চালু হয় না।
- DB write নীরবে success দেখায় না; `DatabaseUnavailable`/HTTP 503 contract আছে।
- `/health` code-only mode-এ HTTP 200 সহ `status=limited` দেয়।
- `/api/runtime/capabilities` full বনাম code-only capability প্রকাশ করে।
- `scripts/smoke_code_only.py` সম্পূর্ণ ASGI lifespan smoke-check করে।

### B. New database schema/bootstrap

- Test fixture-এ আগে embedded থাকা production/test-certified foundation এখন
  `db/schema/000_foundation.sql`-এ executable source হিসেবে আছে।
- Runtime-created support objects এখন `db/schema/900_runtime_support.sql`-এ আছে।
- `tests/conftest.py` ওই দুই schema file read করে—test ও provisioning schema
  একই source ব্যবহার করে।
- `db/bootstrap.py` নতুন empty PostgreSQL DB-এর জন্য:
  - deterministic plan;
  - foundation + Core/FPE migrations + runtime support;
  - per-file checksum/version tracking;
  - non-empty DB safety refusal;
  - required-table validation দেয়।
- `086_k32_recruitment_reconciliation.sql` schema নয় এবং fixed legacy data-ID
  precondition চায়; তাই new-empty-DB plan থেকে ইচ্ছাকৃতভাবে বাদ।
- Existing DB upgrade path অপরিবর্তিত: deployment runbook + `db/migrate.py`।

### C. WhatsApp MCP/whatsmeow bridge database

- `shared/bridge_store.py` read-only SQLite compatibility/preflight layer যোগ হয়েছে।
- Stock `messages` schema এবং conservative MCP aliases detect করা হয়।
- Live inbound poller metadata-resolved identifier ও canonical projection ব্যবহার
  করে; `processed_text`/history/media optional column gracefully handle করে।
- `scripts/check_bridge_db.py` single store বা configured Bridge1/2/3 check করে;
  human-readable ও JSON report, mapping এবং schema fingerprint দেয়।
- Bridge DB কখনো migrate/write করা হয় না; preflight `mode=ro` +
  `PRAGMA query_only=ON` ব্যবহার করে।

### D. Documentation/automation

- বিস্তারিত বাংলা guide:
  `docs/CODE_ONLY_DATABASE_AND_BRIDGE_SETUP_BN.md`।
- `.env.example`, `README.md`, `docs/SETUP_BN.md`, `Makefile` এবং CI update হয়েছে।
- Make targets: `code-only-smoke`, `schema-plan`, `bridge-check`।
- CI-তে code-only app smoke যোগ হয়েছে; E2E server env-এ explicit full DB mode
  configure করা হয়েছে।

---

## 2. Validation completed

এই session-এ চালানো হয়েছে:

```text
python -m compileall -q app modules shared scripts db tests/...
python db/bootstrap.py --plan
python scripts/check_bridge_db.py --messages <temporary-stock-store>
pytest tests/unit/test_code_only_and_bridge_store.py \
       tests/unit/test_database_bootstrap_plan.py
DATABASE_MODE=disabled DATABASE_URL= python scripts/smoke_code_only.py
```

ফলাফল:

- Syntax/compile: pass
- Bootstrap plan generation: pass (112 ordered steps + runtime support at the
  time of this update; exact count plan থেকে নিন)
- Temporary bridge SQLite preflight: pass
- New targeted unit tests: **5 passed**
- Code-only full lifespan smoke: pass
- Existing bridge-focused selected tests: **55 passed**; DB-required selected
  tests local PostgreSQL না থাকায় setup error হয়েছে, code regression failure নয়।

---

## 3. Known gaps / cautions

1. **Fresh PostgreSQL bootstrap এখনো real disposable PostgreSQL instance-এ
   end-to-end apply করা হয়নি।** `--plan` ও static/unit validation pass করেছে,
   কিন্তু পরের session-এ PostgreSQL 15/16 container-এ strict apply + re-check
   বাধ্যতামূলক। কোনো migration failure হলে historical migration edit না করে
   bootstrap-specific safe reconciliation layer করতে হবে।
2. Alternate bridge table/column aliases live inbound polling-এ supported।
   Historical payroll sync এবং outgoing escort scanners এখনো stock `messages`
   shape ধরে; preflight alternate profile-এ warning দেয়।
3. Code-only mode business feature simulate করে না। Dashboard shell load হবে,
   কিন্তু persistent APIs unavailable থাকবে—এটি deliberate safety behavior।
4. Full integration/DB/E2E suite এই environment-এ PostgreSQL না থাকায় চালানো হয়নি।
5. Safe flags (`AUTO_REPLY_ENABLED=false`, `OUTBOUND_ENABLED=false`) owner
   approval ছাড়া পরিবর্তন করা যাবে না।

---

## 4. Next session queue (priority order)

### P0 — Bootstrap proof

1. Disposable PostgreSQL 15 বা 16 চালু করুন।
2. `python db/bootstrap.py --apply` strictভাবে চালান।
3. Failure থাকলে exact migration/key record করুন; silent/tolerated error ব্যবহার
   করবেন না।
4. `python db/bootstrap.py --check` এবং second-run checksum/idempotency verify করুন।
5. Minimal full-mode app startup + `/health` verify করুন।

### P1 — Bridge integration proof

1. বাস্তব MCP bridge-এর copy/snapshot (secret/session data commit নয়) দিয়ে
   `scripts/check_bridge_db.py --json` চালান।
2. Stock schema fingerprint ও LID-map availability record করুন।
3. One synthetic inbound row দিয়ে `_fetch_new_messages()` canonical row shape
   test করুন; history-sync row route না হওয়ার guard verify করুন।
4. দরকার হলে historical/outgoing scanners-কে একই bridge-store adapter-এ port করুন।

### P1 — Test/CI hardening

1. New bootstrap integration test disposable PostgreSQL service-এ যোগ করুন।
2. Full relevant unit tests, DB integration tests এবং E2E run করুন।
3. Existing duplicate/contradictory CI workflow paths/working-directory audit করুন।

### P2 — Persistence adapter expansion

শুধু owner যদি PostgreSQL ছাড়া অন্য business DB engine চান:

1. `app/database.py` boundary-এর formal backend protocol লিখুন;
2. engine-specific migrations তৈরি করুন;
3. JSONB, arrays, advisory locks, partial unique indexes ও transaction parity
   test ছাড়া নতুন backend advertise/activate করবেন না।

---

## 5. Session start checklist

```bash
cat WORK_SESSION_HANDOFF.md
sed -n '1,120p' README.md
git status --short --branch
git log -5 --oneline --decorate
python db/bootstrap.py --plan | tail
```

তারপর current environment capability অনুযায়ী P0 থেকে কাজ শুরু করুন।

## 6. Session end checklist

- [ ] Code/tests/docs শেষ অবস্থার সাথে এই handoff মিলিয়ে update করা হয়েছে
- [ ] Validation commands ও ফলাফল লেখা হয়েছে
- [ ] Known gaps সত্যভাবে লেখা হয়েছে
- [ ] কোনো secret/DB dump/session store staged নয়
- [ ] `git diff --check` pass
- [ ] Current fixed session branch-এই commit/push করা হয়েছে
