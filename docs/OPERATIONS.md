# Operations Runbook

## Service control

```bash
# Status / restart / stop / logs
sudo systemctl status  fazle-core.service
sudo systemctl restart fazle-core.service
sudo systemctl stop    fazle-core.service
sudo journalctl -u fazle-core -n 200 -f

# App log (structured)
tail -f /home/azim/core/logs/fazle-core.log
```

Service runs as user `azim`, venv at `/home/azim/core/venv`,
binds `127.0.0.1:8200`. Public traffic terminates at nginx.

On every managed restart, systemd now runs
`/home/azim/shared/scripts/generate_runtime_services_env.sh` before starting the
service. That script resolves the current Docker IPs for `ai-postgres`,
`ai-redis`, and `ollama`, then writes live connection values into
`/home/azim/secure-env-backup/runtime-services.env`.

## Environment

`.env` lives at `/home/azim/core/.env` (NEVER committed).
It now stores stable templates for Docker-backed service URLs; the actual
runtime connection values are materialized into
`/home/azim/secure-env-backup/runtime-services.env`.

Critical keys:

| Var | Meaning |
|---|---|
| `DATABASE_URL_TEMPLATE` | PostgreSQL DSN template with `__HOST__` placeholder |
| `REDIS_URL_TEMPLATE` | Redis URL template with `__HOST__` placeholder |
| `OLLAMA_URL_TEMPLATE` | Ollama URL template with `__HOST__` placeholder |
| `INTERNAL_API_KEY` | Legacy single key (kept alongside per-admin keys) |
| `AUTO_REPLY_ENABLED` | `false` = SAFE MODE (drafts only, no send) |
| `ADMIN_NUMBERS` | Comma list; bootstrapped to superadmin on boot |
| `OCR_CONCURRENCY` | OCR semaphore (default 2) |
| `PAYROLL_BULK_CONCURRENCY` | Payroll semaphore (default 1) |
| `USE_OUTBOUND_QUEUE` | `true` recommended (B15.9) |

Backups of `.env` and generated runtime env files live in
`/home/azim/secure-env-backup/`.

## Deploy

```bash
cd /home/azim/core
git checkout develop && git pull
# Run any new migrations
ls db/migrations/*.sql                # apply manually if new file appears
# Local CI gate
bash scripts/run_ci.sh
# Refresh generated runtime URLs if Docker network membership changed
/home/azim/shared/scripts/generate_runtime_services_env.sh
# Promote
git checkout main && git merge develop && git push
sudo systemctl restart fazle-core.service
sleep 4 && curl -s http://127.0.0.1:8200/health | jq
```

## Database

- Postgres 15 via Docker Compose (`ai-call-platform/ai-infra/docker-compose.yaml`).
- Live `DATABASE_URL`, `REDIS_URL`, and `OLLAMA_URL` values come from
  `/home/azim/secure-env-backup/runtime-services.env`, not from hand-edited
  bridge IPs in `.env`.
- Manual migration: `psql "$DATABASE_URL" -f db/migrations/00X_*.sql`.
- Backup ad-hoc: `curl -X POST -H "X-Internal-Key: $KEY" http://127.0.0.1:8200/backup/run`.
- Snapshots land in `/home/azim/backups/` (rotated by B18 scheduler job).

## Monitoring

### Prometheus scrape (loopback)

`/metrics` is intentionally unauthenticated — bind is `127.0.0.1` so only
local processes can scrape. Sample scrape config:

```yaml
scrape_configs:
  - job_name: fazle-core
    static_configs:
      - targets: ["127.0.0.1:8200"]
```

### Quick dashboard pulse

```bash
KEY=$(grep ^INTERNAL_API_KEY= /home/azim/core/.env | cut -d= -f2-)
curl -s -H "X-Internal-Key: $KEY" http://127.0.0.1:8200/observability/summary | jq
curl -s -H "X-Internal-Key: $KEY" http://127.0.0.1:8200/observability/errors?limit=20 | jq
```

### Metrics worth watching

| Metric | Concern |
|---|---|
| `fazle_uptime_seconds` | Recent restart? |
| `fazle_http_requests_total{status="5xx"}` | Server errors |
| `fazle_http_request_duration_ms` p95 | Latency drift |
| `fazle_outbound_queue_depth` | Bridge backpressure |
| `fazle_scheduler_job_failures_total` | Cron health |
| `errors_24h` (from `/observability/summary`) | Error log spikes |

## Common tasks

### Mint a per-admin API key

```bash
curl -s -X POST -H "X-Internal-Key: $KEY" \
  http://127.0.0.1:8200/admin/users/8801999000111/apikey | jq
# response → { "api_key": "fk_…" } — give to that admin only
```

### Toggle SAFE MODE

Edit `.env`, set `AUTO_REPLY_ENABLED=true|false`, restart service. Live
flag visible at `GET /admin/safe-mode`.

### Bulk-reject safe-mode draft backlog

When `AUTO_REPLY_ENABLED=false` and a large pending-draft backlog accumulates
that is no longer actionable, reject all at once (no messages sent):

```sql
UPDATE fazle_draft_replies
SET status = 'rejected',
    reviewed = true,
    error_text = 'Bulk rejected by admin on YYYY-MM-DD (safe-mode backlog cleanup)',
    edited_at = NOW()
WHERE status IN ('pending', 'pending_selfie');
```

All rows get an audit note. Confirm with `SELECT status, COUNT(*) FROM fazle_draft_replies GROUP BY status;`

### Fix missing payment_method on imported transactions

When transactions are imported without a `payment_method`, apply inference rules
based on `remarks` and `payment_mobile` columns:

```sql
-- 1. Fix blank transaction_type
UPDATE wbom_cash_transactions SET transaction_type = 'Payment'
WHERE transaction_type = '' OR transaction_type IS NULL;

-- 2. Nagad hint in remarks
UPDATE wbom_cash_transactions
SET payment_method = 'Nagad',
    correction_note = correction_note || ' [pm inferred from remarks]'
WHERE (payment_method = '' OR payment_method IS NULL)
  AND (remarks ILIKE '%(N)%' OR remarks ILIKE '%nagod%' OR remarks ILIKE '%nagad%');

-- 3. Bkash hint in remarks
UPDATE wbom_cash_transactions
SET payment_method = 'Bkash',
    correction_note = correction_note || ' [pm inferred from remarks]'
WHERE (payment_method = '' OR payment_method IS NULL)
  AND (remarks ILIKE '%(B)%' OR remarks ILIKE '%bkash%');

-- 4. payment_mobile set → Bkash (most common mobile payment)
UPDATE wbom_cash_transactions
SET payment_method = 'Bkash',
    correction_note = correction_note || ' [pm inferred from payment_mobile]'
WHERE (payment_method = '' OR payment_method IS NULL)
  AND payment_mobile IS NOT NULL AND payment_mobile != '';

-- 5. Remaining → Cash fallback
UPDATE wbom_cash_transactions
SET payment_method = 'Cash',
    correction_note = correction_note || ' [pm defaulted to Cash]'
WHERE (payment_method = '' OR payment_method IS NULL);
```

Verify: `SELECT payment_method, COUNT(*) FROM wbom_cash_transactions GROUP BY 1 ORDER BY 2 DESC;`

### Seed today's attendance (all-present baseline)

```sql
INSERT INTO wbom_attendance (employee_id, attendance_date, status, recorded_by)
SELECT employee_id, CURRENT_DATE, 'Present', 'admin_bulk'
FROM wbom_employees
ON CONFLICT (employee_id, attendance_date) DO NOTHING;
```

Then mark absent employees individually via dashboard or:

```sql
UPDATE wbom_attendance SET status = 'Absent', remarks = 'reason'
WHERE employee_id = <id> AND attendance_date = CURRENT_DATE;
```

### Toggle Recruitment auto-reply gate

Recruitment messages bypass SAFE MODE when `RECRUITMENT_AUTOREPLY_ENABLED=true`.
This applies to all 3 channels (Meta webhook + Bridge1 + Bridge2 pollers).

```bash
# In /home/azim/core/.env:
RECRUITMENT_AUTOREPLY_ENABLED=true   # enable on all channels
RECRUITMENT_AUTOREPLY_ENABLED=false  # disable (full safe mode)
sudo systemctl restart fazle-core.service
```

### Reindex RAG after KB edits

```bash
curl -s -X POST -H "X-Internal-Key: $KEY" http://127.0.0.1:8200/rag/reindex | jq
curl -s -H "X-Internal-Key: $KEY" http://127.0.0.1:8200/rag/stats | jq
```

### Trigger backup / scheduler job manually

```bash
curl -s -X POST -H "X-Internal-Key: $KEY" http://127.0.0.1:8200/backup/run | jq
curl -s -X POST -H "X-Internal-Key: $KEY" http://127.0.0.1:8200/scheduler/run/outbound_drain | jq
```

## Troubleshooting

### Service won't start
1. `sudo journalctl -u fazle-core -n 80` — usually a missing env var or DB down.
2. `pg_isready -h 127.0.0.1 -p 5432` — confirm DB.
3. `/home/azim/core/venv/bin/python -c "from app.main import app"` — import smoke.

### `/health` 503
- DB ping failed. Check `/home/azim/secure-env-backup/runtime-services.env`,
  then verify `ai-postgres` and rerun
  `/home/azim/shared/scripts/generate_runtime_services_env.sh`.

### Drafts not delivering
- Check `AUTO_REPLY_ENABLED` — `false` blocks sends except admin approvals and recruitment gate.
- Check `RECRUITMENT_AUTOREPLY_ENABLED` — must be `true` for recruitment bypass.
- `GET /scheduler/status` — confirm `outbound_drain` is running.
- Check `/observability/errors` for bridge timeouts.

### Bridges silent
- Bridge1 (HR, :8082): `curl http://127.0.0.1:8082/health`
- Bridge2 (OPS, :8081): `curl http://127.0.0.1:8081/health`
- Both must be QR-authed; check WhatsApp Linked Devices.
- Bridge poller cursor lag is **normal** when only group messages received — cursor advances only on individual DMs.

### Rolling back
```bash
git -C /home/azim/core log --oneline -5
git -C /home/azim/core checkout <good-sha>
sudo systemctl daemon-reload
sudo systemctl restart fazle-core.service
```

## Tests

- Offline (no services): `venv/bin/python scripts/test_batch22_observability.py`
- Live (needs running service + DB): `bash scripts/run_ci.sh`
- Per-batch suites: `scripts/test_batch{11..22}*.py`
