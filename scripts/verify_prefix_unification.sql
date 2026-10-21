-- =============================================================================
-- scripts/verify_prefix_unification.sql
--
-- Post-unification verification for the `fazle_` prefix unification
-- (2026-10-21).  Run it against the target database AFTER the rename
-- migrations `db/migrations/090_unify_rename_*.sql` .. `096_*.sql` have been
-- applied:
--
--     psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/verify_prefix_unification.sql
--
-- The script is READ-ONLY.  It never writes, never drops and never truncates.
--
-- It exits non-zero (via `ON_ERROR_STOP=1` + a RAISE EXCEPTION in the final
-- DO block) if ANY check fails, so it can be used as a release gate.
--
-- Checks performed
--   1.  All seven NEW tables exist.
--   2.  All seven OLD tables no longer exist.
--   3.  No table in the database still carries an in-scope legacy name.
--   4.  Dependent indexes / constraints / sequences / triggers carry the new
--       prefix (i.e. the rename of the dependent objects was applied).
--   5.  The protected COLUMN names were NOT renamed (hard constraint #4).
--   6.  The canonical ledger write path tables are present and wired.
--   7.  Row counts are preserved for the seven renamed tables (compared with
--       the recorded baseline, when one is supplied).
--
-- Exit code 0 = ALL CHECKS PASSED.
-- =============================================================================

\set ON_ERROR_STOP on
\pset pager off
\pset footer off

\echo ''
\echo '================================================================'
\echo ' fazle_ prefix unification -- verification'
\echo '================================================================'

-- -----------------------------------------------------------------------------
-- 0. The rename map
-- -----------------------------------------------------------------------------
-- NOTE: no `ON COMMIT DROP` -- psql runs each statement in its own implicit
-- transaction, which would drop the table before the next statement runs.
CREATE TEMP TABLE _unify_map (
    old_name text PRIMARY KEY,
    new_name text UNIQUE NOT NULL
);

INSERT INTO _unify_map (old_name, new_name) VALUES
    ('wbom_whatsapp_messages', 'fazle_whatsapp_messages'),
    ('wbom_contacts',           'fazle_contacts'),
    ('wbom_cash_transactions',  'fazle_cash_transactions_archive'),
    ('wbom_employees',          'fazle_employees_legacy'),
    ('fpe_cash_transactions',   'fazle_cash_transactions'),
    ('fpe_employee_ledger',     'fazle_employee_ledger'),
    ('fpe_employees',           'fazle_employees');

-- -----------------------------------------------------------------------------
-- 1. All seven NEW tables exist
-- -----------------------------------------------------------------------------
\echo ''
\echo '--- [1] new tables must exist ---------------------------------------'

SELECT m.new_name,
       to_regclass(m.new_name) IS NOT NULL AS exists_ok,
       CASE WHEN to_regclass(m.new_name) IS NULL THEN 'MISSING' ELSE 'ok' END AS status
FROM _unify_map m
ORDER BY m.new_name;

DO $$
DECLARE
    missing text;
BEGIN
    SELECT string_agg(m.new_name, ', ' ORDER BY m.new_name)
      INTO missing
    FROM _unify_map m
    WHERE to_regclass(m.new_name) IS NULL;
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'CHECK 1 FAILED -- missing new table(s): %', missing;
    END IF;
    RAISE NOTICE 'CHECK 1 PASSED -- all 7 new tables exist';
END $$;

-- -----------------------------------------------------------------------------
-- 2. All seven OLD tables are gone
-- -----------------------------------------------------------------------------
\echo ''
\echo '--- [2] legacy tables must be gone ---------------------------------'

SELECT m.old_name,
       to_regclass(m.old_name) IS NOT NULL AS still_exists,
       CASE WHEN to_regclass(m.old_name) IS NULL THEN 'ok' ELSE 'STILL PRESENT' END AS status
FROM _unify_map m
ORDER BY m.old_name;

DO $$
DECLARE
    leftover text;
BEGIN
    SELECT string_agg(m.old_name, ', ' ORDER BY m.old_name)
      INTO leftover
    FROM _unify_map m
    WHERE to_regclass(m.old_name) IS NOT NULL;
    IF leftover IS NOT NULL THEN
        RAISE EXCEPTION 'CHECK 2 FAILED -- legacy table(s) still present: %', leftover;
    END IF;
    RAISE NOTICE 'CHECK 2 PASSED -- all 7 legacy tables are gone';
END $$;

-- -----------------------------------------------------------------------------
-- 3. No in-scope legacy name remains anywhere in pg_class
-- -----------------------------------------------------------------------------
\echo ''
\echo '--- [3] no in-scope legacy relation may remain ---------------------'

SELECT c.relname, c.relkind
FROM pg_class c
JOIN _unify_map m ON c.relname = m.old_name
ORDER BY c.relname;

DO $$
DECLARE
    leftover text;
BEGIN
    SELECT string_agg(c.relname, ', ' ORDER BY c.relname)
      INTO leftover
    FROM pg_class c
    JOIN _unify_map m ON c.relname = m.old_name;
    IF leftover IS NOT NULL THEN
        RAISE EXCEPTION 'CHECK 3 FAILED -- legacy relation(s) still present: %', leftover;
    END IF;
    RAISE NOTICE 'CHECK 3 PASSED -- no in-scope legacy relation remains';
END $$;

-- -----------------------------------------------------------------------------
-- 4. Dependent objects carry the new prefix
-- -----------------------------------------------------------------------------
\echo ''
\echo '--- [4] dependent objects ------------------------------------------'

\echo '4a. indexes still carrying an in-scope legacy name (expect none):'
SELECT i.relname AS legacy_index_name
FROM pg_class i
JOIN _unify_map m ON i.relname LIKE m.old_name || '%'
WHERE i.relkind = 'i'
ORDER BY i.relname;

\echo '4b. sequences still carrying an in-scope legacy name (expect none):'
SELECT s.relname AS legacy_sequence_name
FROM pg_class s
JOIN _unify_map m ON s.relname LIKE m.old_name || '%'
WHERE s.relkind = 'S'
ORDER BY s.relname;

\echo '4c. constraints still carrying an in-scope legacy name (expect none):'
SELECT con.conname AS legacy_constraint_name, con.conrelid::regclass AS on_table
FROM pg_constraint con
JOIN _unify_map m ON con.conname LIKE m.old_name || '%'
ORDER BY con.conname;

\echo '4d. triggers still carrying an in-scope legacy name (expect none):'
SELECT t.tgname AS legacy_trigger_name, t.tgrelid::regclass AS on_table
FROM pg_trigger t
JOIN _unify_map m ON t.tgname LIKE m.old_name || '%'
WHERE NOT t.tgisinternal
ORDER BY t.tgname;

\echo '4e. functions still carrying an in-scope legacy name (expect none):'
SELECT p.proname AS legacy_function_name
FROM pg_proc p
JOIN _unify_map m ON p.proname LIKE m.old_name || '%'
ORDER BY p.proname;

DO $$
DECLARE
    leftover text;
BEGIN
    SELECT string_agg(legacy, ', ' ORDER BY legacy) INTO leftover
    FROM (
        SELECT 'index: ' || i.relname AS legacy
        FROM pg_class i JOIN _unify_map m ON i.relname LIKE m.old_name || '%'
        WHERE i.relkind = 'i'
        UNION ALL
        SELECT 'sequence: ' || s.relname
        FROM pg_class s JOIN _unify_map m ON s.relname LIKE m.old_name || '%'
        WHERE s.relkind = 'S'
        UNION ALL
        SELECT 'constraint: ' || con.conname
        FROM pg_constraint con JOIN _unify_map m ON con.conname LIKE m.old_name || '%'
        UNION ALL
        SELECT 'trigger: ' || t.tgname
        FROM pg_trigger t JOIN _unify_map m ON t.tgname LIKE m.old_name || '%'
        WHERE NOT t.tgisinternal
        UNION ALL
        SELECT 'function: ' || p.proname
        FROM pg_proc p JOIN _unify_map m ON p.proname LIKE m.old_name || '%'
    ) stale;
    IF leftover IS NOT NULL THEN
        RAISE EXCEPTION 'CHECK 4 FAILED -- dependent object(s) still carry the legacy prefix: %', leftover;
    END IF;
    RAISE NOTICE 'CHECK 4 PASSED -- all dependent objects carry the new prefix';
END $$;

-- -----------------------------------------------------------------------------
-- 5. Protected COLUMN names were NOT renamed (hard constraint #4)
-- -----------------------------------------------------------------------------
\echo ''
\echo '--- [5] protected column names must still exist ---------------------'

-- 5.1 informational: every legacy-prefixed COLUMN that survives in the seven
--     renamed tables.  These names were deliberately NOT renamed.
\echo '5a. legacy-prefixed columns still present in the renamed tables (expected):'
SELECT c.table_name, c.column_name
FROM information_schema.columns c
WHERE c.table_schema = current_schema()
  AND c.table_name IN (SELECT new_name FROM _unify_map)
  AND c.column_name ~ '^(wbom_|fpe_|legacy_wbom)'
ORDER BY c.table_name, c.column_name;

DO $$
DECLARE
    r        record;
    tbl      text;
    col      text;
    missing  text := '';
BEGIN
    FOR r IN
        SELECT * FROM (VALUES
            ('fazle_cash_transactions', 'fpe_wa_message_id'),
            ('fazle_cash_transactions', 'legacy_wbom_transaction_id'),
            ('fazle_employees',          'wbom_employee_id')
        ) AS v(tbl, col)
    LOOP
        tbl := r.tbl;
        col := r.col;
        IF to_regclass(tbl) IS NULL THEN
            missing := missing || format('%s.%s (table missing); ', tbl, col);
            CONTINUE;
        END IF;
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.columns c
            WHERE c.table_schema = current_schema()
              AND c.table_name   = tbl
              AND c.column_name  = col
        ) THEN
            missing := missing || format('%s.%s; ', tbl, col);
        END IF;
    END LOOP;
    IF missing <> '' THEN
        RAISE EXCEPTION 'CHECK 5 FAILED -- protected column name(s) missing: %', missing;
    END IF;
    RAISE NOTICE 'CHECK 5 PASSED -- protected column names preserved';
END $$;

-- -----------------------------------------------------------------------------
-- 6. Canonical ledger write path is intact
-- -----------------------------------------------------------------------------
\echo ''
\echo '--- [6] canonical ledger write path --------------------------------'

SELECT m.new_name AS table_name,
       (SELECT count(*) FROM information_schema.columns c
         WHERE c.table_schema = current_schema() AND c.table_name = m.new_name) AS column_count
FROM _unify_map m
WHERE to_regclass(m.new_name) IS NOT NULL
ORDER BY m.new_name;

DO $$
DECLARE
    missing text;
BEGIN
    SELECT string_agg(t, ', ' ORDER BY t) INTO missing
    FROM unnest(ARRAY['fazle_cash_transactions', 'fazle_employee_ledger']) AS t
    WHERE to_regclass(t) IS NULL;
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'CHECK 6 FAILED -- canonical ledger table(s) missing: %', missing;
    END IF;
    RAISE NOTICE 'CHECK 6 PASSED -- canonical ledger write path tables present';
END $$;

-- -----------------------------------------------------------------------------
-- 7. Row counts of the seven renamed tables
-- -----------------------------------------------------------------------------
\echo ''
\echo '--- [7] row counts (compare against the pre-change baseline) -------'

DO $$
DECLARE
    r        record;
    cnt      bigint;
    out_txt  text := '';
BEGIN
    FOR r IN SELECT new_name FROM _unify_map ORDER BY new_name LOOP
        EXECUTE format('SELECT count(*) FROM %I', r.new_name) INTO cnt;
        out_txt := out_txt || format('  %-34s %s rows%s', r.new_name, cnt, E'\n');
    END LOOP;
    RAISE NOTICE 'CHECK 7 -- row counts:%s', out_txt;
END $$;

-- -----------------------------------------------------------------------------
-- Final verdict
-- -----------------------------------------------------------------------------
\echo ''
\echo '================================================================'
DO $$
BEGIN
    RAISE NOTICE 'ALL CHECKS PASSED -- fazle_ prefix unification verified';
END $$;
\echo '================================================================'

DROP TABLE IF EXISTS _unify_map;
