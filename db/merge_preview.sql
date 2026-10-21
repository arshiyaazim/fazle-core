-- Fazle Core — Phase 5 DB Merge Preview
-- READ-ONLY inspection queries. Nothing is dropped.
-- Run these to understand the data before any migration.
--
-- All real data lives in the `postgres` database.
-- The `waerp` database has only 12 reply_templates and 3 escort_clients rows.

-- ── 1. Count rows in key tables ───────────────────────────────────────────────
SELECT 'fazle_employees_legacy'        AS tbl, COUNT(*) AS rows FROM fazle_employees_legacy
UNION ALL
SELECT 'fazle_contacts',                COUNT(*)         FROM fazle_contacts
UNION ALL
SELECT 'fazle_whatsapp_messages',       COUNT(*)         FROM fazle_whatsapp_messages
UNION ALL
SELECT 'wbom_escort_programs',         COUNT(*)         FROM wbom_escort_programs
UNION ALL
SELECT 'fazle_cash_transactions_archive',       COUNT(*)         FROM fazle_cash_transactions_archive
UNION ALL
SELECT 'wbom_attendance',              COUNT(*)         FROM wbom_attendance
UNION ALL
SELECT 'wbom_candidates',              COUNT(*)         FROM wbom_candidates
UNION ALL
SELECT 'fazle_leads',                  COUNT(*)         FROM fazle_leads;

-- ── 2. Sample contacts (latest 5) ─────────────────────────────────────────────
SELECT contact_id, whatsapp_number, display_name, relation_type_id, last_seen
FROM fazle_contacts
ORDER BY last_seen DESC NULLS LAST
LIMIT 5;

-- ── 3. Sample employees ────────────────────────────────────────────────────────
SELECT employee_id, employee_name, employee_mobile, designation, status
FROM fazle_employees_legacy
ORDER BY employee_id DESC
LIMIT 5;

-- ── 4. Recent messages ────────────────────────────────────────────────────────
SELECT id, whatsapp_number, LEFT(message_content, 60) AS preview,
       direction, platform, created_at
FROM fazle_whatsapp_messages
ORDER BY created_at DESC NULLS LAST
LIMIT 10;

-- ── 5. Active escort programs ─────────────────────────────────────────────────
SELECT program_id, program_date, vessel_name,
       escort_employee_id, status
FROM wbom_escort_programs
ORDER BY program_date DESC NULLS LAST
LIMIT 10;

-- ── 6. Columns that fazle-core needs to write ─────────────────────────────────
-- fazle_whatsapp_messages columns:
\d fazle_whatsapp_messages

-- ── 7. Check for 'platform' column (needed for source tracking) ───────────────
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'fazle_whatsapp_messages'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- ── 8. If 'platform' column doesn't exist, add it: ────────────────────────────
-- ALTER TABLE fazle_whatsapp_messages ADD COLUMN IF NOT EXISTS platform TEXT DEFAULT 'unknown';
-- ALTER TABLE fazle_whatsapp_messages ADD COLUMN IF NOT EXISTS direction TEXT DEFAULT 'inbound';
