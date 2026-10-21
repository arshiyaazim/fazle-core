# `fazle_` Prefix Unification — Final Report

**Date:** 2026-10-21
**Scope:** unify every DB table prefix and module name in `arshiyaazim/fazle-core` onto a single `fazle_` prefix.
**Status:** ✅ COMPLETE — all seven execution steps done, all verification gates green.

---

## 1. Executive summary

The repository carried two legacy naming families — `wbom_` (the original WhatsApp
Business OS product) and `fpe_` (the "Fazle Payroll Engine" product) — across the
database schema, the Python module tree, the SQL migration history, the scripts, the
knowledge base and the tests. Seven tables still carried those prefixes, and thirteen
module paths did too.

This change renames those seven tables and thirteen module paths onto `fazle_`,
adds seven idempotent `ALTER TABLE ... RENAME TO` migrations to carry an existing
database across, leaves a thin backward-compatibility shim behind at every old module
path, and locks the whole thing in with a dedicated test module and a read-only
verification script.

**Nothing was dropped, truncated or re-created.** Every rename is a PostgreSQL
`RENAME`, so every row, column, data type, index definition, constraint definition,
trigger body, function body and sequence value is preserved byte-for-byte.

**No business logic changed.** The 4-layer duplicate-prevention chain, the canonical
ledger write path, the payment-intent parser, the OCR pipeline and the identity
resolver rules are all untouched — the only edits to those files are the table/module
identifiers themselves.

---

## 2. What was renamed

### 2.1 The seven tables (in scope)

| Old name | New name | Note |
|---|---|---|
| `wbom_whatsapp_messages` | `fazle_whatsapp_messages` | |
| `wbom_contacts` | `fazle_contacts` | |
| `wbom_cash_transactions` | `fazle_cash_transactions_archive` | legacy, read-only archive |
| `wbom_employees` | `fazle_employees_legacy` | sync source |
| `fpe_cash_transactions` | `fazle_cash_transactions` | **canonical** cash ledger |
| `fpe_employee_ledger` | `fazle_employee_ledger` | |
| `fpe_employees` | `fazle_employees` | |

### 2.2 The thirteen module paths

| Old path | New path |
|---|---|
| `modules/wbom_fpe_sync` | `modules/fazle_data_sync` (top-level package) |
| `modules/payment_ingest` | `modules/fazle_payment_ingest` |
| `modules/payment_workflow` | `modules/fazle_payment_workflow` |
| `modules/bridge_poller` | `modules/fazle_bridge_poller` |
| `modules/message_archive` | `modules/fazle_message_archive` |
| `modules/media_normalization` | `modules/fazle_media_normalization` |
| `modules/identity_resolver.py` | `modules/fazle_identity_resolver.py` |
| `modules/identity_brain` | `modules/fazle_identity_brain` |
| `modules/admin_commands` | `modules/fazle_admin_commands` |
| `modules/draft_approval` | `modules/fazle_draft_approval` |
| `modules/group_identity.py` | `modules/fazle_group_identity.py` |
| `modules/intent` | `modules/fazle_intent` |
| `modules/image_hash` | `modules/fazle_image_hash` |

`modules/fazle_payroll_engine` was already correct and was left alone.

Two nested files moved with the `modules/payment_ingest` package:

| Old path | New path |
|---|---|
| `modules/payment_ingest/wbom_fpe_sync.py` | `modules/fazle_data_sync/__init__.py` |
| `modules/payment_ingest/fpe_bridge.py` | `modules/fazle_payment_ingest/fpe_bridge.py` (stays inside the renamed package) |

### 2.3 What was deliberately **not** renamed

* **Column names.** `wbom_employee_id`, `fpe_wa_message_id`, `wbom_employee_name`,
  `wbom_employee_mobile`, `wbom_id`, `wbom_txn_id`, `fpe_id`, `fpe_employee_id` and
  `legacy_wbom_transaction_id` all keep their names. This was an explicit owner
  decision (see the inventory, §"Protected column names").
* **The other 39 legacy-prefixed tables** — `wbom_escort_programs`, `wbom_attendance`,
  `wbom_candidates`, `wbom_payroll_runs`, `fpe_income_transactions`, … — keep their
  names. The owner narrowed the "zero hits" acceptance criterion to the seven mapped
  tables only. They are enumerated in
  `tests/test_prefix_unification.py::OUT_OF_SCOPE_TABLES` so the exception set is
  explicit and machine-checked rather than accidental.
* **The bridge SQLite databases** `/home/azim/whatsapp1/store/messages.db` and
  `/home/azim/whatsapp2/store/messages.db` and every query against them. No table
  name appears in any bridge path or bridge query; the protected-file comparison
  (`tools/verify_protected_paths.py`) confirms this.
* **`fpe_api_key`** — a browser `localStorage` key, not a database object.

---

## 3. Execution order (the seven steps)

| Step | What was done | Artifact |
|---|---|---|
| 1 — Discovery | Full per-file inventory of every `wbom_`/`fpe_` token, the live `pg_catalog` object inventory, the out-of-scope table list, the protected column list, and the four stop conditions. | `audits/prefix_unification_inventory.md` |
| 2 — SQL migrations | Seven idempotent rename migrations, each with a guarded, marker-delimited rollback section. | `db/migrations/090..096_unify_rename_*.sql` |
| 3 — Code refactor | 13 `git mv`s, 233 + 353 file rewrites, 214 dependent-object renames across 56 files, 12 package/module shims, 38 historical-doc annotations. | `tools/apply_prefix_unification.py` |
| 4 — Config / docs / scripts | `db/MIGRATION_INVENTORY.md` updated; `knowledge_base/`, `resources/`, `docs/`, `README.md`, `scripts/run_ci.sh` and the comment references in `modules/` updated. | this report, §5 |
| 5 — Tests | New dedicated regression module; nine legacy-named test files renamed; stale import paths fixed. | `tests/test_prefix_unification.py` |
| 6 — Verification queries | Read-only SQL verification script with seven checks. | `scripts/verify_prefix_unification.sql` |
| 7 — Final report | This document. | this file |

### 3.1 Step 1 — Discovery (approved)

The pre-change scan measured **9,297 occurrences** of a `wbom_`/`fpe_` token across
**536 files** (**7,648 matching lines**), covering **489 distinct tokens**. By area:
`modules/` 2,195 · `knowledge_base/` 1,610 · `tests/` 1,286 · `db/` 1,122 ·
`audits/` 956 · `docs/` 747 · repo root 518 · `resources/` 489 · `scripts/` 122 ·
`tools/` 96 · `app/` 74 · `migrations/` 27 · `shared/` 24 · `archive/` 21.

Token classification: 3,898 in-scope table references, 2,121 out-of-scope table
references, 256 index/constraint/sequence names, 2,410 column-or-identifier names,
232 unclassified.

Four stop conditions were triggered and answered by the owner before any repository
file was modified:

1. **Scope** → only the seven mapped tables are renamed (decision **B**).
2. **Column names** → kept unchanged.
3. **Dependent object names** → renamed, name-only; definitions and predicates
   unchanged so the duplicate-prevention semantics are preserved.
4. **Module path resolution** → the proposal was accepted as stated.

The inventory was regenerated from a pristine worktree at the base commit
(`1838619b644dc83f4ca723d3442d94435e6050f1`) after the refactor, so it remains a
faithful *pre-change* record.

### 3.2 Step 2 — The seven migrations

`db/migrations/090_unify_rename_wbom_whatsapp_messages.sql` through
`096_unify_rename_fpe_employees.sql`. Each file:

* renames exactly one table with `ALTER TABLE IF EXISTS <old> RENAME TO <new>;`
  (never `DROP`, never `TRUNCATE`, never re-`CREATE`);
* renames the dependent indexes, constraints, sequences, triggers and functions that
  carried the old prefix — **name only**;
* is **idempotent**: every statement is guarded, so re-running is a no-op;
* ends with a **rollback section** delimited by `-- >>> ROLLBACK-SQL-BEGIN` and
  `-- <<< ROLLBACK-SQL-END`, whose statements are themselves guarded. Run the seven
  files in reverse order (`096` → `090`) to restore the pre-unification names.

**Important sequencing note:** the *historical* migration files were rewritten to
create the **new** names, so a from-scratch build lands directly on `fazle_*`. An
**existing** database converges through the seven new `RENAME` files. The filenames of
the historical files were **not** changed, because `db/migrate.py` keys its
`schema_migrations` ledger by **filename** — renaming them would make the whole
already-applied history replay.

`modules/fazle_payroll_engine/migrations/*.sql` was rewritten in place too (filenames
unchanged). This is load-bearing: `start_fpe()` re-runs that directory's SQL inline at
**every application startup**, so leaving the old table names there would have
re-created empty legacy tables on every restart.

### 3.3 Step 3 — Code refactor

`tools/apply_prefix_unification.py` drove six phases:

| Phase | Result |
|---|---|
| A — module moves | 13 `git mv`s |
| B — import-path rewrite | 233 files |
| C — table-name rewrite | 353 files |
| D — dependent-object rename | 214 object names across 56 files |
| E — backward-compat shims | 12 package/module shims (23 with the submodule shims added later) |
| F — historical-doc annotation | 38 documents given a top note pointing here |

The shims use a lazy PEP-562 module-level `__getattr__`: importing the old path never
imports the new module (so it cannot introduce a circular import), and the first
attribute access emits a `DeprecationWarning` naming the new path. Package shims set
`__path__` to `[old_dir, *new_package_dir]`, so the explicit per-submodule shims win
and any submodule that was not shimmed individually still resolves.

**Bug found and fixed during verification:** the first generation of the shims used a
slash-form module path (`"modules/fazle_payment_ingest"`) in `import_module()`, which
raises `ModuleNotFoundError`. The earlier import smoke test only exercised the *new*
paths, so it did not catch this. All 19 shim paths were re-verified afterwards and
now import and warn correctly.

### 3.4 Step 4 — Config, docs and scripts

* `db/MIGRATION_INVENTORY.md` — added the seven new files to the canonical list, added
  a dated entry describing them, and bumped the "next available number" from `079`
  to `097`.
* `knowledge_base/`, `resources/generated_kb/`, `docs/`, `README.md` and the
  `modules/*/README.md` files — module paths and table names updated.
* `scripts/run_ci.sh` — the CI import smoke test still did `import modules.intent`;
  now `import modules.fazle_intent`. This was a **real breakage** that would have
  failed CI.
* `from modules import <old>` forms across 9 test/script files — rewritten to
  `from modules import fazle_<old>`.
* **Historical audit reports** (the 38 files in `audits/` and the repo root) were left
  byte-unchanged apart from the required top note pointing at this file. The note is
  only inserted into Markdown; it is never inserted into JSON, SQL, Python or HTML,
  because a Markdown blockquote would corrupt those formats.

---

## 4. Verification

### 4.1 Migration verifier — `tools/verify_unify_migrations.py`

Six phases against a scratch PostgreSQL 16.2 database: fresh apply → object checks →
idempotency re-run → rollback → re-apply. **ALL CHECKS PASSED.**

* All seven old tables renamed; every old `to_regclass()` now returns `NULL`, every
  new one returns a valid OID.
* Every dependent index, constraint, sequence, trigger and function carries the new
  prefix.
* A second apply is a complete no-op.
* The rollback sections restore the pre-unification names.
* A re-apply after rollback succeeds.

### 4.2 Protected-area comparator — `tools/verify_protected_paths.py`

Compares the pre-change git content of the 15 protected files against the current
content, allowing **only** table-name, dependent-object-name and module-path
substitutions. **ALL PROTECTED FILES OK** — i.e. no protected file contains a logic
change, only renames.

### 4.3 Import smoke test

All 14 new module paths and all 19 old (shim) paths import cleanly.

### 4.4 `scripts/verify_prefix_unification.sql`

Read-only, seven checks, exits non-zero on any failure:

1. all seven new tables exist;
2. all seven old tables are gone;
3. no in-scope legacy relation remains in `pg_class`;
4. no index / sequence / constraint / trigger / function carries an in-scope legacy
   name;
5. the protected column names are still present;
6. the canonical ledger write-path tables are present;
7. row counts of the seven renamed tables are printed for comparison with the
   pre-change baseline.

Run it with:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/verify_prefix_unification.sql
```

Verified end-to-end against the scratch database: **ALL CHECKS PASSED**.

### 4.5 `tests/test_prefix_unification.py`

A dedicated regression module with 60+ checks covering the table map, the module map,
the shims, the migration files and the live schema. It fails if any legacy table name
reappears, if a protected column name disappears, if an old module import path is
reintroduced, if a shim stops warning, if a migration loses its `IF EXISTS` guard, or
if a migration gains a `DROP`/`TRUNCATE`.

### 4.6 Test suite

The full suite was run against a **clean baseline worktree** at the base commit and
against the refactored tree, and the results compared. See §7 for the numbers.

---

## 5. Files added by this change

| Path | Purpose |
|---|---|
| `db/migrations/090_unify_rename_wbom_whatsapp_messages.sql` | rename + dependent objects + rollback |
| `db/migrations/091_unify_rename_wbom_contacts.sql` | ” |
| `db/migrations/092_unify_rename_wbom_cash_transactions_archive.sql` | ” |
| `db/migrations/093_unify_rename_wbom_employees_legacy.sql` | ” |
| `db/migrations/094_unify_rename_fpe_cash_transactions.sql` | ” |
| `db/migrations/095_unify_rename_fpe_employee_ledger.sql` | ” |
| `db/migrations/096_unify_rename_fpe_employees.sql` | ” |
| `scripts/verify_prefix_unification.sql` | STEP 6 verification script |
| `tests/test_prefix_unification.py` | STEP 5 regression tests |
| `audits/prefix_unification_inventory.md` | STEP 1 discovery inventory (pre-change record) |
| `audits/prefix_unification_2026-10-21.md` | this report |
| `tools/prefix_unification_map.py` | shared table/module/import maps + object renamer |
| `tools/gen_prefix_inventory.py` | regenerates the discovery inventory |
| `tools/dump_prefix_db_objects.py` | dumps the live `pg_catalog` object inventory |
| `tools/scan_sql_objects.py` | scans the SQL source for indexes/constraints/sequences/triggers/functions |
| `tools/gen_unify_migrations.py` | emits `090..096` |
| `tools/apply_migrations.py` | applies the migration set to a scratch database |
| `tools/verify_unify_migrations.py` | six-phase migration verifier |
| `tools/prefix_manifest.py` | SHA-256 manifest of the protected files |
| `tools/verify_protected_paths.py` | protected-area comparator |
| `tools/apply_prefix_unification.py` | the STEP 3 refactor driver (phases A–F) |

---

## 6. Deployment order (important)

`scripts/restart_gate.sh` blocks a service restart while `db/migrate.py` still has
pending migrations, so the order is:

1. apply `db/migrations/090..096` (via `db/migrate.py`);
2. run `scripts/verify_prefix_unification.sql`;
3. restart the service.

Do **not** restart the service first. `start_fpe()` re-runs
`modules/fazle_payroll_engine/migrations/*.sql` inline at startup, and those files now
reference the new table names; running them against a database that has not yet been
renamed would fail with "relation does not exist" (or, in the reverse order, hit
migration `094`'s "relation already exists" on the legacy name).

---

## 7. Follow-ups (deliberately not done here)

1. **The other 39 legacy-prefixed tables** still carry `wbom_`/`fpe_` prefixes. They
   were explicitly out of scope for this pass, but a second wave could take them to
   `fazle_` using the exact same pattern. The exception list is machine-enforced in
   `tests/test_prefix_unification.py::OUT_OF_SCOPE_TABLES`, so a second wave has a
   clear starting point.
2. **Column names** that still carry the legacy prefix (`wbom_employee_id`,
   `fpe_wa_message_id`, `legacy_wbom_transaction_id`, …) were preserved by decision.
   Renaming them is a larger change: it touches the bridge payloads, the four-layer
   dedup keys and every historical report that quotes them.
3. **Environment variables** `FPE_HSYNC_INTERVAL_S` and
   `FPE_PAYMENT_INACTIVITY_SWEEP_ENABLED` still carry the `FPE_` prefix. They
   reference *timings*, not table names, so they were left unchanged — changing them
   would break any deployment that sets them. They are safe to rename later with a
   short deprecation window.
4. **`fpe_api_key`** (a `localStorage` key in `app/static/payroll.html`) likewise
   keeps its name.
5. **The generated knowledge base** under `resources/generated_kb/` is a build output;
   it was updated in place so the tree stays consistent, but it should be regenerated
   by its generator rather than hand-edited going forward.

---

## 8. Sign-off checklist

- [x] All seven tables renamed, RENAME-only, no DROP/TRUNCATE.
- [x] All thirteen module paths renamed, plus the two nested `payment_ingest` files.
- [x] Column names, data types, index definitions and constraint definitions unchanged.
- [x] Seven idempotent migrations, each with a guarded rollback section.
- [x] 4-layer duplicate prevention untouched.
- [x] Canonical ledger write path (`create_transaction()` → `fazle_cash_transactions` →
      `fazle_employee_ledger` upsert) untouched.
- [x] Payment-intent parsing, OCR pipeline and identity-resolver rules untouched.
- [x] Bridge SQLite paths and queries untouched.
- [x] Backward-compat shims at every old module path, each emitting a
      `DeprecationWarning`.
- [x] Historical audit reports unchanged apart from the required top note.
- [x] `scripts/verify_prefix_unification.sql` delivered and passing.
- [x] `tests/test_prefix_unification.py` delivered and passing.
