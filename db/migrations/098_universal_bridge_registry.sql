-- 098 — Universal WhatsApp Bridge Registry (N-bridge, MCP-ready)
-- Supports 1..N bridges per install; legacy bridge1/2/3 auto-seeded on first boot.
-- Backward compatible: existing fazle_whatsapp_messages + bridge_poller_cursor untouched.

-- ── Core registry ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS whatsapp_bridges (
    id                  BIGSERIAL PRIMARY KEY,
    bridge_id           TEXT NOT NULL UNIQUE,          -- slug: bridge1, bridge2, wa-hr-01, my-vps-bridge …
    label               TEXT NOT NULL DEFAULT '',      -- human: "HR", "OPS", "REC2"
    base_url            TEXT NOT NULL,                 -- http://localhost:8082
    messages_db_path    TEXT NOT NULL DEFAULT '',      -- /home/.../messages.db  (empty = webhook-only bridge)
    whatsapp_db_path    TEXT NOT NULL DEFAULT '',      -- /home/.../whatsapp.db  (LID→PN map)
    phone_number        TEXT NOT NULL DEFAULT '',      -- 8801XXXXXXXXX (owner number for this bridge)
    phone_number_jid    TEXT NOT NULL DEFAULT '',      -- 8801XXXXXXXXX@s.whatsapp.net (derived)
    direction           TEXT NOT NULL DEFAULT 'both' CHECK (direction IN ('both','inbound','outbound')),
    enabled             BOOLEAN NOT NULL DEFAULT true,
    priority            INT NOT NULL DEFAULT 100,      -- lower = preferred for outbound failover
    webhook_secret      TEXT NOT NULL DEFAULT '',
    extra_json          JSONB NOT NULL DEFAULT '{}'::jsonb, -- {media_download:true, call_log:true, …}
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_bridges_enabled ON whatsapp_bridges (enabled) WHERE enabled = true;
CREATE INDEX IF NOT EXISTS idx_whatsapp_bridges_priority ON whatsapp_bridges (priority ASC);

-- Keep updated_at fresh
CREATE OR REPLACE FUNCTION _touch_whatsapp_bridges_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_whatsapp_bridges_touch ON whatsapp_bridges;
CREATE TRIGGER trg_whatsapp_bridges_touch BEFORE UPDATE ON whatsapp_bridges
    FOR EACH ROW EXECUTE FUNCTION _touch_whatsapp_bridges_updated_at();

-- ── Per-bridge sync state (extends bridge_poller_cursor which used TEXT PK) ──
-- We keep bridge_poller_cursor for backward compat; new cursor lives in bridge_sync_state.
CREATE TABLE IF NOT EXISTS bridge_sync_state (
    bridge_id           TEXT PRIMARY KEY REFERENCES whatsapp_bridges(bridge_id) ON DELETE CASCADE,
    last_poll_ts        TIMESTAMPTZ,
    last_message_id     TEXT,
    history_synced      BOOLEAN NOT NULL DEFAULT false,
    history_total       INT NOT NULL DEFAULT 0,
    history_copied      INT NOT NULL DEFAULT 0,
    last_history_sync_at TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Canonical extended columns on fazle_whatsapp_messages (additive, nullable) ──
-- Existing prod table has: id, phone, message, direction, source_bridge, etc.
-- We add full WA identifiers so every message is self-describing.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fazle_whatsapp_messages' AND column_name='wa_message_id') THEN
        ALTER TABLE fazle_whatsapp_messages ADD COLUMN wa_message_id TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fazle_whatsapp_messages' AND column_name='wa_jid') THEN
        ALTER TABLE fazle_whatsapp_messages ADD COLUMN wa_jid TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fazle_whatsapp_messages' AND column_name='wa_lid') THEN
        ALTER TABLE fazle_whatsapp_messages ADD COLUMN wa_lid TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fazle_whatsapp_messages' AND column_name='wa_pn') THEN
        ALTER TABLE fazle_whatsapp_messages ADD COLUMN wa_pn TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fazle_whatsapp_messages' AND column_name='group_jid') THEN
        ALTER TABLE fazle_whatsapp_messages ADD COLUMN group_jid TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fazle_whatsapp_messages' AND column_name='media_type') THEN
        ALTER TABLE fazle_whatsapp_messages ADD COLUMN media_type TEXT; -- text|image|video|audio|document|sticker|call|missed_call|location|contact|unknown
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fazle_whatsapp_messages' AND column_name='media_path') THEN
        ALTER TABLE fazle_whatsapp_messages ADD COLUMN media_path TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fazle_whatsapp_messages' AND column_name='call_status') THEN
        ALTER TABLE fazle_whatsapp_messages ADD COLUMN call_status TEXT; -- call|missed_call|rejected|null
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fazle_whatsapp_messages' AND column_name='raw_json') THEN
        ALTER TABLE fazle_whatsapp_messages ADD COLUMN raw_json JSONB;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fazle_whatsapp_messages' AND column_name='bridge_id_ref') THEN
        ALTER TABLE fazle_whatsapp_messages ADD COLUMN bridge_id_ref TEXT; -- FK-like to whatsapp_bridges.bridge_id
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_fwm_wa_message_id ON fazle_whatsapp_messages (wa_message_id) WHERE wa_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fwm_wa_jid ON fazle_whatsapp_messages (wa_jid) WHERE wa_jid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fwm_group_jid ON fazle_whatsapp_messages (group_jid) WHERE group_jid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fwm_media_type ON fazle_whatsapp_messages (media_type) WHERE media_type IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fwm_bridge_id_ref ON fazle_whatsapp_messages (bridge_id_ref) WHERE bridge_id_ref IS NOT NULL;

-- ── Seed legacy bridges if whatsapp_bridges empty (handled also in Python for .env without DB) ──
-- No hard insert here — seeding is done by modules/whatsapp_mcp/registry.py on first boot
-- so it can read current .env values (bridge1_url etc.) instead of stale SQL literals.

COMMENT ON TABLE whatsapp_bridges IS 'Universal N-bridge registry — one row per WhatsApp bridge (MCP Phase 1, migration 098)';
COMMENT ON TABLE bridge_sync_state IS 'Per-bridge poll cursor + history-sync progress (Phase 1/2)';
