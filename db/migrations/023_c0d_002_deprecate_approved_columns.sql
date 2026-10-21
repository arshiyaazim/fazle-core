-- Migration C0D-002: Mark approved_by / approved_at as DEPRECATED (no physical DROP)
-- Sprint-C0D: Migration Repair
-- Purpose: Declare approved_by and approved_at on fazle_cash_transactions_archive as deprecated.
-- Owner Decision: "এখনই Physical DROP নয়; প্রথমে Deprecated ঘোষণা।"
-- These columns have 0 rows, no active writer, not part of Business Constitution.
-- Physical DROP will be done in a future sprint after verification period.
--
-- This migration is IDEMPOTENT — COMMENT is safe to run multiple times.
--
-- Rollback:
--   COMMENT ON COLUMN fazle_cash_transactions_archive.approved_by IS NULL;
--   COMMENT ON COLUMN fazle_cash_transactions_archive.approved_at IS NULL;

COMMENT ON COLUMN fazle_cash_transactions_archive.approved_by IS
    'DEPRECATED — 0 rows, no active writer. Not part of Business Constitution. Scheduled for removal in future sprint.';

COMMENT ON COLUMN fazle_cash_transactions_archive.approved_at IS
    'DEPRECATED — 0 rows, no active writer. Not part of Business Constitution. Scheduled for removal in future sprint.';