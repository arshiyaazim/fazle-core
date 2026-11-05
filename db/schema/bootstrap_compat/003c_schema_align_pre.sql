-- Fresh-database compatibility shim for historical migration 003c.
--
-- core/002_align_tables.sql now creates fazle_payment_drafts directly with the
-- canonical names employee_mobile and expected_amount. Historical migration
-- 003c_schema_align.sql predates that correction and unconditionally renames
-- employee_phone -> employee_mobile and amount -> expected_amount. On a fresh
-- database it therefore fails before applying its still-required FK/index
-- alignment statements.
--
-- Recreate the historical pre-003c names only for the duration of bootstrap;
-- 003c immediately renames them back. This file is NOT an existing-database
-- migration and is intentionally ordered immediately before core/003c.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'fazle_payment_drafts'
          AND column_name = 'employee_mobile'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'fazle_payment_drafts'
          AND column_name = 'employee_phone'
    ) THEN
        ALTER TABLE public.fazle_payment_drafts
            RENAME COLUMN employee_mobile TO employee_phone;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'fazle_payment_drafts'
          AND column_name = 'expected_amount'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'fazle_payment_drafts'
          AND column_name = 'amount'
    ) THEN
        ALTER TABLE public.fazle_payment_drafts
            RENAME COLUMN expected_amount TO amount;
    END IF;
END $$;

-- The foundation uses PostgreSQL's automatic constraint names for inline
-- REFERENCES clauses, while 003c drops the production-captured `fazle_*`
-- names explicitly. Rename those constraints to the historical names first.
DO $$
DECLARE
    item TEXT[];
BEGIN
    FOREACH item SLICE 1 IN ARRAY ARRAY[
        ['wbom_attendance', 'wbom_attendance_employee_id_fkey', 'fazle_attendance_employee_id_fkey'],
        ['wbom_escort_programs', 'wbom_escort_programs_escort_employee_id_fkey', 'fazle_escort_programs_escort_employee_id_fkey'],
        ['wbom_salary_records', 'wbom_salary_records_employee_id_fkey', 'fazle_salary_records_employee_id_fkey'],
        ['wbom_payroll_runs', 'wbom_payroll_runs_employee_id_fkey', 'fazle_payroll_runs_employee_id_fkey'],
        ['wbom_employee_requests', 'wbom_employee_requests_employee_id_fkey', 'fazle_employee_requests_employee_id_fkey'],
        ['wbom_cases', 'wbom_cases_employee_id_fkey', 'fazle_cases_employee_id_fkey']
    ]
    LOOP
        IF EXISTS (
            SELECT 1
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'public'
              AND t.relname = item[1]
              AND c.conname = item[2]
        ) THEN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = item[3]
            ) THEN
                -- Early bootstrap catalog 029 already added the captured
                -- production name; discard the duplicate auto-named FK.
                EXECUTE format(
                    'ALTER TABLE public.%I DROP CONSTRAINT %I',
                    item[1], item[2]
                );
            ELSE
                EXECUTE format(
                    'ALTER TABLE public.%I RENAME CONSTRAINT %I TO %I',
                    item[1], item[2], item[3]
                );
            END IF;
        END IF;
    END LOOP;
END $$;

-- The early catalog normally supplies this production-captured FK name.
-- Keep the prerequisite explicit for reviewed non-empty adoption too, because
-- historical 003c unconditionally drops and recreates this constraint.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fazle_whatsapp_messages_contact_id_fkey'
    ) THEN
        ALTER TABLE public.fazle_whatsapp_messages
            ADD CONSTRAINT fazle_whatsapp_messages_contact_id_fkey
            FOREIGN KEY (contact_id)
            REFERENCES public.fazle_contacts(contact_id);
    END IF;
END $$;
