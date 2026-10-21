-- Migration: Add indexes to FPE tables for performance optimization
-- Purpose: Optimize frequently-searched columns on fazle_employees table
-- Date: 2026-06-26

-- Add index on employee_code for fast lookups
CREATE INDEX IF NOT EXISTS idx_fazle_employees_code 
  ON fazle_employees(employee_code);

-- Add index on primary_phone for fast lookups during income/cash entry
CREATE INDEX IF NOT EXISTS idx_fazle_employees_phone 
  ON fazle_employees(primary_phone);

-- Add index on fpe_income_transactions for fast lookups by date
CREATE INDEX IF NOT EXISTS idx_fazle_income_txn_date 
  ON fpe_income_transactions(txn_date);

-- Add index on fazle_cash_transactions for fast lookups by date
CREATE INDEX IF NOT EXISTS idx_fazle_cash_txn_date 
  ON fazle_cash_transactions(txn_date);

-- Verify indexes created
SELECT indexname, tablename 
FROM pg_indexes 
WHERE tablename IN ('fazle_employees', 'fpe_income_transactions', 'fazle_cash_transactions')
  AND indexname LIKE 'idx_fpe%'
ORDER BY tablename, indexname;
