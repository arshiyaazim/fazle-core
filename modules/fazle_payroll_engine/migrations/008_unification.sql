-- ============================================================================
-- Migration 008: Safe Unification Layer
-- ============================================================================
-- PHILOSOPHY: Additive only. No columns dropped, no renames, no data loss.
-- All statements use IF NOT EXISTS / safe UPDATE guards.
-- Runs automatically via start_fpe() on next service restart.
-- ============================================================================

-- ── 1. Soft-link fazle_employees → fazle_employees_legacy ──────────────────────────────
-- A nullable FK-like column. NULL = not yet linked. Safe for joins.
ALTER TABLE fazle_employees
    ADD COLUMN IF NOT EXISTS wbom_employee_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_fazle_emp_fazle_link
    ON fazle_employees(wbom_employee_id)
    WHERE wbom_employee_id IS NOT NULL;

-- ── 2. Soft-link fazle_payment_drafts → escort_roster_entries ────────────────
-- Lets a payment draft optionally reference the roster entry that spawned it.
ALTER TABLE fazle_payment_drafts
    ADD COLUMN IF NOT EXISTS escort_roster_entry_id INTEGER;

-- ── 3. Processing lock table (idempotent distributed lock) ───────────────────
-- Used by shared.locks — prevents double-processing in concurrent workers.
CREATE TABLE IF NOT EXISTS fazle_processing_locks (
    lock_key   TEXT        PRIMARY KEY,
    locked_by  TEXT        NOT NULL,
    locked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '60 seconds'
);

CREATE INDEX IF NOT EXISTS idx_locks_expires
    ON fazle_processing_locks(expires_at);

-- ── 4. Phone-based backfill of wbom_employee_id ──────────────────────────────
-- Only fills NULLs. Matches on last-10 digits of primary_phone.
-- Safe: if no fazle_employees_legacy row exists, nothing happens.
UPDATE fazle_employees fe
SET    wbom_employee_id = we.employee_id
FROM   fazle_employees_legacy we
WHERE  fe.wbom_employee_id IS NULL
  AND  RIGHT(REGEXP_REPLACE(COALESCE(fe.primary_phone, ''), '\D', '', 'g'), 10)
       = RIGHT(REGEXP_REPLACE(we.employee_mobile, '\D', '', 'g'), 10)
  AND  RIGHT(REGEXP_REPLACE(COALESCE(fe.primary_phone, ''), '\D', '', 'g'), 10)
       <> '';
