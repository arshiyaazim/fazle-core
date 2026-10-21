# Post-Chaos Validation Checklist


> **Pre-unification schema note.** Table names in this document refer to the
> pre-unification schema. See `audits/prefix_unification_2026-10-21.md` for the
> current table names.
**Purpose:** Verify system data integrity, operational health, and correctness after chaos/soak testing.
**Run this after every chaos test and before declaring system healthy.**
**Date of chaos test:** _______________
**Date of validation:** _______________

---

## Section 1 — Service Health

Run these first. If any fail, stop and recover before continuing.

```bash
#!/bin/bash
echo "=== Section 1: Service Health ==="

# 1.1 App health
echo -n "[1.1] App health: "
HTTP=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:8200/health)
[ "$HTTP" = "200" ] && echo "PASS ($HTTP)" || echo "FAIL ($HTTP)"

# 1.2 Deep health
echo "[1.2] Deep health:"
curl -sf -H "X-Internal-Key: $INTERNAL_KEY" http://localhost:8200/health/deep \
  | python3 -m json.tool

# 1.3 Bridge health
echo -n "[1.3] Bridge2 (OPS): "
curl -sf http://localhost:8081/health > /dev/null && echo "PASS" || echo "FAIL"
echo -n "[1.4] Bridge1 (HR): "
curl -sf http://localhost:8082/health > /dev/null && echo "PASS" || echo "FAIL"

# 1.5 DB connectivity
echo -n "[1.5] PostgreSQL: "
docker exec ai-postgres psql -U postgres -c "SELECT 1;" > /dev/null 2>&1 \
  && echo "PASS" || echo "FAIL"

# 1.6 Redis connectivity
echo -n "[1.6] Redis: "
docker exec ai-redis redis-cli PING | grep -q PONG && echo "PASS" || echo "FAIL"

# 1.7 Ollama
echo -n "[1.7] Ollama: "
curl -sf http://localhost:11434/api/tags > /dev/null && echo "PASS" || echo "WARN (degraded OK)"
```

---

## Section 2 — Database Consistency

### 2.1 Row Count Comparison

Before chaos test, capture baseline row counts. After, compare.

```bash
# Capture counts (run before AND after chaos)
docker exec ai-postgres psql -U postgres -d postgres << 'SQL'
SELECT
  'wbom_employees'          AS tbl, COUNT(*) AS n FROM wbom_employees UNION ALL
SELECT 'wbom_escort_programs',        COUNT(*) FROM wbom_escort_programs UNION ALL
SELECT 'wbom_attendance',             COUNT(*) FROM wbom_attendance UNION ALL
SELECT 'wbom_cash_transactions',      COUNT(*) FROM wbom_cash_transactions UNION ALL
SELECT 'wbom_payroll_runs',           COUNT(*) FROM wbom_payroll_runs UNION ALL
SELECT 'fazle_payment_drafts',        COUNT(*) FROM fazle_payment_drafts UNION ALL
SELECT 'fazle_payment_correction_log',COUNT(*) FROM fazle_payment_correction_log UNION ALL
SELECT 'fazle_admin_audit',           COUNT(*) FROM fazle_admin_audit UNION ALL
SELECT 'fazle_outbound_queue',        COUNT(*) FROM fazle_outbound_queue UNION ALL
SELECT 'fazle_scheduler_log',         COUNT(*) FROM fazle_scheduler_log
ORDER BY tbl;
SQL
```

Expected after chaos: row counts should be **at least as high** as baseline.
Unexpected decreases indicate data loss.

### 2.2 Orphan Detection

```bash
docker exec ai-postgres psql -U postgres -d postgres << 'SQL'
-- Orphan attendance records (no employee)
SELECT COUNT(*) AS orphan_attendance
FROM wbom_attendance wa
LEFT JOIN wbom_employees e ON e.id = wa.employee_id
WHERE e.id IS NULL;

-- Orphan payment drafts (escort type, no escort program)
SELECT COUNT(*) AS orphan_drafts
FROM fazle_payment_drafts fpd
LEFT JOIN wbom_escort_programs ep ON ep.id = fpd.escort_program_id
WHERE fpd.draft_type = 'escort'
  AND fpd.escort_program_id IS NOT NULL
  AND ep.id IS NULL;

-- Orphan cash transactions (no payment draft)
SELECT COUNT(*) AS orphan_transactions
FROM wbom_cash_transactions wct
LEFT JOIN fazle_payment_drafts fpd ON fpd.id = wct.draft_id
WHERE wct.draft_id IS NOT NULL AND fpd.id IS NULL;

-- Orphan payroll runs (no employee)
SELECT COUNT(*) AS orphan_payroll_runs
FROM wbom_payroll_runs pr
LEFT JOIN wbom_employees e ON e.id = pr.employee_id
WHERE e.id IS NULL;
SQL
# Expected: all counts = 0
```

### 2.3 Double-Finalize Detection

```bash
docker exec ai-postgres psql -U postgres -d postgres << 'SQL'
-- Drafts with multiple non-reversed cash transactions (double-finalize)
SELECT
  fpd.id AS draft_id,
  fpd.employee_id,
  fpd.expected_amount,
  fpd.status,
  COUNT(wct.id) AS transaction_count
FROM fazle_payment_drafts fpd
JOIN wbom_cash_transactions wct ON wct.draft_id = fpd.id
WHERE wct.is_reversed = false
GROUP BY fpd.id, fpd.employee_id, fpd.expected_amount, fpd.status
HAVING COUNT(wct.id) > 1
ORDER BY fpd.id DESC;
SQL
# Expected: 0 rows — any rows need manual review
```

### 2.4 Draft Status Consistency

```bash
docker exec ai-postgres psql -U postgres -d postgres << 'SQL'
-- Drafts marked 'sent' but no corresponding cash transaction
SELECT fpd.id, fpd.employee_id, fpd.status, fpd.expected_amount, fpd.updated_at
FROM fazle_payment_drafts fpd
LEFT JOIN wbom_cash_transactions wct ON wct.draft_id = fpd.id
WHERE fpd.status = 'sent' AND wct.id IS NULL
ORDER BY fpd.updated_at DESC
LIMIT 20;

-- Drafts stuck in 'approved' for > 24h
SELECT id, employee_id, expected_amount, status, updated_at,
       NOW() - updated_at AS age
FROM fazle_payment_drafts
WHERE status = 'approved'
  AND updated_at < NOW() - INTERVAL '24 hours'
ORDER BY updated_at;

-- Payment draft status distribution
SELECT status, COUNT(*) AS count
FROM fazle_payment_drafts
GROUP BY status
ORDER BY count DESC;
SQL
```

### 2.5 Escort Program Consistency

```bash
docker exec ai-postgres psql -U postgres -d postgres << 'SQL'
-- Programs 'Active' with no end date set and > 7 days old (stuck open)
SELECT id, employee_id, status, start_date, updated_at,
       NOW() - start_date AS age
FROM wbom_escort_programs
WHERE status = 'Active'
  AND start_date < NOW() - INTERVAL '7 days'
ORDER BY start_date;

-- Completed programs without attendance records
SELECT ep.id, ep.employee_id, ep.start_date, ep.end_date, ep.status
FROM wbom_escort_programs ep
LEFT JOIN wbom_attendance wa ON wa.employee_id = ep.employee_id
  AND wa.work_date BETWEEN ep.start_date AND COALESCE(ep.end_date, NOW()::DATE)
WHERE ep.status = 'Completed'
  AND ep.start_date IS NOT NULL
  AND ep.end_date IS NOT NULL
  AND wa.id IS NULL
ORDER BY ep.id DESC
LIMIT 10;
SQL
```

---

## Section 3 — Payment Integrity

### 3.1 Cash Transaction Totals

```bash
docker exec ai-postgres psql -U postgres -d postgres << 'SQL'
-- Total non-reversed cash outflows by method
SELECT
  transaction_type,
  payment_method,
  COUNT(*) AS transactions,
  SUM(amount) AS total_amount
FROM wbom_cash_transactions
WHERE is_reversed = false
GROUP BY transaction_type, payment_method
ORDER BY transaction_type, payment_method;

-- Reversed transactions check
SELECT COUNT(*) AS reversed_count, SUM(amount) AS reversed_total
FROM wbom_cash_transactions
WHERE is_reversed = true;

-- Counter-transactions in correction log
SELECT correction_type, COUNT(*) AS count
FROM fazle_payment_correction_log
GROUP BY correction_type;
SQL
```

### 3.2 Payroll Consistency

```bash
docker exec ai-postgres psql -U postgres -d postgres << 'SQL'
-- Payroll runs by status
SELECT status, COUNT(*) AS count
FROM wbom_payroll_runs
GROUP BY status
ORDER BY status;

-- Runs in 'approved' or 'locked' > 48h (stuck)
SELECT id, employee_id, status, period_year, period_month, updated_at,
       NOW() - updated_at AS age
FROM wbom_payroll_runs
WHERE status IN ('approved', 'locked')
  AND updated_at < NOW() - INTERVAL '48 hours'
ORDER BY updated_at;

-- Paid runs without cash transaction
SELECT pr.id, pr.employee_id, pr.status, pr.net_salary
FROM wbom_payroll_runs pr
LEFT JOIN wbom_cash_transactions wct ON wct.draft_id = pr.id
  AND wct.transaction_type = 'payroll'
WHERE pr.status = 'paid' AND wct.id IS NULL
LIMIT 10;
SQL
```

---

## Section 4 — Queue and Scheduler Health

### 4.1 Outbound Queue

```bash
docker exec ai-postgres psql -U postgres -d postgres << 'SQL'
-- Queue depth by status
SELECT status, COUNT(*) AS count,
       MAX(created_at) AS newest,
       MIN(created_at) AS oldest
FROM fazle_outbound_queue
GROUP BY status
ORDER BY status;

-- DLQ messages (failed beyond retry limit)
SELECT id, recipient_phone, message_type, retry_count, last_error, created_at
FROM fazle_outbound_queue
WHERE status = 'dead'
ORDER BY created_at DESC
LIMIT 20;

-- Stuck 'sending' messages (> 5 min old)
SELECT id, recipient_phone, created_at, retry_count
FROM fazle_outbound_queue
WHERE status = 'sending'
  AND updated_at < NOW() - INTERVAL '5 minutes'
ORDER BY created_at;
SQL
# Expected after chaos: dead count = 0 or explained; no stuck 'sending'
```

### 4.2 Scheduler Jobs

```bash
curl -sf -H "X-Internal-Key: $INTERNAL_KEY" http://localhost:8200/scheduler/status \
  | python3 -m json.tool

# Expected: all jobs show recent execution, no error status
# Jobs: backup_daily, payment_draft_sweep, outbound_sweep, gap_detect,
#       payroll_reminder, bridge_reconnect, dlq_alert, log_rotate,
#       metrics_flush, rag_reindex
```

---

## Section 5 — Audit Log Completeness

```bash
docker exec ai-postgres psql -U postgres -d postgres << 'SQL'
-- Recent admin actions (last 100)
SELECT actor, action, target_type, target_id, result, created_at
FROM fazle_admin_audit
ORDER BY created_at DESC
LIMIT 100;

-- Failed actions during chaos period
SELECT actor, action, result, error_detail, COUNT(*) AS count
FROM fazle_admin_audit
WHERE result = 'error'
  AND created_at > NOW() - INTERVAL '6 hours'
GROUP BY actor, action, result, error_detail
ORDER BY count DESC;
SQL
```

---

## Section 6 — Functional Smoke Test

Run after all DB checks pass:

```bash
cd /home/azim/core && source /home/azim/.venv/bin/activate

# Quick smoke (should complete in < 30s)
python -m pytest tests/unit/ -q --timeout=30 2>&1 | tail -5

# Workflow test (should complete in < 30s)
python -m pytest tests/workflows/test_escort_payment_flow.py -m workflow \
  --timeout=60 -q 2>&1 | tail -5
```

---

## Section 7 — Comparison with Pre-Chaos Baseline

Fill in after running both baseline and post-chaos snapshots:

| Table | Pre-Chaos Count | Post-Chaos Count | Delta | Expected | Status |
|---|---|---|---|---|---|
| wbom_employees | | | | >= 0 | |
| wbom_escort_programs | | | | >= 0 | |
| wbom_attendance | | | | >= 0 | |
| wbom_cash_transactions | | | | >= 0 | |
| wbom_payroll_runs | | | | >= 0 | |
| fazle_payment_drafts | | | | >= 0 | |
| fazle_admin_audit | | | | > 0 (chaos logged) | |
| fazle_outbound_queue (dead) | | | | = pre-chaos | |

---

## Section 8 — Dashboard Spot Check

```bash
# Verify dashboard renders
HTTP=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:8200/dashboard)
echo "Dashboard: $HTTP (expected 200)"

# Check key API endpoints
for endpoint in /admin/overview /admin/payment-drafts /admin/escort-programs /admin/cash-transactions; do
  HTTP=$(curl -sf -o /dev/null -w "%{http_code}" \
    -H "X-Internal-Key: $INTERNAL_KEY" "http://localhost:8200${endpoint}")
  echo "$endpoint: $HTTP"
done
```

---

## Section 9 — Resource Recovery Check

```bash
# Memory usage recovered
free -h

# DB connections back to normal
docker exec ai-postgres psql -U postgres -c \
  "SELECT count(*) AS total_connections, state FROM pg_stat_activity GROUP BY state ORDER BY state;"
# Expected: no 'idle in transaction', active connections <= pool_max (10)

# Disk space OK
df -h /home | awk 'NR>1 {print $5 " used on /home"}'
```

---

## Summary Scorecard

After running all sections, fill in:

| Section | Items | Issues Found | Severity | Status |
|---|---|---|---|---|
| 1. Service Health | 7 | | | |
| 2. DB Consistency | 5 | | | |
| 3. Payment Integrity | 2 | | | |
| 4. Queue + Scheduler | 2 | | | |
| 5. Audit Log | 2 | | | |
| 6. Smoke Tests | 2 | | | |
| 7. Baseline Comparison | 8 | | | |
| 8. Dashboard | 2 | | | |
| 9. Resource Recovery | 3 | | | |

**Issues requiring follow-up:**

| Issue | Severity | Action | Owner |
|---|---|---|---|
| | | | |

**Overall result:** [ ] CLEAN   [ ] ISSUES FOUND (see above)
**Signed off by:** _______________  
**Date/Time:** _______________
