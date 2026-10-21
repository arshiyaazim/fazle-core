-- ============================================================
-- Migration 006: Critical-contact zero-loss + strict number identity
-- Run: docker exec -i ai-postgres psql -U postgres -d postgres < db/migrations/006_critical_contact_zero_loss.sql
-- ============================================================

BEGIN;

ALTER TABLE fazle_whatsapp_messages
    ADD COLUMN IF NOT EXISTS canonical_phone TEXT,
    ADD COLUMN IF NOT EXISTS phone_last10 TEXT,
    ADD COLUMN IF NOT EXISTS source_message_ref TEXT,
    ADD COLUMN IF NOT EXISTS source_timestamp TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source_context TEXT,
    ADD COLUMN IF NOT EXISTS message_hash TEXT,
    ADD COLUMN IF NOT EXISTS critical_contact BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS critical_log_path TEXT,
    ADD COLUMN IF NOT EXISTS original_sender_number TEXT;

CREATE INDEX IF NOT EXISTS idx_fazle_messages_canonical_phone
    ON fazle_whatsapp_messages (canonical_phone, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_fazle_messages_phone_last10
    ON fazle_whatsapp_messages (phone_last10, received_at DESC);

DROP INDEX IF EXISTS uq_fazle_messages_hash;
CREATE UNIQUE INDEX IF NOT EXISTS uq_fazle_messages_hash
    ON fazle_whatsapp_messages (message_hash);

CREATE TABLE IF NOT EXISTS fazle_contact_aliases (
    phone           TEXT        NOT NULL,
    alias_name      TEXT        NOT NULL,
    source_bridge   TEXT        NOT NULL DEFAULT '',
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (phone, alias_name)
);

CREATE INDEX IF NOT EXISTS idx_fazle_contact_aliases_phone
    ON fazle_contact_aliases (phone, last_seen DESC);

COMMIT;