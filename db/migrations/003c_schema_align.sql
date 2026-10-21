-- ============================================================
-- Migration 003: Schema alignment — fix all column mismatches
-- between app code and database tables.
-- Run: docker exec -i ai-postgres psql -U postgres -d postgres < db/migrations/003_schema_align.sql
-- ============================================================

BEGIN;

-- ── 1. fazle_payment_drafts ──────────────────────────────────────────────────
-- Code uses employee_mobile but DB has employee_phone → rename
ALTER TABLE fazle_payment_drafts
    RENAME COLUMN employee_phone TO employee_mobile;

-- Code uses expected_amount but DB has amount → rename
ALTER TABLE fazle_payment_drafts
    RENAME COLUMN amount TO expected_amount;

-- Add missing columns used by code
ALTER TABLE fazle_payment_drafts
    ADD COLUMN IF NOT EXISTS draft_type     TEXT          NOT NULL DEFAULT 'escort_payment',
    ADD COLUMN IF NOT EXISTS employee_id    INTEGER,
    ADD COLUMN IF NOT EXISTS escort_program_id INTEGER,
    ADD COLUMN IF NOT EXISTS duty_days      NUMERIC(6,2);

-- FK: payment draft → employee (SET NULL so draft is kept when employee is deleted)
ALTER TABLE fazle_payment_drafts
    ADD CONSTRAINT fazle_payment_drafts_employee_fkey
        FOREIGN KEY (employee_id)
        REFERENCES fazle_employees_legacy(employee_id)
        ON UPDATE CASCADE ON DELETE SET NULL;

-- FK: payment draft → escort program (SET NULL so draft survives program deletion)
ALTER TABLE fazle_payment_drafts
    ADD CONSTRAINT fazle_payment_drafts_program_fkey
        FOREIGN KEY (escort_program_id)
        REFERENCES wbom_escort_programs(program_id)
        ON UPDATE CASCADE ON DELETE SET NULL;

-- Index on employee_id for fast lookups
CREATE INDEX IF NOT EXISTS idx_fazle_payment_drafts_employee
    ON fazle_payment_drafts (employee_id);

-- ── 2. fazle_cash_transactions_archive ────────────────────────────────────────────────
-- transaction_date is NOT NULL with no default — code never provides it → add default
ALTER TABLE fazle_cash_transactions_archive
    ALTER COLUMN transaction_date SET DEFAULT CURRENT_DATE;

-- ── 3. FK CASCADE rules: employee-related tables ─────────────────────────────
-- Current: ON UPDATE NO ACTION, ON DELETE NO ACTION
-- Target:  ON UPDATE CASCADE (if employee_id ever changes), ON DELETE RESTRICT
--          (block deleting an employee who has financial/duty records)

-- wbom_attendance
ALTER TABLE wbom_attendance
    DROP CONSTRAINT fazle_attendance_employee_id_fkey,
    ADD CONSTRAINT fazle_attendance_employee_id_fkey
        FOREIGN KEY (employee_id)
        REFERENCES fazle_employees_legacy(employee_id)
        ON UPDATE CASCADE ON DELETE RESTRICT;

-- fazle_cash_transactions_archive (employee)
ALTER TABLE fazle_cash_transactions_archive
    DROP CONSTRAINT fazle_cash_transactions_archive_employee_id_fkey,
    ADD CONSTRAINT fazle_cash_transactions_archive_employee_id_fkey
        FOREIGN KEY (employee_id)
        REFERENCES fazle_employees_legacy(employee_id)
        ON UPDATE CASCADE ON DELETE RESTRICT;

-- wbom_escort_programs (employee)
ALTER TABLE wbom_escort_programs
    DROP CONSTRAINT fazle_escort_programs_escort_employee_id_fkey,
    ADD CONSTRAINT fazle_escort_programs_escort_employee_id_fkey
        FOREIGN KEY (escort_employee_id)
        REFERENCES fazle_employees_legacy(employee_id)
        ON UPDATE CASCADE ON DELETE RESTRICT;

-- wbom_salary_records (employee)
ALTER TABLE wbom_salary_records
    DROP CONSTRAINT fazle_salary_records_employee_id_fkey,
    ADD CONSTRAINT fazle_salary_records_employee_id_fkey
        FOREIGN KEY (employee_id)
        REFERENCES fazle_employees_legacy(employee_id)
        ON UPDATE CASCADE ON DELETE RESTRICT;

-- wbom_payroll_runs (employee)
ALTER TABLE wbom_payroll_runs
    DROP CONSTRAINT fazle_payroll_runs_employee_id_fkey,
    ADD CONSTRAINT fazle_payroll_runs_employee_id_fkey
        FOREIGN KEY (employee_id)
        REFERENCES fazle_employees_legacy(employee_id)
        ON UPDATE CASCADE ON DELETE RESTRICT;

-- wbom_employee_requests (employee) — already NO ACTION, upgrade to CASCADE/RESTRICT
ALTER TABLE wbom_employee_requests
    DROP CONSTRAINT fazle_employee_requests_employee_id_fkey,
    ADD CONSTRAINT fazle_employee_requests_employee_id_fkey
        FOREIGN KEY (employee_id)
        REFERENCES fazle_employees_legacy(employee_id)
        ON UPDATE CASCADE ON DELETE RESTRICT;

-- wbom_cases (employee)
ALTER TABLE wbom_cases
    DROP CONSTRAINT fazle_cases_employee_id_fkey,
    ADD CONSTRAINT fazle_cases_employee_id_fkey
        FOREIGN KEY (employee_id)
        REFERENCES fazle_employees_legacy(employee_id)
        ON UPDATE CASCADE ON DELETE SET NULL;

-- ── 4. fazle_whatsapp_messages: add missing index on sender_number ─────────────
CREATE INDEX IF NOT EXISTS idx_fazle_messages_sender
    ON fazle_whatsapp_messages (sender_number, received_at DESC);

-- ── 5. fazle_contacts: cascade contact deletion to messages ───────────────────
-- Currently NO ACTION — upgrade so deleting a contact cascades its message links to NULL
ALTER TABLE fazle_whatsapp_messages
    DROP CONSTRAINT fazle_whatsapp_messages_contact_id_fkey,
    ADD CONSTRAINT fazle_whatsapp_messages_contact_id_fkey
        FOREIGN KEY (contact_id)
        REFERENCES fazle_contacts(contact_id)
        ON UPDATE CASCADE ON DELETE SET NULL;

COMMIT;
