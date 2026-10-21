
-- 005_review_audit_logs.sql
-- Immutable audit log for admin review-queue actions.
-- INSERT-only. No row in this table is ever updated or deleted by application code.

CREATE TABLE IF NOT EXISTS fpe_review_audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    review_item_id  BIGINT,                 -- references fpe_unmatched_messages.id (nullable for DLQ/non-review actions)
    action          TEXT NOT NULL,          -- promote | dismiss | duplicate | requeue | gap_scan_trigger | reject | non_payment | ...
    actor           TEXT NOT NULL,          -- reviewer name / role identifier
    old_state       JSONB,                  -- snapshot before action
    new_state       JSONB,                  -- snapshot after action
    reason          TEXT,                   -- free-text reason / note
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fazle_review_audit_item    ON fpe_review_audit_logs (review_item_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fazle_review_audit_action  ON fpe_review_audit_logs (action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fazle_review_audit_actor   ON fpe_review_audit_logs (actor, created_at DESC);

-- This is an INSERT-only ledger. Application code must NEVER UPDATE/DELETE rows.
-- Corrections are recorded by appending a new audit row referencing the same review_item_id.
