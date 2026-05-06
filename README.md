# Fazle Core — WhatsApp AI Operations Engine

**Version:** v1.0.2 (B11 → B24 + B25 hotfix + 2026-05-06 ops) · **Status:** live
· **Repo path:** `/home/azim/core` · **README path:** `/home/azim/core/README.md`

> **2026-05-06 ops patch:**
> - Bulk-rejected 415 safe-mode backlog drafts (pending → rejected, no messages sent)
> - Fixed 573 transactions missing `payment_method` / `transaction_type` via inference rules
>   (remarks hints `(N)/(B)`, `payment_mobile` presence, Cash fallback; all rows stamped with audit note)
> - Bridge2 poller lag confirmed non-issue (group-chat messages filtered; cursor at correct last individual DM)
> - Recruitment auto-reply confirmed live on all 3 channels (Meta, Bridge1, Bridge2)
>
> **v1.0.1 hotfix (Batch 25):** Draft Quality Gate, in-process admin command dedup,
> multi-ID approve/reject (`APPROVE 165 162` or `APPROVE ১৬৫`), softer LLM fallback,
> admin help on unknown command. Env kill-switch: `DRAFT_QUALITY_GATE=false`.
> See [docs/ROADMAP.md](docs/ROADMAP.md) for full changelog.

A production FastAPI backend running on VPS that bridges WhatsApp conversations into structured business workflows for HR, Payroll, and Escort Operations.

Runtime infra note: Docker-backed URLs are now generated from stable
container names into `/home/azim/secure-env-backup/runtime-services.env`
before service start, instead of being hand-pinned to bridge IPs in `.env`.

## Documentation

| Doc | Purpose |
|---|---|
| [docs/V1_LAUNCH_CHECKLIST.md](docs/V1_LAUNCH_CHECKLIST.md) | **Tick before flipping `AUTO_REPLY_ENABLED=true`** — security, backup, daily routine, owner dashboard, monetization |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System diagram, components, data flow, modules |
| [docs/WORKSPACE_REVIEW_2026-04-29.md](docs/WORKSPACE_REVIEW_2026-04-29.md) | Read-only workspace review covering performance, workflow, media, attendance, escort, and payments |
| [docs/WORKSPACE_IMPLEMENTATION_PLAN_2026-04-29.md](docs/WORKSPACE_IMPLEMENTATION_PLAN_2026-04-29.md) | Prioritized implementation plan derived from the workspace review |
| [docs/WORKSPACE_P0_EXECUTION_BACKLOG_2026-04-29.md](docs/WORKSPACE_P0_EXECUTION_BACKLOG_2026-04-29.md) | Concrete execution backlog for the `P0` implementation sequence |
| [docs/DASHBOARD_URL_SPEC.md](docs/DASHBOARD_URL_SPEC.md) | Concrete `/dashboard/*` page map and chosen frontend direction |
| [docs/DASHBOARD_IMPLEMENTATION_BACKLOG.md](docs/DASHBOARD_IMPLEMENTATION_BACKLOG.md) | Ordered delivery backlog for dashboard pages and foundation work |
| [docs/API.md](docs/API.md) | Every HTTP endpoint with auth + examples |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Deploy, restart, backup, monitor, troubleshoot |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Versioning model, batch ledger B11 → B24, candidate batches B25 → B34 |

## Overview

Fazle Core processes inbound WhatsApp messages from two bridges, classifies intent using a local LLM (Ollama/qwen2.5), and routes them into the appropriate workflow:

- **Escort Operations** — Slip extraction, payment draft creation, admin approval
- **HR / Recruitment** — Candidate tracking, duty records, payroll drafts
- **Admin Commands** — APPROVE / REJECT / EDIT / PAID / ADVANCE / STATUS via WhatsApp

## Architecture

```
WhatsApp → Bridge1 (HR, :8080)   ─┐
WhatsApp → Bridge2 (OPS, :8081)  ─┤→ fazle-core (:8200) → PostgreSQL
WhatsApp → Meta Webhook           ─┘         ↓
                                         Ollama (LLM)
```

## Key Features

- **SAFE MODE**: `AUTO_REPLY_ENABLED=false` — suppresses outbound messages for safe testing
- **Recruitment Gate**: `RECRUITMENT_AUTOREPLY_ENABLED=true` — bypasses safe mode for recruitment triggers on all 3 channels
- **Dual Bridge Poller**: polls both SQLite bridge DBs every 5s
- **Intent Classification**: local LLM classifies every message before routing
- **Admin Approval Loop**: drafts queued → admin approves via WhatsApp → sent
- **Knowledge Base**: 277+ docs (161 file + 116 KB) indexed with BM25 RAG

## Modules

| Module | Purpose |
|---|---|
| `bridge_poller` | Polls bridge1/bridge2 SQLite, routes messages |
| `message_router` | Central routing and admin command detection |
| `admin_commands` | APPROVE/REJECT/EDIT/PAID/ADVANCE/STATUS |
| `escort` | Escort slip parsing and payment draft creation |
| `recruitment` | Candidate workflow and duty tracking |
| `payment_workflow` | Payment finalization and accountant notification |
| `knowledge_base` | Company rules and policy lookup |
| `intent` | LLM-based message intent classification |
| `ollama` | Ollama API client with health check |

## Stack

- **Runtime**: Python 3.11, FastAPI 0.115.5, uvicorn 0.32.1 (uvloop)
- **DB**: PostgreSQL 17 (asyncpg 0.30.0), SQLite (bridge stores)
- **LLM**: Ollama, model: `qwen2.5:1.5b`
- **Bridges**: WhatsApp bridge (Go binary) × 2 + Meta Cloud API webhook
- **Scheduler**: APScheduler 3.11.2, 10 jobs, timezone Asia/Dhaka
- **Infra**: Docker (Ollama, PostgreSQL, Redis), systemd services

## Running

```bash
# Production (systemd)
sudo systemctl status fazle-core.service

# Regenerate Docker-backed runtime URLs manually when needed
/home/azim/shared/scripts/generate_runtime_services_env.sh

# Health check
curl http://localhost:8200/health

# Logs
tail -f /home/azim/core/logs/fazle-core.log
```

## Environment

See `.env.example` for required variables. Never commit `.env`.

## Branch Strategy

- `main` — production stable
- `develop` — active sprint work
- `hotfix/*` — emergency fixes
- `feature/*` — optional modules

## Safe Deployment

```bash
# Work on develop
git checkout develop
# ... changes ...
git commit -m "fix: description"

# Deploy to production
git checkout main
git merge develop
sudo systemctl restart fazle-core.service
```

## Versioning

Fazle Core ships as **immutable versions**. v1.0 is frozen for daily
use. Future features (B25 alerting, B26 multi-tenant, custom batches…)
are built in a **clone** of this folder on a different port, tested in
isolation, then promoted via the launch checklist:

```
/home/azim/core            ← live (v1.0)
/home/azim/core-v2-dev     ← work-in-progress copy on port 8201
/home/azim/core-v1-archive ← previous version, kept 30 days
```

Full workflow + bump rules: [docs/ROADMAP.md](docs/ROADMAP.md#versioning-model).

## Launching v1

1. Open [docs/V1_LAUNCH_CHECKLIST.md](docs/V1_LAUNCH_CHECKLIST.md).
2. Tick every box top-to-bottom (pre-flight → security → backup →
   daily routine → dashboard → monetization).
3. Flip `AUTO_REPLY_ENABLED=true` in `.env`, restart the service, tag
   `git tag -a v1.0`.
4. Watch `/observability/summary` and `journalctl -u fazle-core -f`
   for the first 48 hours.
