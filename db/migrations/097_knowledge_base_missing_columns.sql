-- ============================================================================
-- 097_knowledge_base_missing_columns
-- ============================================================================
-- Declare three live `fazle_knowledge_base` columns that no migration in this
-- repository ever created: `subcategory`, `value` and `language`.
--
-- Found by audits/NAMING_MISMATCH_AUDIT_2026-10-24.md section 1.4. Until now
-- the column names existed only in application code and in other migrations'
-- statements, never in a CREATE TABLE / ALTER TABLE that a fresh database
-- would see.
--
-- WHY THESE THREE COLUMNS ARE REAL, NOT A CODE MISTAKE
--   * `value`    — migration 003 documents it as pre-existing on the live
--                  database ("DB had: key, value, tags") and migrates its
--                  contents into `reply_text` (`reply_text = value`). It is
--                  legacy, but it is real data.
--   * `subcategory` — migration 012's `ai_read_kb_articles` view selects
--                  `k.subcategory`, and that migration was applied to
--                  production; a missing column would have made the CREATE
--                  VIEW fail. Five code sites read or write it.
--   * `language` — scripts/seed_recruitment_kb.sql (applied to production,
--                  see db/MIGRATION_INVENTORY.md) INSERTs it, as does
--                  modules/kb_upload/routes.py.
--
-- WHAT THIS DOES
--   Adds the three columns to an EXISTING database. Purely additive:
--   `ADD COLUMN IF NOT EXISTS` with no NOT NULL, no DEFAULT rewrite and no
--   data backfill, so no row is touched and nothing is dropped.
--
--   On production these statements are expected to be no-ops — the columns
--   are already there. Their purpose is to (a) make the schema reproducible
--   from this repository and (b) converge any environment that genuinely
--   lacks them (a restored dump, a staging clone, a partially-migrated box).
--
--   A FROM-SCRATCH build does not need this file: migration 002 now declares
--   the same three columns in its canonical CREATE TABLE, and 002 runs before
--   migrations 012 and 021, which are the statements that actually needed
--   them. This file is the "existing database" half of that fix.
--
-- IDEMPOTENCY
--   Every statement is guarded, so this file is safe to re-run.
--
-- ROLLBACK
--   See the "ROLLBACK" section at the bottom of this file. Dropping these
--   columns is only safe once no code reads or writes them; today migration
--   012's view and five code sites do, so rollback would break them.
-- ============================================================================


-- ── 1. Ensure the table exists (no-op on every environment that has it) ────

CREATE TABLE IF NOT EXISTS fazle_knowledge_base (
    id               SERIAL PRIMARY KEY,
    category         TEXT        NOT NULL,
    subcategory      TEXT,
    key              TEXT        NOT NULL UNIQUE,
    value            TEXT,
    language         TEXT,
    trigger_keywords TEXT[]      DEFAULT '{}',
    reply_text       TEXT        NOT NULL,
    reply_short      TEXT,
    tags             TEXT[]      DEFAULT '{}',
    confidence       FLOAT       DEFAULT 1.0,
    is_active        BOOLEAN     DEFAULT true,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);


-- ── 2. Add the three missing columns to pre-existing tables ─────────────────

ALTER TABLE fazle_knowledge_base
    ADD COLUMN IF NOT EXISTS subcategory TEXT,
    ADD COLUMN IF NOT EXISTS value       TEXT,
    ADD COLUMN IF NOT EXISTS language    TEXT;


-- ── 3. Supporting index ─────────────────────────────────────────────────────
-- `subcategory` is used as a filter column by
-- modules/business_read_service.py's `kb_policies` QuerySpec.

CREATE INDEX IF NOT EXISTS idx_kb_subcategory ON fazle_knowledge_base(subcategory);


-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- >>> ROLLBACK-SQL-BEGIN
--
--   ALTER TABLE fazle_knowledge_base
--       DROP COLUMN IF EXISTS subcategory,
--       DROP COLUMN IF EXISTS value,
--       DROP COLUMN IF EXISTS language;
--
--   DROP INDEX IF EXISTS idx_kb_subcategory;
--
-- <<< ROLLBACK-SQL-END
--
-- ROLLBACK COMPLETE for knowledge_base_missing_columns
-- ============================================================================
