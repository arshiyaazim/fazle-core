-- ============================================================================
-- 015_fpe_gap_scan_skipped_no_content
-- ============================================================================
-- Declare `fpe_gap_scan_runs.skipped_no_content` — a column the runtime writes
-- but that no migration in this repository ever created.
--
-- Found by audits/NAMING_MISMATCH_AUDIT_2026-10-24.md section 1.7.
-- modules/fazle_payroll_engine/gap_scan.py INSERTs it on every gap-scan run:
--
--     INSERT INTO fpe_gap_scan_runs
--         (source, chat_jid, sqlite_count, archive_count,
--          missing_count, backfilled, skipped_no_content,
--          duration_ms, error, finished_at)
--
-- but the CREATE TABLE in 004_fpe_zero_loss.sql declares only
-- id, source, chat_jid, sqlite_count, archive_count, missing_count,
-- backfilled, duration_ms, error, started_at, finished_at.
--
-- WHY ADD THE COLUMN RATHER THAN REMOVE THE CODE
--   * The value is not cosmetic. gap_scan.py counts messages that are absent
--     from the archive purely because they carry no content, and reports
--     `real_gaps = missing - skipped` so operators are not paged about gaps
--     that are not real. Dropping the column would discard that signal.
--   * This INSERT is the only place a completed scan is recorded. Because it
--     names a column that does not exist, the statement fails outright — so
--     the failure is not "one field is missing" but "no run is ever logged".
--   * The alternative fix (deleting the column from the INSERT) would change
--     behaviour; adding the column preserves it. It is also the same choice
--     made for fazle_knowledge_base in section 1.4.
--
-- WHAT THIS DOES
--   Adds the column to an EXISTING database. Purely additive: one
--   `ADD COLUMN IF NOT EXISTS` with a DEFAULT of 0, so no row is rewritten
--   and nothing is dropped.
--
--   On production this is expected to be a no-op if the column is already
--   there. Its purpose is to (a) make the schema reproducible from this
--   repository and (b) converge any environment that genuinely lacks it.
--
--   A FROM-SCRATCH build does not need this file: migration 004 now declares
--   the column in its CREATE TABLE. This file is the "existing database"
--   half of that fix.
--
-- IDEMPOTENCY
--   Every statement is guarded. This matters more than usual here — the FPE
--   runner replays every file in modules/fazle_payroll_engine/migrations/ at
--   each startup (see start_fpe()), so this file runs repeatedly.
--
-- ROLLBACK
--   See the "ROLLBACK" section at the bottom of this file. Dropping the
--   column is only safe once gap_scan.py no longer INSERTs it; today it does,
--   so rollback would break every gap scan.
-- ============================================================================


-- ── 1. Ensure the table exists (no-op on every environment that has it) ────
-- Guarded so this file cannot fail with 42P01 "undefined table" if it is ever
-- replayed against a database where 004 has not run.

CREATE TABLE IF NOT EXISTS fpe_gap_scan_runs (
    id                  BIGSERIAL    PRIMARY KEY,
    source              TEXT         NOT NULL,      -- 'bridge1' | 'bridge2'
    chat_jid            TEXT         NOT NULL,
    sqlite_count        BIGINT       NOT NULL DEFAULT 0,
    archive_count       BIGINT       NOT NULL DEFAULT 0,
    missing_count       BIGINT       NOT NULL DEFAULT 0,
    backfilled          BIGINT       NOT NULL DEFAULT 0,
    skipped_no_content  BIGINT       NOT NULL DEFAULT 0,
    duration_ms         INT          NOT NULL DEFAULT 0,
    error               TEXT,
    started_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ
);


-- ── 2. Add the missing column to pre-existing tables ────────────────────────

ALTER TABLE fpe_gap_scan_runs
    ADD COLUMN IF NOT EXISTS skipped_no_content BIGINT NOT NULL DEFAULT 0;


-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- >>> ROLLBACK-SQL-BEGIN
--
--   ALTER TABLE fpe_gap_scan_runs
--       DROP COLUMN IF EXISTS skipped_no_content;
--
-- <<< ROLLBACK-SQL-END
--
-- ROLLBACK COMPLETE for fpe_gap_scan_skipped_no_content
-- ============================================================================
