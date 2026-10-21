# Recovery Procedures — Fazle Core

**Last updated:** 2026-05-07
**Applies to:** `/home/azim/core` (production Fazle Core instance)

> **Before attempting recovery:** Take a backup of the current (potentially broken) state first.
> See `BACKUP.md` for backup procedures.

---

## Quick Reference

| Scenario | Jump To |
|---|---|
| App won't start | [Section 1](#1-service-recovery) |
| Database corruption / restore from backup | [Section 2](#2-postgresql-restore) |
| Redis state lost | [Section 3](#3-redis-recovery) |
| Full disaster recovery | [Section 4](#4-full-disaster-recovery) |
| Roll back code to previous version | [Section 5](#5-code-rollback) |
| Bridge stopped receiving messages | [Section 6](#6-bridge-recovery) |
| Data consistency repair | [Section 7](#7-data-consistency-repair) |

---

## 1. Service Recovery

### App Won't Start

```bash
# 1. Check service status
sudo systemctl status fazle-core.service

# 2. Check logs for startup error
journalctl -u fazle-core -n 100 --no-pager

# 3. Check port conflict
ss -tlnp | grep 8200

# 4. Verify .env exists and is readable
ls -la /home/azim/core/.env
cat /home/azim/core/.env | grep -v password | grep -v token

# 5. Test imports manually
cd /home/azim/core && source /home/azim/.venv/bin/activate
python -c "from app.main import app; print('OK')"

# 6. Check DB connectivity
docker exec ai-postgres psql -U postgres -c "SELECT 1;" 2>&1

# 7. Restart service
sudo systemctl restart fazle-core.service
curl http://localhost:8200/health
```

### App Crashed Mid-Request (500 errors)

```bash
# Check last error
journalctl -u fazle-core -n 50 --no-pager | grep -E "ERROR|Exception|Traceback"

# Check observability endpoint (if app is up)
curl -H "X-Internal-Key: <key>" http://localhost:8200/observability/errors \
  | python3 -m json.tool

# Safe restart (drains in-flight requests via systemd TimeoutStopSec)
sudo systemctl restart fazle-core.service
```

---

## 2. PostgreSQL Restore

### Identify Backup to Restore

```bash
ls -lht /home/azim/backups/fazle/*.dump
# Choose the most recent valid backup, or the last known-good pre-chaos backup
```

### Restore Procedure (Live DB Rename)

> **Warning:** This replaces the production database. Stop the app first.

```bash
# Step 1: Stop application
sudo systemctl stop fazle-core.service

# Step 2: Verify backup file integrity
BACKUP_FILE="/home/azim/backups/fazle/fazle_pg_YYYYMMDD_HHMMSS.dump"
docker cp "$BACKUP_FILE" ai-postgres:/tmp/restore.dump
docker exec ai-postgres pg_restore --list /tmp/restore.dump > /dev/null \
  && echo "VALID" || (echo "CORRUPT — aborting" && exit 1)

# Step 3: Create restore target database
docker exec ai-postgres psql -U postgres \
  -c "CREATE DATABASE postgres_restore;"

# Step 4: Restore into new database
docker exec ai-postgres pg_restore \
  -U postgres \
  -d postgres_restore \
  --no-owner \
  --no-privileges \
  --verbose \
  /tmp/restore.dump 2>&1 | tail -20

# Step 5: Verify row counts in restored database
docker exec ai-postgres psql -U postgres -d postgres_restore -c "
  SELECT 'fazle_employees_legacy' AS t, COUNT(*) AS n FROM fazle_employees_legacy
  UNION ALL SELECT 'fazle_payment_drafts', COUNT(*) FROM fazle_payment_drafts
  UNION ALL SELECT 'fazle_cash_transactions_archive', COUNT(*) FROM fazle_cash_transactions_archive
  UNION ALL SELECT 'wbom_escort_programs', COUNT(*) FROM wbom_escort_programs;
"

# Step 6: Disconnect all sessions from production DB
docker exec ai-postgres psql -U postgres -c "
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE datname = 'postgres' AND pid <> pg_backend_pid();
"

# Step 7: Rename databases (atomic swap)
docker exec ai-postgres psql -U postgres \
  -c "ALTER DATABASE postgres RENAME TO postgres_broken_$(date +%Y%m%d_%H%M%S);"
docker exec ai-postgres psql -U postgres \
  -c "ALTER DATABASE postgres_restore RENAME TO postgres;"

# Step 8: Restart application
sudo systemctl start fazle-core.service
sleep 3
curl http://localhost:8200/health
curl -H "X-Internal-Key: <key>" http://localhost:8200/health/deep

# Step 9: Drop old broken database (only after verifying app is healthy)
# docker exec ai-postgres psql -U postgres \
#   -c "DROP DATABASE postgres_broken_YYYYMMDD_HHMMSS;"
```

### Restore Specific Tables Only

```bash
# Restore only payment drafts table
docker exec ai-postgres pg_restore \
  -U postgres \
  -d postgres \
  --table=fazle_payment_drafts \
  --no-owner \
  --data-only \
  /tmp/restore.dump
```

---

## 3. Redis Recovery

Redis data loss causes transient degradation only (rate limits reset, session state clears).
No manual data recovery is needed unless admin dedup state is important.

### Redis Won't Start

```bash
# Check container status
docker inspect ai-redis | grep Status

# Restart container
docker restart ai-redis

# Verify
docker exec ai-redis redis-cli -a <pass> PING
```

### Restore Redis from RDB

```bash
# Stop container
docker stop ai-redis

# Copy backup RDB into container data volume
docker cp /home/azim/backups/redis/redis_YYYYMMDD.rdb ai-redis:/data/dump.rdb

# Restart container (Redis loads dump.rdb on startup)
docker start ai-redis
sleep 2
docker exec ai-redis redis-cli -a <pass> PING
docker exec ai-redis redis-cli -a <pass> DBSIZE
```

---

## 4. Full Disaster Recovery

Use this when the host machine or Docker infrastructure is lost.

### Prerequisites

- A new host with Docker and Docker Compose installed
- Access to `/home/azim/backups/` (NFS, S3, or manual copy)
- Access to `/home/azim/secure-env-backup/core.env.*`

### Steps

```bash
# Step 1: Set up infrastructure
git clone <repo> /home/azim/core
cd /home/azim/ai-call-platform
docker compose up -d

# Wait for containers to be healthy
docker ps --format "{{.Names}}: {{.Status}}"

# Step 2: Restore .env
cp /path/to/secure-env-backup/core.env.YYYYMMDD /home/azim/core/.env
chmod 600 /home/azim/core/.env

# Step 3: Restore Python environment
cd /home/azim/core
python3.11 -m venv /home/azim/.venv
source /home/azim/.venv/bin/activate
pip install -e .

# Step 4: Restore PostgreSQL
BACKUP_FILE="/path/to/fazle_pg_YYYYMMDD.dump"
docker cp "$BACKUP_FILE" ai-postgres:/tmp/restore.dump
docker exec ai-postgres pg_restore \
  -U postgres -d postgres \
  --no-owner --no-privileges \
  /tmp/restore.dump

# Step 5: Verify DB
docker exec ai-postgres psql -U postgres -c "
  SELECT COUNT(*) FROM fazle_employees_legacy;
"

# Step 6: Start fazle-core service
sudo systemctl start fazle-core.service
curl http://localhost:8200/health/deep

# Step 7: Verify full functionality
cd /home/azim/core && source /home/azim/.venv/bin/activate
make smoke

# Step 8: Restore bridge state
sudo systemctl start bridge1
sudo systemctl start bridge2
curl http://localhost:8081/health
curl http://localhost:8082/health
```

### Recovery Time Objectives (targets)

| Scenario | Target RTO | Target RPO |
|---|---|---|
| App restart only | < 1 minute | 0 (no data loss) |
| DB restore from last backup | < 15 minutes | Up to 24 hours |
| Full disaster recovery | < 2 hours | Up to 24 hours |
| Full disaster with off-host backup | < 4 hours | Up to 24 hours |

---

## 5. Code Rollback

### Via Git (recommended)

```bash
cd /home/azim/core

# View recent commits
git log --oneline -20

# View available tags
git tag -l | sort -r | head -10

# Roll back to a specific tag
sudo systemctl stop fazle-core.service
git stash                               # save any local changes
git checkout v1.0.1-hotfix              # or any tag
sudo systemctl start fazle-core.service
curl http://localhost:8200/health

# Verify tests still pass after rollback
source /home/azim/.venv/bin/activate
make smoke
```

### Via File Snapshot (if git not available)

```bash
# Stop app
sudo systemctl stop fazle-core.service

# Backup current state
cp -r /home/azim/core /home/azim/core_rollback_$(date +%Y%m%d_%H%M%S)

# Restore from tar snapshot
tar -xzf /home/azim/backups/core_pre_chaos_TIMESTAMP.tar.gz -C /

# Restore Python dependencies if pyproject.toml changed
cd /home/azim/core
source /home/azim/.venv/bin/activate
pip install -e .

# Restart
sudo systemctl start fazle-core.service
curl http://localhost:8200/health
```

---

## 6. Bridge Recovery

### Bridge Not Responding

```bash
# Check health
curl http://localhost:8081/health        # OPS bridge
curl http://localhost:8082/health        # HR bridge

# Check service status
sudo systemctl status bridge2
sudo systemctl status bridge1

# Restart bridge
sudo systemctl restart bridge2
sudo systemctl restart bridge1

# View logs
journalctl -u bridge2 -n 50 --no-pager
journalctl -u bridge1 -n 50 --no-pager
```

### Bridge Not Polling New Messages

```bash
# Check bridge cursor position in DB
docker exec ai-postgres psql -U postgres -d postgres \
  -c "SELECT * FROM fazle_bridge_cursors ORDER BY updated_at DESC;"

# Reset cursor to force re-poll (WARNING: may replay messages)
# Only use if cursor is stuck and messages are genuinely missing
# docker exec ai-postgres psql -U postgres -d postgres \
#   -c "UPDATE fazle_bridge_cursors SET last_id = 0 WHERE bridge = 'bridge2';"

# Restart app to reset poller state
sudo systemctl restart fazle-core.service
```

---

## 7. Data Consistency Repair

### Find Orphan Records

```bash
docker exec ai-postgres psql -U postgres -d postgres << 'SQL'
-- Escort programs without any attendance records
SELECT ep.id, ep.employee_id, ep.status, ep.start_date, ep.end_date
FROM wbom_escort_programs ep
LEFT JOIN wbom_attendance wa ON wa.employee_id = ep.employee_id
  AND wa.work_date BETWEEN ep.start_date AND ep.end_date
WHERE ep.status = 'Completed' AND wa.id IS NULL
ORDER BY ep.id DESC LIMIT 20;

-- Payment drafts without completed escort program
SELECT fpd.id, fpd.employee_id, fpd.escort_program_id, fpd.status
FROM fazle_payment_drafts fpd
LEFT JOIN wbom_escort_programs ep ON ep.id = fpd.escort_program_id
WHERE fpd.draft_type = 'escort'
  AND fpd.escort_program_id IS NOT NULL
  AND ep.id IS NULL
LIMIT 20;

-- Cash transactions without payment draft
SELECT wct.id, wct.employee_id, wct.amount, wct.transaction_date
FROM fazle_cash_transactions_archive wct
LEFT JOIN fazle_payment_drafts fpd ON fpd.id = wct.draft_id
WHERE wct.draft_id IS NOT NULL AND fpd.id IS NULL
LIMIT 20;
SQL
```

### Fix Double-Finalized Payments

```bash
docker exec ai-postgres psql -U postgres -d postgres << 'SQL'
-- Find drafts with multiple cash transactions
SELECT fpd.id, fpd.employee_id, fpd.expected_amount, COUNT(wct.id) AS txn_count
FROM fazle_payment_drafts fpd
JOIN fazle_cash_transactions_archive wct ON wct.draft_id = fpd.id
WHERE wct.is_reversed = false
GROUP BY fpd.id, fpd.employee_id, fpd.expected_amount
HAVING COUNT(wct.id) > 1
ORDER BY fpd.id DESC;
SQL
# If found, manually reverse the duplicate via:
# POST /admin/payment-drafts/{id}/reverse
```

### Repair Missing Contact IDs

```bash
# Run the backfill script (safe, idempotent)
cd /home/azim/core
source /home/azim/.venv/bin/activate
python /home/azim/core/recover_critical_numbers.py --dry-run
python /home/azim/core/recover_critical_numbers.py
```

---

## 8. Recovery Validation Checklist

After any recovery, verify these before resuming operations:

```bash
#!/bin/bash
echo "=== Recovery Validation ==="

# 1. App health
echo -n "App health: "
curl -sf http://localhost:8200/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('status')=='ok' else 'FAIL')"

# 2. Deep health
echo -n "Deep health: "
curl -sf -H "X-Internal-Key: $INTERNAL_KEY" http://localhost:8200/health/deep \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('ok') else 'FAIL')"

# 3. DB row counts
echo "DB row counts:"
docker exec ai-postgres psql -U postgres -d postgres -t -c "
  SELECT '  employees: ' || COUNT(*) FROM fazle_employees_legacy;
" 2>&1

# 4. Pending drafts
echo -n "Pending drafts: "
curl -sf -H "X-Internal-Key: $INTERNAL_KEY" \
  "http://localhost:8200/admin/payment-drafts?status=pending" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('payment_drafts',[])))"

# 5. Bridge health
echo -n "Bridge2 health: "; curl -sf http://localhost:8081/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d else 'FAIL')"
echo -n "Bridge1 health: "; curl -sf http://localhost:8082/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d else 'FAIL')"

# 6. Quick smoke test
echo "Smoke tests:"
cd /home/azim/core && source /home/azim/.venv/bin/activate
python -m pytest tests/unit/ -q --timeout=30 2>&1 | tail -3
```
