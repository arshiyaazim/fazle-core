-- Migration 006: Income transactions table
-- Stores company income received from clients/employees, reported via
-- the "Income <phone> <name> <amount>" WhatsApp command.
-- This table is intentionally SEPARATE from fazle_cash_transactions so
-- income and payroll expenses stay in distinct ledgers.

CREATE TABLE IF NOT EXISTS fpe_income_transactions (
    id                  BIGSERIAL     PRIMARY KEY,
    txn_ref             TEXT          UNIQUE NOT NULL,
    fpe_wa_message_id   BIGINT        REFERENCES fpe_wa_messages(id),
    employee_id         BIGINT        REFERENCES fazle_employees(id),
    employee_name_raw   TEXT,
    amount              NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    txn_date            DATE          NOT NULL,
    accounting_period   TEXT          NOT NULL,        -- YYYY-MM
    reported_by_phone   TEXT,                          -- normalized 01XXXXXXXXX sender
    source_message_text TEXT,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fazle_income_emp
    ON fpe_income_transactions(employee_id, txn_date DESC);

CREATE INDEX IF NOT EXISTS idx_fazle_income_period
    ON fpe_income_transactions(accounting_period);

CREATE INDEX IF NOT EXISTS idx_fazle_income_reporter
    ON fpe_income_transactions(reported_by_phone);
