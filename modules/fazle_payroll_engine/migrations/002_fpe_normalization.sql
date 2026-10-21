-- ─────────────────────────────────────────────────────────────────────────────
-- Fazle Payroll Engine — Safe identity normalization layer
-- File: modules/fazle_payroll_engine/migrations/002_fpe_normalization.sql
--
-- Adds the "Alias-Based Identity Resolution Model" tables.
-- This migration is purely ADDITIVE. It does NOT touch:
--   - fazle_cash_transactions   (immutable accounting)
--   - fazle_employee_ledger     (append-safe totals)
--   - fpe_accounting_audit_logs
-- It only adds soft-link, review-queue, and normalization-audit tables.
-- All statements are idempotent (IF NOT EXISTS / DO NOTHING).
-- ─────────────────────────────────────────────────────────────────────────────

-- ── A. Extend fazle_employees with soft-link columns ────────────────────────────
-- Never mutate transactions; instead mark a duplicate employee row as resolved
-- to a canonical employee. Both rows remain forever.
ALTER TABLE fazle_employees
    ADD COLUMN IF NOT EXISTS canonical_employee_id BIGINT
        REFERENCES fazle_employees(id);

ALTER TABLE fazle_employees
    ADD COLUMN IF NOT EXISTS resolution_status TEXT
        NOT NULL DEFAULT 'unresolved';
        -- 'unresolved' | 'canonical' | 'duplicate' | 'inactive'

ALTER TABLE fazle_employees
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(4,3)
        NOT NULL DEFAULT 0.000;

CREATE INDEX IF NOT EXISTS idx_fazle_emp_canonical
    ON fazle_employees(canonical_employee_id);
CREATE INDEX IF NOT EXISTS idx_fazle_emp_resolution_status
    ON fazle_employees(resolution_status);


-- ── B. Resolution links (audit trail of every duplicate→canonical decision) ──
CREATE TABLE IF NOT EXISTS fpe_employee_resolution_links (
    id                     BIGSERIAL    PRIMARY KEY,
    employee_id            BIGINT       NOT NULL REFERENCES fazle_employees(id),
    canonical_employee_id  BIGINT       NOT NULL REFERENCES fazle_employees(id),
    resolution_type        TEXT         NOT NULL,
        -- 'manual_merge' | 'manual_alias' | 'phone_match' | 'admin_decision'
    confidence_score       NUMERIC(4,3) NOT NULL DEFAULT 1.000,
    reason                 TEXT,
    created_by             TEXT         NOT NULL DEFAULT 'fpe_engine',
    reviewed_by            TEXT,
    reviewed_at            TIMESTAMPTZ,
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT fpe_resolution_no_self CHECK (employee_id <> canonical_employee_id),
    CONSTRAINT fpe_resolution_unique UNIQUE (employee_id, canonical_employee_id)
);

CREATE INDEX IF NOT EXISTS idx_fazle_reslinks_employee
    ON fpe_employee_resolution_links(employee_id);
CREATE INDEX IF NOT EXISTS idx_fazle_reslinks_canonical
    ON fpe_employee_resolution_links(canonical_employee_id);


-- ── C. Manual review queue (ambiguous matches) ───────────────────────────────
CREATE TABLE IF NOT EXISTS fpe_employee_review_queue (
    id                    BIGSERIAL    PRIMARY KEY,
    candidate_employee_id BIGINT       REFERENCES fazle_employees(id),
    suspected_match_id    BIGINT       REFERENCES fazle_employees(id),
    match_reason          TEXT         NOT NULL,
        -- 'fuzzy_name_below_threshold' | 'name_collision' |
        -- 'phone_conflict' | 'duplicate_suspected' | 'manual_flag'
    confidence_score      NUMERIC(4,3) NOT NULL DEFAULT 0.000,
    source_message_id     BIGINT       REFERENCES fpe_wa_messages(id),
    raw_name              TEXT,
    raw_phone             TEXT,
    review_status         TEXT         NOT NULL DEFAULT 'pending',
        -- 'pending' | 'approved_merge' | 'rejected' | 'kept_separate'
    reviewer              TEXT,
    review_note           TEXT,
    reviewed_at           TIMESTAMPTZ,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT fpe_review_no_self CHECK (
        candidate_employee_id IS NULL
        OR suspected_match_id IS NULL
        OR candidate_employee_id <> suspected_match_id
    )
);

CREATE INDEX IF NOT EXISTS idx_fazle_review_status
    ON fpe_employee_review_queue(review_status);
CREATE INDEX IF NOT EXISTS idx_fazle_review_candidate
    ON fpe_employee_review_queue(candidate_employee_id);


-- ── D. Normalization audit log (every safe action — never mutates txns) ──────
CREATE TABLE IF NOT EXISTS fpe_normalization_audit_logs (
    id            BIGSERIAL    PRIMARY KEY,
    action_type   TEXT         NOT NULL,
        -- 'add_alias' | 'link_duplicate' | 'enqueue_review' |
        -- 'resolve_review' | 'mark_inactive' | 'phone_normalize' |
        -- 'name_normalize'
    entity_type   TEXT         NOT NULL DEFAULT 'employee',
    entity_id     BIGINT,
    before_state  JSONB,
    after_state   JSONB,
    reviewer      TEXT,
    reason        TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fazle_norm_audit_entity
    ON fpe_normalization_audit_logs(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_fazle_norm_audit_action
    ON fpe_normalization_audit_logs(action_type);
