# P0 Bootstrap Proof — PostgreSQL 16.2

**Date:** 2026-11-06 (Asia/Dhaka)  
**Branch:** `arena/af5c3ad4-fazle-core`  
**Scope:** strict fresh-database bootstrap, check, idempotent second apply, and
minimal full-mode application health.

## Disposable environment

- PostgreSQL **16.2**, local disposable cluster, trust-auth on loopback only.
- Server binaries came from the temporary `pgserver==0.1.4` Python wheel.
- That wheel omits `pg_trgm`; the PostgreSQL `REL_16_2` `contrib/pg_trgm`
  extension was compiled against its own PGXS headers and installed only into
  the disposable virtual environment.
- Database name: `fazle_bootstrap`; no production data, credentials, bridge
  sessions, or dumps were used or committed.
- Customer sends, auto-reply, drafts, and internal notifications were disabled
  during the application smoke test.

## Strict failure ledger

Every failure below stopped `db/bootstrap.py` with exit code 1. No statement
error was ignored/tolerated. The disposable database was dropped and recreated
before the next full attempt.

| Attempt | Exact failing step | Exact error | Resolution |
|---|---|---|---|
| 1 | `core/003c_schema_align.sql` | `column "employee_phone" does not exist` | Added explicit fresh-build precondition shim to temporarily restore the historical names that 003c renames. |
| 2 | `core/003c_schema_align.sql` | `constraint "fazle_attendance_employee_id_fkey" of relation "wbom_attendance" does not exist` | The same shim now reconciles foundation auto-named FKs with production-captured names and removes duplicate FK shapes. |
| 3 | `core/012_ai_readonly_views.sql` | `column c.interaction_count does not exist` | Aligned `fazle_contacts` foundation columns with the production-captured catalog. |
| 4 | `core/012_ai_readonly_views.sql` | `column "meta_json" does not exist` | Added the production `fazle_service_heartbeats.meta_json` column to the foundation. |
| 5 | `core/012_ai_readonly_views.sql` | `role "fazle_ai_reader" does not exist` | Added a bootstrap-only prerequisite that creates a safe `NOLOGIN` group role. |
| 6 | `core/018_atomic_release_and_outbound.sql` | `relation "fazle_outbound_queue" does not exist` | Identified migration 029 as a production-captured prerequisite catalog rather than a chronological migration. |
| 7 | `core/029_bootstrap_core_tables_schema_record.sql` | `column "salary_id" of relation "wbom_salary_records" does not exist` | Ordered catalog 029 **before** the test foundation so its exact production table shapes are not shadowed by older stubs. |
| 8 | `core/024_escort_history_fk.sql` | `relation "escort_order_lighters" does not exist` | Ordered recorded legacy `migrations/escort_history_schema.sql` immediately before migration 024. |
| 9 | — | none | Strict bootstrap completed successfully. |

Historical migration files were not edited. Fresh-build-only ordering and
compatibility are explicit, checksummed steps in `db/bootstrap.py` and
`db/schema/bootstrap_compat/`.

## Successful strict apply

Command:

```bash
DATABASE_URL=postgresql://postgres@127.0.0.1:55432/fazle_bootstrap \
  python db/bootstrap.py --apply
```

Result:

```text
BOOTSTRAP_EXIT=0
database=fazle_bootstrap tables=133 versions=115
schema check: OK
```

Additional integrity queries:

```text
planned_steps=115
migration_versions=115
unvalidated_constraints=0
duplicate_fk_shapes=0
ai_read_views=11
fazle_ai_reader login=false
payment draft canonical columns=employee_mobile,expected_amount
pg_trgm=1.6
```

## Explicit check and idempotency

```bash
python db/bootstrap.py --check
python db/bootstrap.py --apply
```

Results:

```text
CHECK_EXIT=0
schema check: OK
SECOND_APPLY_EXIT=0
SKIP_COUNT=115
APPLY_COUNT=0
```

`--check` now compares all 115 expected keys and on-disk checksums with the
version manifest, in addition to checking required tables. A disposable clone
was mutated to store a false checksum for catalog 029; both paths rejected it:

```text
MUTATED_CHECK_EXIT=1
schema checksum mismatch: core/029_bootstrap_core_tables_schema_record.sql
MUTATED_APPLY_EXIT=1
ERROR: applied schema step changed on disk: core/029_bootstrap_core_tables_schema_record.sql
```

A database with Fazle-managed version history may now resume/re-run normally.
An unrelated non-empty clone with one test table and no Fazle history was also
verified to fail (`UNMANAGED_APPLY_EXIT=1`). `--allow-nonempty` remains an
explicit operator-reviewed escape hatch.

## Full-mode application smoke

The application was started against the bootstrapped DB with three disposable,
empty stock-shape bridge SQLite stores and all outbound/reply flags off.

Results:

```text
Application startup complete
GET /health                  200 status=ok
GET /api/runtime/capabilities 200 runtime_mode=full
GET /health/deep             200 status=ok
```

Verified active capabilities included PostgreSQL reads/writes, bridge polling,
scheduler heartbeat, runtime gateway, FPE startup, and paused outbound queue.
Ollama and real bridge HTTP endpoints were intentionally absent; this did not
prevent Core/DB health and no outbound send was authorized.

## Conclusion

P0 bootstrap proof is complete for PostgreSQL 16.2. The next priority is the P1
real MCP bridge snapshot/preflight and canonical inbound/history guard proof.
