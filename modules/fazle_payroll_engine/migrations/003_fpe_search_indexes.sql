-- 003_fpe_search_indexes.sql
-- Indexes to support fast read-only employee search & transaction history.
-- Strictly additive. No schema/data mutation.

CREATE INDEX IF NOT EXISTS idx_fazle_emp_id_phone
    ON fazle_employees(employee_id_phone)
    WHERE employee_id_phone IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_fazle_emp_primary_phone
    ON fazle_employees(primary_phone)
    WHERE primary_phone IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_fazle_emp_name_norm
    ON fazle_employees(name_normalized);

CREATE INDEX IF NOT EXISTS idx_fazle_emp_canonical
    ON fazle_employees(canonical_employee_id)
    WHERE canonical_employee_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_fazle_txn_date_desc
    ON fazle_cash_transactions(txn_date DESC, id DESC);
