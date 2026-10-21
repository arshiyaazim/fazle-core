-- ============================================================
-- Fazle Payroll Engine — Initial Schema
-- File: modules/fazle_payroll_engine/migrations/001_fpe_schema.sql
-- All tables use fpe_* prefix — never conflicts with wbom_* or fazle_* tables
-- Run once manually or via install.sh (no Alembic — raw SQL pattern)
-- ============================================================

-- ── 1. Raw WhatsApp messages (immutable store) ───────────────────────────────
CREATE TABLE IF NOT EXISTS fpe_wa_messages (
    id              BIGSERIAL    PRIMARY KEY,
    wa_message_id   TEXT         NOT NULL,
    source          TEXT         NOT NULL,       -- 'bridge1' | 'bridge2' | 'meta'
    source_number   TEXT         NOT NULL,       -- bridge owner phone e.g. 8801958122300
    chat_jid        TEXT         NOT NULL,       -- counterpart JID
    sender_phone    TEXT,                        -- resolved phone (01XXXXXXXXX)
    is_from_me      BOOLEAN      NOT NULL DEFAULT FALSE,
    raw_content     TEXT,
    media_type      TEXT,
    timestamp_wa    TIMESTAMPTZ  NOT NULL,
    ingested_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT fpe_wa_messages_unique UNIQUE (wa_message_id, source)
);

CREATE INDEX IF NOT EXISTS idx_fazle_wam_chat   ON fpe_wa_messages(chat_jid, timestamp_wa DESC);
CREATE INDEX IF NOT EXISTS idx_fazle_wam_source ON fpe_wa_messages(source, timestamp_wa DESC);

-- ── 2. Per-message processing FSM ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fpe_message_processing_state (
    id                BIGSERIAL    PRIMARY KEY,
    fpe_wa_message_id BIGINT       NOT NULL REFERENCES fpe_wa_messages(id),
    status            TEXT         NOT NULL DEFAULT 'pending',
    -- pending | parsing | parsed | accounting | done | failed | skipped
    attempts          INT          NOT NULL DEFAULT 0,
    last_error        TEXT,
    queued_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    processed_at      TIMESTAMPTZ,
    CONSTRAINT fpe_mps_unique UNIQUE (fpe_wa_message_id)
);

CREATE INDEX IF NOT EXISTS idx_fazle_mps_status ON fpe_message_processing_state(status, queued_at);

-- ── 3. Parser results (what was extracted from each message) ──────────────────
CREATE TABLE IF NOT EXISTS fpe_parser_results (
    id                BIGSERIAL    PRIMARY KEY,
    fpe_wa_message_id BIGINT       NOT NULL REFERENCES fpe_wa_messages(id),
    message_type      TEXT         NOT NULL,   -- 'payment' | 'balance_summary' | 'other'
    parsed_data       JSONB        NOT NULL DEFAULT '{}',
    confidence        FLOAT        NOT NULL DEFAULT 1.0,
    parser_version    TEXT         NOT NULL DEFAULT 'v1',
    ai_enhanced       BOOLEAN      NOT NULL DEFAULT FALSE,
    ai_notes          TEXT,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── 4. Employees ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fazle_employees (
    id                BIGSERIAL    PRIMARY KEY,
    employee_code     TEXT         UNIQUE,             -- EMP-00001 (auto-assigned)
    full_name         TEXT         NOT NULL,
    name_normalized   TEXT         NOT NULL,           -- lower + stripped
    primary_phone     TEXT,                            -- 01XXXXXXXXX canonical
    employee_id_phone TEXT,                            -- from "ID: 01XXXXXXXXX" field
    department        TEXT,
    status            TEXT         NOT NULL DEFAULT 'active',
    created_source    TEXT         NOT NULL DEFAULT 'whatsapp_auto_create',
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fazle_emp_primary_phone ON fazle_employees(primary_phone);
CREATE INDEX IF NOT EXISTS idx_fazle_emp_id_phone      ON fazle_employees(employee_id_phone);
CREATE INDEX IF NOT EXISTS idx_fazle_emp_name_norm     ON fazle_employees(name_normalized);

-- ── 5. Employee aliases (multi-phone / multi-name per employee) ───────────────
CREATE TABLE IF NOT EXISTS fpe_employee_aliases (
    id           BIGSERIAL   PRIMARY KEY,
    employee_id  BIGINT      NOT NULL REFERENCES fazle_employees(id) ON DELETE CASCADE,
    alias_type   TEXT        NOT NULL,   -- 'phone' | 'name' | 'employee_id'
    alias_value  TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fpe_aliases_unique UNIQUE (alias_type, alias_value)
);

CREATE INDEX IF NOT EXISTS idx_fazle_aliases_lookup ON fpe_employee_aliases(alias_type, alias_value);

-- ── 6. Cash transactions (immutable accounting events) ───────────────────────
CREATE TABLE IF NOT EXISTS fazle_cash_transactions (
    id                  BIGSERIAL     PRIMARY KEY,
    txn_ref             TEXT          UNIQUE NOT NULL,   -- fpe-TXN-<sha256_8>
    fpe_wa_message_id   BIGINT        REFERENCES fpe_wa_messages(id),
    employee_id         BIGINT        REFERENCES fazle_employees(id),
    employee_name_raw   TEXT,                            -- as parsed
    amount              NUMERIC(12,2) NOT NULL,
    payout_phone        TEXT,                            -- 01XXXXXXXXX
    payout_method       TEXT,                            -- 'bkash'|'nagad'|'cash'|'rocket'|'bank'
    txn_date            DATE          NOT NULL,
    txn_category        TEXT          NOT NULL DEFAULT 'salary',
    -- salary | advance | bonus | deduction | correction
    source_message_text TEXT,
    is_reversal         BOOLEAN       NOT NULL DEFAULT FALSE,
    reversed_txn_id     BIGINT        REFERENCES fazle_cash_transactions(id),
    accounting_period   TEXT,                            -- YYYY-MM
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    created_by          TEXT          NOT NULL DEFAULT 'fpe_engine'
);

CREATE INDEX IF NOT EXISTS idx_fazle_txn_employee ON fazle_cash_transactions(employee_id, txn_date);
CREATE INDEX IF NOT EXISTS idx_fazle_txn_period   ON fazle_cash_transactions(accounting_period);
CREATE INDEX IF NOT EXISTS idx_fazle_txn_phone    ON fazle_cash_transactions(payout_phone);

-- ── 7. Employee ledger (running totals per employee per month) ────────────────
CREATE TABLE IF NOT EXISTS fazle_employee_ledger (
    id                BIGSERIAL     PRIMARY KEY,
    employee_id       BIGINT        NOT NULL REFERENCES fazle_employees(id),
    accounting_period TEXT          NOT NULL,   -- YYYY-MM
    opening_balance   NUMERIC(12,2) NOT NULL DEFAULT 0,
    total_earned      NUMERIC(12,2) NOT NULL DEFAULT 0,
    total_paid        NUMERIC(12,2) NOT NULL DEFAULT 0,
    total_advance     NUMERIC(12,2) NOT NULL DEFAULT 0,
    closing_balance   NUMERIC(12,2) NOT NULL DEFAULT 0,
    txn_count         INT           NOT NULL DEFAULT 0,
    last_updated      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT fazle_ledger_unique UNIQUE (employee_id, accounting_period)
);

-- ── 8. Unmatched messages (parse failure or no employee match) ────────────────
CREATE TABLE IF NOT EXISTS fpe_unmatched_messages (
    id                BIGSERIAL   PRIMARY KEY,
    fpe_wa_message_id BIGINT      NOT NULL REFERENCES fpe_wa_messages(id),
    reason            TEXT        NOT NULL,   -- 'no_parse_match' | 'no_employee_match'
    raw_content       TEXT,
    reviewed          BOOLEAN     NOT NULL DEFAULT FALSE,
    reviewed_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── 9. Accounting audit log (immutable) ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS fpe_accounting_audit_logs (
    id            BIGSERIAL   PRIMARY KEY,
    entity_type   TEXT        NOT NULL,   -- 'transaction' | 'employee' | 'ledger'
    entity_id     BIGINT      NOT NULL,
    action        TEXT        NOT NULL,   -- 'create' | 'update' | 'reverse'
    before_state  JSONB,
    after_state   JSONB,
    performed_by  TEXT        NOT NULL DEFAULT 'fpe_engine',
    reason        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fazle_audit_entity ON fpe_accounting_audit_logs(entity_type, entity_id);

-- ── 10. Sync checkpoints (resume-safe per bridge source) ─────────────────────
CREATE TABLE IF NOT EXISTS fpe_sync_checkpoints (
    id              BIGSERIAL   PRIMARY KEY,
    source          TEXT        NOT NULL,       -- 'bridge1' | 'bridge2' | 'meta'
    source_number   TEXT        NOT NULL,       -- e.g. 8801958122300
    chat_jid        TEXT        NOT NULL,       -- which conversation is being tracked
    last_message_id TEXT,                       -- wa_message_id of last processed row
    last_timestamp  TIMESTAMPTZ,
    total_ingested  BIGINT      NOT NULL DEFAULT 0,
    last_sync_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fpe_checkpoint_unique UNIQUE (source, source_number, chat_jid)
);
