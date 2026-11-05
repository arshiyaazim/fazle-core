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

**Primary objective:** P0 fresh PostgreSQL bootstrap proof এখন সম্পূর্ণ। পরবর্তী
objective হলো বাস্তব MCP/whatsmeow bridge store snapshot দিয়ে read-only preflight,
canonical inbound mapping এবং history-sync guard-এর P1 integration proof।

---

## 1. Current state

### A. Database-optional code mode

- `DATABASE_MODE=auto|postgres|disabled` আছে; `DATABASE_URL` initial runtime-এ
  বাধ্যতামূলক নয়।
- `auto` mode-এ URL থাকলে PostgreSQL, না থাকলে `disabled` resolve হয়।
- Disabled mode-এ HTTP/static/OpenAPI/preflight চলে; DB workers, pollers,
  scheduler, outbound এবং business persistence ইচ্ছাকৃতভাবে বন্ধ থাকে।
- DB write নীরবে success দেখায় না; `DatabaseUnavailable`/HTTP 503 contract আছে।
- `/health` code-only mode-এ HTTP 200 সহ `status=limited` দেয় এবং
  `/api/runtime/capabilities` active capability প্রকাশ করে।
- `scripts/smoke_code_only.py` সম্পূর্ণ ASGI lifespan smoke-check করে।

### B. New database schema/bootstrap — P0 proven

- `db/bootstrap.py` fresh PostgreSQL DB-এর জন্য deterministic, checksummed,
  strict plan চালায়। Current plan: **115 tracked steps**।
- Production-captured migration 029 catalog হিসেবে generic foundation-এর আগে
  চলে; ফলে older foundation stub exact production table shape shadow করে না।
- `db/schema/bootstrap_compat/003c_schema_align_pre.sql` historical 003c-এর
  expected old names/FK names explicitly ও duplicate-FK ছাড়া প্রস্তুত করে।
- `db/schema/bootstrap_compat/012_ai_readonly_views_pre.sql` safe `NOLOGIN`
  `fazle_ai_reader` role তৈরি করে।
- Recorded legacy `migrations/escort_history_schema.sql` migration 024-এর ঠিক
  আগে checksummed prerequisite হিসেবে চলে।
- `db/schema/000_foundation.sql` production contact metadata এবং
  `fazle_service_heartbeats.meta_json` shape-এর সাথে aligned।
- Non-empty, unmanaged database defaultভাবে refused হয়। Fazle version history
  থাকা managed DB resume/second apply করতে পারে; checksum mismatch fail করে।
- `086_k32_recruitment_reconciliation.sql` schema নয় এবং fixed legacy data-ID
  precondition চায়; তাই new-empty-DB plan থেকে ইচ্ছাকৃতভাবে বাদ।
- Existing production DB upgrade path অপরিবর্তিত: deployment runbook +
  `db/migrate.py`।
- Full strict ledger ও proof:
  `docs/BOOTSTRAP_PROOF_2026-11-06.md`।

### C. WhatsApp MCP/whatsmeow bridge database

- `shared/bridge_store.py` read-only SQLite compatibility/preflight layer আছে।
- Stock `messages` schema এবং conservative MCP aliases detect করা হয়।
- Live inbound poller metadata-resolved identifier ও canonical projection ব্যবহার
  করে; optional `processed_text`/history/media columns tolerate করে।
- `scripts/check_bridge_db.py` single store বা configured Bridge1/2/3 check করে;
  human-readable/JSON report, mapping এবং schema fingerprint দেয়।
- Bridge DB কখনো migrate/write করা হয় না; preflight `mode=ro` +
  `PRAGMA query_only=ON` ব্যবহার করে।
- P0 full-mode smoke-তে তিনটি disposable empty stock-shape bridge store দিয়ে
  Bridge1/2/3 poller heartbeats healthy প্রমাণিত হয়েছে। বাস্তব MCP store proof
  এখনো P1।

### D. Documentation/automation

- বাংলা setup guide: `docs/CODE_ONLY_DATABASE_AND_BRIDGE_SETUP_BN.md`।
- P0 evidence: `docs/BOOTSTRAP_PROOF_2026-11-06.md`।
- `.env.example`, `README.md`, `docs/SETUP_BN.md`, `Makefile` এবং CI code-only
  path update হয়েছে।
- Make targets: `code-only-smoke`, `schema-plan`, `bridge-check`।
- README প্রতিটি future session-কে এই handoff আগে পড়তে এবং শেষে update/push
  করতে নির্দেশ দেয়।

---

## 2. Validation completed

### PostgreSQL 16.2 strict proof

Disposable PostgreSQL **16.2**-এ clean database drop/recreate করে প্রতিটি failure
strictভাবে stop ও record করা হয়েছে। কোনো SQL error tolerate বা applied হিসেবে
mark করা হয়নি। Exact failure sequence:

```text
core/003c_schema_align.sql -> column "employee_phone" does not exist
core/003c_schema_align.sql -> constraint "fazle_attendance_employee_id_fkey" ... does not exist
core/012_ai_readonly_views.sql -> column c.interaction_count does not exist
core/012_ai_readonly_views.sql -> column "meta_json" does not exist
core/012_ai_readonly_views.sql -> role "fazle_ai_reader" does not exist
core/018_atomic_release_and_outbound.sql -> relation "fazle_outbound_queue" does not exist
core/029_bootstrap_core_tables_schema_record.sql -> column "salary_id" ... does not exist
core/024_escort_history_fk.sql -> relation "escort_order_lighters" does not exist
```

তারপর clean ninth apply:

```text
python db/bootstrap.py --apply
BOOTSTRAP_EXIT=0
database=fazle_bootstrap tables=133 versions=115
schema check: OK
```

Check ও second apply:

```text
python db/bootstrap.py --check        -> exit 0, schema check: OK
python db/bootstrap.py --apply        -> exit 0
SKIP_COUNT=115
APPLY_COUNT=0
```

`--check` required tables-এর সাথে 115-key manifest/checksum-ও compare করে। আলাদা
clone-এ catalog 029 checksum mutate করে `--check` এবং `--apply` উভয়ের exit 1
verify হয়েছে। এক-table unmanaged clone-ও version history না থাকায় default apply
exit 1/refused হয়েছে।

Integrity verification:

```text
PostgreSQL 16.2; pg_trgm 1.6
planned_steps=115; migration_versions=115
unvalidated_constraints=0
duplicate_fk_shapes=0
ai_read_views=11
fazle_ai_reader login=false
```

### Full-mode startup

Bootstrapped DB + disposable stock-shape Bridge1/2/3 stores, outbound/reply flags
বন্ধ রেখে:

```text
Application startup complete
GET /health                    -> 200, status=ok
GET /api/runtime/capabilities -> 200, runtime_mode=full,
                                 database.connected=true
GET /health/deep              -> 200, status=ok
Application shutdown complete
```

Real bridge HTTP endpoints এবং Ollama intentionally absent ছিল; Core DB,
poller, scheduler, FPE, runtime gateway এবং paused outbound health pass করেছে।
কোনো outbound send authorize হয়নি।

### Code/static/unit validation

```text
python -m compileall -q app modules shared scripts db tests/...
git diff --check
pytest tests/unit/test_database_bootstrap_plan.py \
       tests/unit/test_code_only_and_bridge_store.py
```

Result: compile/diff pass; targeted tests **5 passed**। Test process-এর old
default PostgreSQL `127.0.0.1:5433` setup warning targeted pure unit result-কে
প্রভাবিত করেনি। Prior session-এর code-only lifespan এবং 55 bridge-focused tests
pass ছিল।

---

## 3. Known gaps / cautions

1. বাস্তব connected MCP bridge-এর store snapshot এখনো পাওয়া/পরীক্ষা করা হয়নি।
   Disposable stock shape pass করেছে, কিন্তু exact production fingerprint,
   LID-map এবং history-sync behavior P1-তে verify করতে হবে।
2. Historical payroll sync ও outgoing escort scanners এখনো stock `messages`
   shape ধরে; preflight alternate profile-এ warning দেয়। দরকার হলে এগুলোকে
   shared bridge-store adapter-এ port করতে হবে।
3. `tests/conftest.py` legacy test schema loader foundation-এর পরে migrations
   চালায় এবং per-statement migration errors tolerate করে। P0 production bootstrap
   strict, কিন্তু test fixture-কে একই strict bootstrap plan-এ আনা P1 CI debt।
4. Full integration/DB/E2E suite এই P0 proof-এ চালানো হয়নি; শুধু targeted unit,
   real bootstrap এবং full-mode smoke হয়েছে। আলাদা `fazle_test` DB-তে suite
   চালাতে হবে—proof database কখনো test fixture-কে দেবেন না, কারণ fixture
   `DROP SCHEMA public CASCADE` করে।
5. Code-only mode business feature simulate করে না; persistent APIs unavailable
   থাকা deliberate safety behavior।
6. Safe flags (`AUTO_REPLY_ENABLED=false`, `OUTBOUND_ENABLED=false`) owner
   approval ছাড়া পরিবর্তন করা যাবে না।

---

## 4. Next session queue (priority order)

### P1 — Real bridge integration proof

1. বাস্তব MCP bridge-এর copy/snapshot নিন; secret/session data commit করবেন না।
2. `python scripts/check_bridge_db.py --messages ... --whatsapp ... --json`
   চালিয়ে schema fingerprint, canonical mapping ও LID-map availability record করুন।
3. Snapshot copy-তে (live store নয়) one synthetic inbound row দিয়ে
   `_fetch_new_messages()` canonical row shape test করুন।
4. `from_history_sync=1` row route না হওয়ার guard এবং `is_from_me=1` loop guard
   verify করুন।
5. Alternate profile পাওয়া গেলে historical/outgoing scanners-কে shared adapter-এ
   port করুন এবং regression tests দিন।

### P1 — Test/CI hardening

1. `tests/conftest.py` tolerant legacy migration runner-এর বদলে strict shared
   bootstrap plan/fixture ব্যবহার করুন; expected schema seed আলাদা রাখুন।
2. Disposable PostgreSQL 15/16 service-এ clean apply + check + second apply CI
   integration test যোগ করুন।
3. Separate `fazle_test` DB-তে unit/integration/db/workflow/resilience suites,
   তারপর isolated E2E run করুন।
4. Duplicate/contradictory CI workflow paths এবং `working-directory` audit করুন।

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
sed -n '1,140p' README.md
git status --short --branch
git log -5 --oneline --decorate
python db/bootstrap.py --plan | tail
```

তারপর P1 real bridge integration proof থেকে কাজ শুরু করুন।

## 6. Session end checklist

- [ ] Code/tests/docs শেষ অবস্থার সাথে এই handoff মিলিয়ে update করা হয়েছে
- [ ] Validation commands ও ফলাফল লেখা হয়েছে
- [ ] Known gaps সত্যভাবে লেখা হয়েছে
- [ ] কোনো secret/DB dump/session store staged নয়
- [ ] `git diff --check` pass
- [ ] Current fixed session branch-এই commit/push করা হয়েছে
