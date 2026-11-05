-- Fazle Core runtime support schema for a new PostgreSQL database.
-- These objects were historically created by application startup. Keeping an
-- executable record here makes database provisioning independent of startup.

-- Post-migration fixup: add columns that migrations fail to add due to
-- file corruption in migration 010 or BEGIN/COMMIT transaction rollback issues.
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'whatsapp';
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS source_channel TEXT;
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS source_message_id TEXT;
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS employee_id_phone TEXT;
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS employee_phone TEXT;
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS program_id BIGINT;
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS original_payload JSONB;
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS transaction_status TEXT NOT NULL DEFAULT 'final';
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS approval_status TEXT;
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS approved_by TEXT;
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS review_status TEXT;
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS submitted_by TEXT;
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ;
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS deleted_by TEXT;
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE fazle_cash_transactions ADD COLUMN IF NOT EXISTS legacy_wbom_transaction_id BIGINT;

-- Bridge poller dedup tables (created at runtime by bridge_poller.init_tables)
CREATE TABLE IF NOT EXISTS bridge_poller_cursor (
    bridge      TEXT PRIMARY KEY,
    last_ts     TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS processed_bridge_messages (
    message_id  TEXT    NOT NULL,
    bridge      TEXT    NOT NULL,
    phone       TEXT,
    processed_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (message_id, bridge)
);
CREATE INDEX IF NOT EXISTS idx_pbm_bridge_ts
    ON processed_bridge_messages (bridge, processed_at DESC);
CREATE TABLE IF NOT EXISTS processed_outgoing_escort_messages (
    message_id   TEXT    NOT NULL,
    bridge       TEXT    NOT NULL,
    processed_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (message_id, bridge)
);
CREATE TABLE IF NOT EXISTS outbound_safety_incidents (
    id              BIGSERIAL   PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    recipient       TEXT        NOT NULL,
    bridge          TEXT        NOT NULL,
    blocked_reason  TEXT        NOT NULL,
    message_preview TEXT,
    queue_id        TEXT,
    source_module   TEXT        NOT NULL DEFAULT 'bridge_poller'
);
CREATE INDEX IF NOT EXISTS idx_osi_ts
    ON outbound_safety_incidents (ts DESC);
CREATE INDEX IF NOT EXISTS idx_osi_recipient
    ON outbound_safety_incidents (recipient, ts DESC);

-- Outbound queue (used by modules.outbound.enqueue)
CREATE TABLE IF NOT EXISTS fazle_outbound_queue (
    id              BIGSERIAL   PRIMARY KEY,
    recipient       TEXT        NOT NULL,
    body            TEXT        NOT NULL,
    source_bridge   TEXT        NOT NULL DEFAULT 'bridge2',
    fallback_channel TEXT,
    purpose         TEXT,
    idempotency_key TEXT UNIQUE,
    meta_json       JSONB       DEFAULT '{}'::jsonb,
    status          TEXT        NOT NULL DEFAULT 'pending',
    attempts        INT         NOT NULL DEFAULT 0,
    max_attempts    INT         NOT NULL DEFAULT 5,
    next_retry_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_at       TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ,
    external_id     TEXT,
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- LLM conversation log (fire-and-forget inserts from ollama.py)
CREATE TABLE IF NOT EXISTS llm_conversation_log (
    id          BIGSERIAL PRIMARY KEY,
    caller      TEXT,
    provider    TEXT,
    model       TEXT,
    messages    JSONB,
    reply       TEXT,
    latency_ms  INT,
    is_fallback BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Error log (used by app/error_log.py with UPSERT semantics)
CREATE TABLE IF NOT EXISTS fazle_error_log (
    module      TEXT,
    error_type  TEXT,
    message     TEXT,
    count       INT NOT NULL DEFAULT 1,
    first_seen  TIMESTAMPTZ DEFAULT NOW(),
    last_seen   TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_error_log
    ON fazle_error_log (module, error_type, md5(COALESCE(message, '')));
