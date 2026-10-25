-- ============================================================
-- Fazle Payroll Engine — Zero-loss hardening (additive only)
-- File: modules/fazle_payroll_engine/migrations/004_fpe_zero_loss.sql
--
-- Purpose:
--   * Upgrade fpe_unmatched_messages into a first-class review queue
--     ("Pending Accounting Candidates") so detected money never disappears.
--   * Add indexes that support DLQ scan, gap scan, and reconciliation.
--   * Add fpe_gap_scan_runs to record bridge-vs-archive ID gap fills.
--
-- INVARIANTS PRESERVED:
--   - fazle_cash_transactions is NEVER altered. The ledger remains strict and
--     contains only verified accounting entries.
--   - fazle_employee_ledger is untouched.
--   - fpe_accounting_audit_logs is untouched.
--   - All statements are idempotent (IF NOT EXISTS / safe ALTER).
-- ============================================================

-- ── A. Enrich fpe_unmatched_messages ─────────────────────────────────────────
-- These columns let the operator see WHAT the parser detected, even when the
-- transaction was not promoted to the ledger.

ALTER TABLE fpe_unmatched_messages
    ADD COLUMN IF NOT EXISTS detected_amount         NUMERIC(12,2);

ALTER TABLE fpe_unmatched_messages
    ADD COLUMN IF NOT EXISTS detected_payout_phone   TEXT;

ALTER TABLE fpe_unmatched_messages
    ADD COLUMN IF NOT EXISTS detected_employee_name  TEXT;

ALTER TABLE fpe_unmatched_messages
    ADD COLUMN IF NOT EXISTS detected_payout_method  TEXT;

ALTER TABLE fpe_unmatched_messages
    ADD COLUMN IF NOT EXISTS detected_txn_date       DATE;

ALTER TABLE fpe_unmatched_messages
    ADD COLUMN IF NOT EXISTS parser_confidence       NUMERIC(4,3);

ALTER TABLE fpe_unmatched_messages
    ADD COLUMN IF NOT EXISTS retry_count             INT NOT NULL DEFAULT 0;

ALTER TABLE fpe_unmatched_messages
    ADD COLUMN IF NOT EXISTS review_status           TEXT NOT NULL DEFAULT 'pending';
    -- 'pending' | 'promoted' | 'dismissed' | 'duplicate'

ALTER TABLE fpe_unmatched_messages
    ADD COLUMN IF NOT EXISTS resolved_employee_id    BIGINT
        REFERENCES fazle_employees(id);

ALTER TABLE fpe_unmatched_messages
    ADD COLUMN IF NOT EXISTS promoted_txn_id         BIGINT
        REFERENCES fazle_cash_transactions(id);

ALTER TABLE fpe_unmatched_messages
    ADD COLUMN IF NOT EXISTS reviewer                TEXT;

ALTER TABLE fpe_unmatched_messages
    ADD COLUMN IF NOT EXISTS review_note             TEXT;

CREATE INDEX IF NOT EXISTS idx_fazle_unmatched_review_status
    ON fpe_unmatched_messages(review_status);

CREATE INDEX IF NOT EXISTS idx_fazle_unmatched_pending_amount
    ON fpe_unmatched_messages(review_status, detected_amount)
    WHERE review_status = 'pending';


-- ── B. DLQ scan support on processing FSM ────────────────────────────────────
-- The DLQ view exposes messages that the worker has given up on
-- (status='failed' AND attempts >= MAX_ATTEMPTS).

CREATE INDEX IF NOT EXISTS idx_fazle_mps_status_attempts
    ON fpe_message_processing_state(status, attempts);


-- ── C. Gap-scan run log (one row per bridge sweep) ───────────────────────────
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

CREATE INDEX IF NOT EXISTS idx_fazle_gapscan_source_started
    ON fpe_gap_scan_runs(source, started_at DESC);
