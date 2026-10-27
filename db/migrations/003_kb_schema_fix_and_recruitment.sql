-- Migration 003: Fix knowledge_base schema mismatch + create recruitment sessions table
-- Safe: all statements are idempotent (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS)
-- Run: docker exec -i ai-postgres psql -U postgres < /home/azim/fazle-core/db/migrations/003_kb_schema_fix_and_recruitment.sql

BEGIN;

-- ── Phase 4: Fix fazle_knowledge_base schema ──────────────────────────────────
-- DB had: key, value, tags
-- Code expected: trigger_keywords text[], reply_text text, is_active boolean

ALTER TABLE fazle_knowledge_base
    ADD COLUMN IF NOT EXISTS trigger_keywords text[],
    ADD COLUMN IF NOT EXISTS reply_text text,
    ADD COLUMN IF NOT EXISTS is_active boolean DEFAULT true;

-- Migrate existing data: key field → trigger_keywords array, value → reply_text
-- The 'key' column contains a keyword string (use as single-element array)
-- The 'value' column contains the reply text
-- tags column (text[]) also has useful keywords — merge both
UPDATE fazle_knowledge_base
SET
    trigger_keywords = CASE
        WHEN tags IS NOT NULL AND array_length(tags, 1) > 0
            THEN array_cat(ARRAY[key], tags)
        ELSE ARRAY[key]
    END,
    reply_text = value,
    is_active = true
WHERE trigger_keywords IS NULL;

-- Index for quick is_active lookups
CREATE INDEX IF NOT EXISTS idx_fkb_is_active ON fazle_knowledge_base (is_active);

-- ── Phase 5: Create fazle_recruitment_sessions (was missing) ──────────────────
-- This is the session table the recruitment_flow module expects.
-- Maps to wbom_candidates for final storage after completion.

CREATE TABLE IF NOT EXISTS fazle_recruitment_sessions (
    id              bigserial PRIMARY KEY,
    phone           text NOT NULL,
    source          text NOT NULL DEFAULT 'bridge1',
    step            text NOT NULL DEFAULT 'name',
    -- Collected data fields
    name            text,
    age             integer,
    area            text,
    job_preference  text,
    experience      integer,
    phone_confirm   text,
    -- Session state
    status          text NOT NULL DEFAULT 'active',   -- active | complete | abandoned
    candidate_id    integer REFERENCES wbom_candidates(candidate_id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Fresh-build fix (2026-10-27): migration 002_align_tables.sql already creates
-- this table (with collection_step/funnel_stage and no status/candidate_id), so
-- the CREATE TABLE IF NOT EXISTS above is a no-op on a clean database and the
-- two statements that follow it died with `column "status" does not exist`,
-- aborting db/migrate.py on a brand-new database. Additive, guarded, and a
-- no-op on every database where 003 has already been applied. The FK from the
-- CREATE above is deliberately NOT added here -- wbom_candidates does not exist
-- on a fresh build, and the column is used for provenance only.
ALTER TABLE fazle_recruitment_sessions
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active';

ALTER TABLE fazle_recruitment_sessions
    ADD COLUMN IF NOT EXISTS candidate_id integer;

CREATE UNIQUE INDEX IF NOT EXISTS idx_recruitment_sessions_phone_active
    ON fazle_recruitment_sessions (phone)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_recruitment_sessions_phone
    ON fazle_recruitment_sessions (phone);

CREATE INDEX IF NOT EXISTS idx_recruitment_sessions_status
    ON fazle_recruitment_sessions (status);

-- ── Phase 8: Normalize direction values in fazle_whatsapp_messages ─────────────
-- Ensure any remaining non-standard direction values are corrected
UPDATE fazle_whatsapp_messages
SET direction = 'inbound'
WHERE direction IN ('incoming', 'in', 'received')
  AND direction != 'inbound';

UPDATE fazle_whatsapp_messages
SET direction = 'outbound'
WHERE direction IN ('outgoing', 'out', 'sent')
  AND direction != 'outbound';

COMMIT;

-- Verify
SELECT
    'fazle_knowledge_base' AS table_name,
    COUNT(*) AS total_rows,
    COUNT(*) FILTER (WHERE is_active = true) AS active_rows,
    COUNT(*) FILTER (WHERE trigger_keywords IS NOT NULL) AS with_keywords
FROM fazle_knowledge_base;
