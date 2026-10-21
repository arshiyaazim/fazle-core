-- ============================================================================
-- Migration 013: Uniform salary baseline at 10,000.00
-- ============================================================================
-- Goal:
--   1) Set all existing employee salaries to 10000.00
--   2) Keep future inserts defaulted to 10000.00
--
-- Notes:
--   - Additive/safe update only on fazle_employees.basic_salary
--   - No transactional ledger rows are modified here

ALTER TABLE fazle_employees
    ALTER COLUMN basic_salary SET DEFAULT 10000.00;

UPDATE fazle_employees
SET basic_salary = 10000.00,
    updated_at = NOW()
WHERE basic_salary IS DISTINCT FROM 10000.00;
