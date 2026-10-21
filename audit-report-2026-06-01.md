# Fazle Core — Full System Audit Report

> **Pre-unification schema note.** Table names in this document refer to the
> pre-unification schema. See `audits/prefix_unification_2026-10-21.md` for the
> current table names.
**Date:** 2026-06-01  
**Auditor:** Claude Code (Senior System Auditor / Read-Only Mode)  
**Scope:** Full VPS ecosystem — all apps, modules, services, routes, dependencies  
**Mode:** STRICTLY READ-ONLY. No files modified. No services restarted. No commands executed except read/inspect.

---

> ### Update Notice — 2026-06-04 (Rev 2)
>
> Since this audit was completed the following changes have been made:
>
> | Change | Detail |
> |---|---|
> | `iamazim.com` — DUPLICATE BUG FIXED | Full Al-Aqsa Security Service company website deployed as static site at `/var/www/iamazim.com/`. Nginx config rewritten to serve static files. `/api/fazle/` still proxied to fazle-core. |
> | New website files | `index.html` (full company site), `legal/privacy.html`, `legal/terms.html`, `legal/contact.html` staged at `/home/azim/iamazim-web/` |
> | 3 new modules documented | `social_auto_reply` (active), `recruitment_ai` (active), `conversation_layer` (shadow-test only) — were present but not in previous audit inventory |
> | Session 2 cleanup (2026-06-01/02) | `employee_utils` + `csv_import` → `archive/deprecated/`; orphan dirs `modules/media/`, `modules/reply/`, `modules/recruitment/` deleted; `payment_correction` marked DORMANT |
> | `context_memory`, `gap_detector`, `gap_actions` | Confirmed archived to `archive/deprecated/` — NOT production code |
> | `modules/payroll/` + `modules/payroll_logic/` | **CONFIRMED ACTIVE** — `payroll` has lazy imports in `admin_commands`, `scheduler`, `app/main.py`; `payroll_logic` directly imported by `message_router` |
> | New dead modules confirmed (2026-06-04 grep) | `media_normalization` (0 callers), `contact_sync` (0 callers), `payment` re-export stub (0 callers) — safe to archive |
> | `message_archive` | Recovery scripts only (`recover_from_backup.py`, `recover_critical_numbers.py`) — not in runtime call chain |
> | `image_hash` | Confirmed ACTIVE — `ocr_processor` imports `check_and_register` |
> | `reply_templates` | Shadow-only — only called from `conversation_layer/recruitment.py` (itself shadow-only) |
> | **Current health (2026-06-04)** | `bridge1_db/bridge2_db` mtime ~18 min (was 2.8h+); available RAM 15.6GB (was ~5GB); disk 47% / 108.8GB free; Ollama now has `qwen3:8b` in addition to existing models |
>
> See `FAZLE_CORE_CONSOLIDATION_PLAN.md` Section F for full updated module inventory.

---

## 1. Executive Summary

**Fazle Core** is a production AI-powered WhatsApp business management system for **Al-Aqsa Security and Logistics Services Limited** (Chittagong, Bangladesh). It manages:

- Inbound WhatsApp DM routing and AI reply generation
- Escort worker lifecycle (assignment, completion, payment)
- Recruitment funnel automation (Bengali-language candidates)
- Payroll management and admin draft approval workflow
- Attendance tracking and supervisor communications
- Payment ingest and finalization from SMS/accountant

**Health at audit time:** ✅ All critical systems healthy.

```
{"status":"ok", "db":"ok", "bridge1_db":"ok", "bridge2_db":"ok",
 "bridge_poller_b1":"ok", "bridge_poller_b2":"ok",
 "outbound":"ok (pending=0, dlq=0)",
 "disk":"ok (43% used, 117GB free)",
 "mem":"ok (4897MB available)",
 "ollama":"ok (qwen2.5:3b active, qwen3:14b available)"}
```

**Key stats:**
- 51 Python modules in `/modules/` (50+ `__init__.py` files)
- 2,059 lines in `app/main.py`
- 1,302 lines in `bridge_poller`
- 1,329 lines in `admin_commands`
- 863 lines in `escort`
- 3 active WhatsApp bridges (bridge1, bridge2, bridge3)
- 14 Docker containers running
- 5 distinct VPS processes related to this ecosystem

---

## 2. Production Architecture Overview

```
EXTERNAL INBOUND PATHS
═══════════════════════════════════════════════════════════
                                                          
  [Meta WhatsApp API]  ─────────────────────────────────►  fazle.iamazim.com/webhook/meta
  [Bridge1 SQLite]     ─── bridge_poller (async poll) ──►  /whatsapp1/store/messages.db
  [Bridge2 SQLite]     ─── bridge_poller (async poll) ──►  /whatsapp2/store/messages.db
  [Bridge3 Loop]       ─── run_bridge3_loop.sh ──────────►  /bridges/bridge3/ (separate)
                                                          
NGINX (SSL termination + rate limiting)
═══════════════════════════════════════════════════════════
  iamazim.com          ──► /var/www/iamazim.com/ (Al-Aqsa company website — FIXED 2026-06-04)
  api.iamazim.com      ──► 127.0.0.1:8200  (Fazle Core FastAPI)
  fazle.iamazim.com    ──► 127.0.0.1:8200  (Fazle Core FastAPI)
  chat.iamazim.com     ──► 172.22.0.2:8080 (Open WebUI / Docker)
  locationwhere.iamazim.com ── /home/azim/locationwhere-frontend/ + Node.js 8310
  vscode.iamazim.com   ──► 127.0.0.1:8443  (code-server / Docker)

FAZLE CORE APP (port 8200, systemd: fazle-core.service)
═══════════════════════════════════════════════════════════
  run.py
    └── uvicorn → app/main.py:app (FastAPI)
          ├── /webhook/meta  → process_message()
          ├── /bridge1/send  → bridge1 outbound
          ├── /bridge2/send  → bridge2 outbound
          ├── /api/fpe/*     → fazle_payroll_engine.routes
          ├── /api/escort-roster/* → escort_roster.routes
          ├── /api/employees/* → admin_employees.routes
          ├── /api/transactions/* → admin_transactions.routes
          ├── /api/social/*  → social_auto_reply.routes
          ├── /admin/chat    → Ollama AI chat
          ├── /payroll       → payroll dashboard SPA
          └── /health        → health probe

MESSAGE PROCESSING PIPELINE
═══════════════════════════════════════════════════════════
  Inbound Message
    │
    ├── bridge_poller (bridge1/bridge2 path)
    │     ├── OCR (images) → ocr_processor
    │     ├── STT (audio)  → voice_processor
    │     ├── identity_brain.detect_identity()
    │     ├── social_auto_reply.ingest_social_event() [if SINGLE_ENGINE=true]
    │     └── process_message() → [reply, admin_note]
    │
    └── app/main.py webhook (Meta API path)
          └── process_message() → [reply, admin_note]
                │
                └── modules/message_router/
                      ├── 1. identity_brain → role detection
                      ├── 2. family → hardcoded reply
                      ├── 3. escort_client → escort flow
                      ├── 4. admin → admin_commands
                      ├── 5. attendance → attendance_parser
                      ├── 6. intent.classify() → LLM fallback
                      ├── 7. accountant → payment_ingest
                      ├── 8. candidate/recruitment → recruitment_ai
                      ├── 9. employee → verification / payroll / lifecycle
                      ├── 10. escort order intent → escort flow
                      ├── 11. advance request → employee_verification
                      ├── 12. office_location → knowledge_base (fast path)
                      ├── 13. knowledge_base.get_reply()
                      ├── 14. reviewed_reply_memory (admin-approved)
                      └── 15. ollama.generate_reply() (AI fallback)

OUTBOUND PATHS
═══════════════════════════════════════════════════════════
  reply_text → bridge_poller safety checks:
    ├── advance_request phrase guard → DRAFT
    ├── financial intent gate → DRAFT
    ├── complaint phrase guard → DRAFT
    ├── draft_always phone/role/name → DRAFT
    ├── loop detection → DRAFT
    ├── outbound poison filter → DRAFT + admin alert
    ├── length/structure guard → DRAFT
    ├── AI_SAFE_MODE checks → DRAFT
    └── bridge.send(phone, reply) → WhatsApp delivery
```

---

## 3. Entry Points & Service Map

| Service | Entry Point | Port | Runtime | Status |
|---|---|---|---|---|
| fazle-core | `run.py → uvicorn app/main.py:app` | 8200 | systemd | ✅ RUNNING (41.9% CPU) |
| social_auto_reply | `modules/social_auto_reply/service_runner.py` | — | direct python | ✅ RUNNING |
| facebook_supervisor_agent | `/home/azim/facebook_supervisor_agent/service_runtime.py` | — | direct python | ✅ RUNNING |
| system-agent | `/home/azim/system-agent/uvicorn system_agent.main:app` | 8300 | direct python | ✅ RUNNING |
| media-processor | `/home/azim/shared/media/media-processor/server.py` | — | direct python | ✅ RUNNING (6.6% CPU) |
| whatsapp-bridge1 | `/home/azim/whatsapp-mcp/whatsapp-bridge/whatsapp-bridge` | — | Go binary | ✅ RUNNING |
| whatsapp-bridge2 | same binary, 2nd instance | — | Go binary | ✅ RUNNING |
| whatsapp-bridge3 | `bridges/bridge3/run_bridge3_loop.sh` | — | bash loop | ✅ RUNNING |
| open-webui | Docker (ghcr.io/open-webui/open-webui) | 8501→8080 | Docker | ✅ RUNNING |
| ollama | Docker (ollama/ollama:latest) | 11434 | Docker | ✅ RUNNING |
| ai-postgres | Docker (pgvector/pgvector:pg17) | 5432 | Docker | ✅ RUNNING |
| ai-redis | Docker (redis:8.0.2-alpine) | 6379 | Docker | ✅ RUNNING |
| qdrant | Docker (qdrant/qdrant:v1.17.0) | 6333-6334 | Docker | ✅ RUNNING |
| minio | Docker (minio/minio) | 9000 | Docker | ✅ RUNNING |
| grafana | Docker (grafana/grafana:11.4.0) | 3000/3030 | Docker | ✅ RUNNING |
| prometheus | Docker (prom/prometheus) | 9090 | Docker | ✅ RUNNING |
| loki | Docker (grafana/loki) | 3100 | Docker | ✅ RUNNING |
| promtail | Docker (grafana/promtail) | — | Docker | ✅ RUNNING |
| cadvisor | Docker (gcr.io/cadvisor) | 8080 | Docker | ✅ RUNNING |
| node-exporter | Docker + native | 9100 | Docker + native | ✅ RUNNING |
| otel-collector | Docker (otel/opentelemetry-collector-contrib) | 4317-4318 | Docker | ✅ RUNNING |
| code-server | Docker (codercom/code-server) | 8443→8080 | Docker | ✅ RUNNING |

**External recruitment agent** (separate systemd service):
- Service: `fazle-recruitment-agent.service`
- Entry: `/home/azim/external_recruitment_agent/agent.py --mode live --send`
- Status: NOT confirmed running (not in ps output at audit time — may be stopped)

---

## 4. Active Modules

Modules confirmed active (imported in production call chain from `main.py` or `bridge_poller`):

| Module | Lines | Purpose | Imported By |
|---|---|---|---|
| `message_router` | 557 | Central routing hub — all message routing logic | main.py, bridge_poller |
| `bridge_poller` | 1,302 | SQLite poll loop for bridge1+bridge2 DMs | main.py (start_pollers) |
| `admin_commands` | 1,329 | Parse/execute admin commands (APPROVE/REJECT/PAID etc) | message_router, main.py |
| `escort` | 863 | Escort client flow, completion detection, draft creation | message_router, bridge_poller |
| `escort_lifecycle` | 638 | Release slips, lifecycle events, OCR release | message_router, bridge_poller, main.py |
| `escort_roster` | multi-file | Roster management + FastAPI routes | main.py (router) |
| `escort_slip_extractor` | — | Extract vessel/escort data from text | main.py |
| `fazle_payroll_engine` | multi-file | Payroll engine + FastAPI routes + lifecycle | main.py (router + start/stop) |
| `payment_workflow` | 340 | Create payment drafts, advance requests, finalize | main.py, message_router |
| `payment_ingest` | 433 | Parse accountant SMS, cash shorthand, match employees | message_router, main.py |
| `payment_correction` | 289 | Payment correction audit log | (via payment chain) |
| `payment` | 22 | Thin re-export stub for payment_workflow | (backwards compat layer) |
| `recruitment_ai` | 206 | Generate AI recruitment replies via Ollama | message_router, bridge_poller |
| `recruitment_flow` | 291 | Session tracking, trigger detection, funnel state | message_router, bridge_poller, main.py |
| `identity_brain` | 298 | Detect sender role, confidence, display name | message_router, bridge_poller |
| `intent` | 171 | Keyword-based intent classification (fast path) | message_router, bridge_poller, main.py |
| `knowledge_base` | 309 | KB reply lookup from `fazle_knowledge_base` table | message_router |
| `accountant_summary` | 157 | Detect and ack daily accounting summaries | message_router (lazy) |
| `attendance` | 244 | Handle attendance messages, summaries | message_router |
| `attendance_parser` | 281 | Parse structured attendance reports | message_router |
| `admin_employees` | 390 | FastAPI CRUD routes for employee management | main.py (router) |
| `admin_transactions` | 550 | FastAPI CRUD routes for cash transactions | main.py (router) |
| `employee_verification` | 376 | Verification sessions (slip/advance/mismatch) | message_router |
| `draft_quality` | 84 | Quality gate — blocks garbage LLM replies from drafts | bridge_poller, main.py |
| `outbound` | 215 | Outbound message queue management | 11 files |
| `observability` | 156 | Metrics counters, increment helpers | 14 files |
| `scheduler` | 551 | Cron-like scheduler (payroll, backup, digest) | 6 files |
| `backup` | 288 | pg_dump + rotation via Docker | scheduler (36 importers) |
| `social_auto_reply` | 225 | Social event ingest + auto-reply daemon | main.py, bridge_poller |
| `payroll` | — | Payroll compute/approve/lock | main.py (lazy) |
| `payroll_logic` | — | Payroll context formatting | message_router |
| `rbac` | 340 | Role-based access control | 11 files |
| `user_role` | 256 | Phone normalization, role utilities | 3 files |
| `number_identity` | 107 | Phone number normalization helpers | 5 files |
| `rag` | 389 | RAG pipeline (vector + semantic search) | 4 files |
| `reviewed_reply_memory` | 365 | Admin-approved reply lookup (memory system) | message_router |
| `ocr_processor` | — | Image OCR (slip detection) | bridge_poller (lazy) |
| `voice_processor` | — | Audio transcription (STT) | bridge_poller (lazy) |
| `media_normalization` | — | Media file normalization | — |
| `draft_quality` | 84 | Quality gate for outbound reply text | bridge_poller, main.py |

---

## 5. Inactive / Potentially Unused Modules

| Module | Lines | Importers | Assessment |
|---|---|---|---|
| `employee_utils` | 102 | **0** | ❌ Dead code — `get_or_create_employee()` defined but nothing imports it |
| `gap_detector` | 480 | **0** | ❌ Dead code — FPE gap detection, no active callers |
| `csv_import` | 292 | **0** | ❌ Dead code — CSV employee import, no active callers |
| `context_memory` | 105 | 1 | ⚠️ Near-dead — only 1 importer, likely experimental |
| `gap_actions` | 280 | 1 | ⚠️ Near-dead — gap remediation actions, 1 importer |
| `image_hash` | — | — | ⚠️ Unverified — need caller check |
| `contact_sync` | — | — | ⚠️ Unverified — sync logic |
| `conversation_layer` | — | — | ⚠️ Unverified — possible legacy layer |
| `message_archive` | — | — | ⚠️ Unverified — archival system |
| `reply_templates` | — | — | ⚠️ Unverified — template system |
| `reports` | — | — | ⚠️ Unverified — reporting module |

**Orphan directories (no `__init__.py`):**
| Path | Status |
|---|---|
| `modules/media/` | Orphan directory — no Python package |
| `modules/reply/` | Orphan directory — no Python package |
| `modules/recruitment/` | Orphan directory — no Python package |

---

## 6. Duplicate & Overlapping Systems

### 6a. Intent Detection (Two-Layer System — BOTH ACTIVE, COMPLEMENTARY)

| System | Type | File | Trigger |
|---|---|---|---|
| `modules/fazle_intent.classify()` | Keyword/rule-based (fast) | `modules/intent/__init__.py` | Every message, first pass |
| `app.ollama.classify_intent_llm()` | LLM-based (slow, accurate) | `app/ollama.py` | Fallback when intent == "unknown" |

**Assessment:** These are complementary, not conflicting. Fast path → LLM fallback is intentional design. ✅

### 6b. Recruitment Systems (THREE LAYERS)

| Layer | Location | Status | Scope |
|---|---|---|---|
| `modules/recruitment_flow` + `modules/recruitment_ai` | Core app | ✅ ACTIVE | Inbound bridge/Meta WhatsApp DMs |
| `external_recruitment_agent/agent.py` | `/home/azim/external_recruitment_agent/` | ⚠️ SEPARATE SERVICE (not in ps at audit time) | Outbound recruitment automation |
| `/home/azim/external_recruitment_bot_v2/` | `/home/azim/external_recruitment_bot_v2/` | ❓ UNKNOWN | Possibly legacy |
| `/home/azim/external_recruitment_bot_v3/` | `/home/azim/external_recruitment_bot_v3/` | ❓ UNKNOWN | Possibly latest version |
| `modules/recruitment/` directory | `modules/recruitment/` (no `__init__.py`) | ❌ ORPHAN | Not a Python package |

**Risk:** Multiple recruitment bots (v2, v3, external_agent) may be targeting the same candidate population. Unclear if they coordinate or conflict.

### 6c. Phone Normalization (Potential Overlap)

| Module | Function | Users |
|---|---|---|
| `modules/user_role` | `normalize_phone()` | 3 files |
| `modules/number_identity` | normalization helpers | 5 files |
| `message_router._phone_variants()` | inline normalization | local only |

**Assessment:** Minor overlap. `user_role.normalize_phone` is likely canonical. `number_identity` may be a refactored version. No conflict but could be consolidated.

### 6d. Social Auto-Reply (Dual Execution Path — NEEDS ATTENTION)

`social_auto_reply` is both:
1. Imported and called from `bridge_poller` (line 831-845) when `SOCIAL_AUTO_REPLY_SINGLE_ENGINE=true`
2. Running as a **separate standalone process** via `service_runner.py`

When `SOCIAL_AUTO_REPLY_SINGLE_ENGINE=true` (current default), bridge_poller delegates to the social daemon and skips its own reply logic — this is intentional. But the **standalone process also runs independently**. These must coordinate correctly or double-processing occurs.

### 6e. Payment Import Paths (Split — NEEDS CLEANUP)

`modules/payment/__init__.py` is a re-export stub for `payment_workflow`, but:
- `app/main.py:35` imports `payment_workflow` directly
- `message_router:47` imports `payment_workflow` directly  
- `message_router:267` imports `payment_ingest` directly
- `app/main.py:1195` imports `payment_ingest` directly

**Assessment:** The `modules/payment` re-export layer is incomplete — callers bypass it. This is exactly the consolidation target for Phase 2 of the planned refactoring.

---

## 7. Message Processing Flow (Full Lifecycle)

```
INBOUND MESSAGE (DM via Bridge1 or Bridge2)
│
▼
bridge_poller._fetch_new_messages() [SQLite, read-only, thread pool]
│   ├─ LID → phone resolution (whatsapp.db lid_map)
│   ├─ Group/newsletter/status filtering (SQL-level)
│   ├─ Text extraction (content or processed_text)
│   └─ Timestamp parsing + cursor advance
│
▼
Dedup check: processed_bridge_messages (PostgreSQL)
│   └─ Already processed? SKIP
│
▼
Media pipeline (if applicable):
│   ├─ image → ocr_processor.classify_from_context() → process_image()
│   │         └─ slip_type: release_slip → escort_lifecycle.handle_ocr_release_slip()
│   ├─ audio/ptt → voice_processor.process_voice() → transcript
│   └─ document/PDF → ocr_processor.process_document()
│
▼
identity_brain.detect_identity(phone, text)
│   → returns: role, display_name, identity_confidence, employee_id
│
▼
_save_message() → wbom_whatsapp_messages (PostgreSQL)
│
▼ [if phone starts with "unresolved:"] STOP (persist only, no routing)
│
▼
social_auto_reply.ingest_social_event() [if SOCIAL_AUTO_REPLY_SINGLE_ENGINE=true]
│   └─ Delegates to social daemon → bridge_poller skips legacy router/send
│
▼ [legacy path, only if SINGLE_ENGINE=false]
│
▼
Cooldown check: _last_reply dict (in-memory, per process)
│   └─ < 60s since last reply? SKIP
│
▼
Keyword flood check: _kw_flood_ts (in-memory)
│   └─ Same keyword > 3x in 5min? SUPPRESS
│
▼
Intent override: intent.classify(text)
│   └─ "unknown"/"greeting"? → check recruitment triggers
│
▼
Prompt injection detection: _PROMPT_INJECTION_PATTERNS
│   └─ Match? → QUARANTINE as draft
│
▼
message_router.process_message(phone, text, bridge_name)
│   ├─ _should_silent_skip() → accountant phone or "al-aqsa/escort/client" in name → NO REPLY
│   ├─ identity_brain.detect_identity() [re-runs with full context]
│   ├─ FAMILY role → hardcoded Bangla reply
│   ├─ ESCORT CLIENT role + escort content → escort.handle_escort_client_message()
│   ├─ ADMIN role:
│   │   ├─ is_completed_escort_draft() → escort.handle_admin_escort_completion()
│   │   ├─ is_admin_command() → admin_commands.process_admin_command()
│   │   ├─ is_nl_admin_query() → admin_commands.nl_router.process_nl_admin_query()
│   │   └─ unrecognized → inline help text
│   ├─ ATTENDANCE: attendance_parser → create_attendance_draft() + admin notification
│   ├─ Intent classification: intent.classify() → ollama.classify_intent_llm() if unknown
│   ├─ ACCOUNTANT role:
│   │   ├─ is_accountant_summary() → ack_accountant_summary()
│   │   ├─ is_advance_record_query() → nl_advance_record
│   │   ├─ looks_like_payment_sms() → payment_ingest.ingest_payment_sms()
│   │   ├─ is_admin_cash_shorthand() → payment_ingest.ingest_admin_cash_entry()
│   │   └─ fallback → knowledge_base → ollama.generate_reply()
│   ├─ CANDIDATE/recruitment intent → recruitment_ai.generate_recruitment_reply()
│   ├─ NEW_LEAD/UNKNOWN with active session or trigger → recruitment_ai
│   ├─ ESCORT ORDER intent → escort.handle_escort_client_message()
│   ├─ EMPLOYEE role → employee_verification / attendance / payroll / lifecycle
│   ├─ ADVANCE REQUEST (any role) → employee_verification.start_advance_verification()
│   ├─ OFFICE LOCATION → knowledge_base fast path (deterministic KB, no AI)
│   ├─ KNOWLEDGE BASE → kb.get_reply(text, intent)
│   ├─ REVIEWED REPLY → reviewed_reply_memory.lookup_reviewed_reply()
│   └─ AI FALLBACK → ollama.generate_reply(text, intent, db_ctx, role)
│
▼
reply_text, admin_note = process_message(...)
│
▼
Outbound safety firewall (bridge_poller):
│   ├─ advance_request phrase → DRAFT
│   ├─ financial intent + !safe_autosend → DRAFT
│   ├─ complaint phrase + financial → DRAFT
│   ├─ _is_draft_always(phone, role, name) → DRAFT
│   ├─ contact_risk = "admin_review_only" → DRAFT
│   ├─ loop detection (3 replies / 2 min) → DRAFT
│   ├─ poison content filter → DRAFT + DB incident + admin WhatsApp alert
│   ├─ length > 400 / markdown table / headings → DRAFT
│   ├─ AI_SAFE_MODE checks → DRAFT
│   └─ bridge.send(phone, reply) → WhatsApp ✅
│
▼
draft_quality.check_draft_quality(reply_text)
│   → rejected → fazle_draft_replies (status: rejected_quality)
│   → approved → fazle_draft_replies (status: pending)
│
▼
admin_note? → bridge.send(admin_phone, note) [admin notification]
```

---

## 8. Recruitment System Deep-Dive

### 8a. Core Recruitment Modules (inside fazle-core)

| File | Purpose | Status | Connected To |
|---|---|---|---|
| `modules/recruitment_flow/__init__.py` (291 lines) | Session tracking, `is_recruitment_trigger()`, `get_active_session()`, `intake_message()` | ✅ ACTIVE | message_router, bridge_poller, main.py |
| `modules/recruitment_ai/__init__.py` (206 lines) | `generate_recruitment_reply()`, `looks_like_recruitment_followup()` via Ollama | ✅ ACTIVE | message_router, bridge_poller |
| `modules/recruitment/` (dir) | No `__init__.py` — empty directory or orphan | ❌ ORPHAN | Nothing |
| `fazle_recruitment_sessions` (DB table) | Stores active candidate sessions with funnel stage | ✅ ACTIVE | recruitment_flow |

### 8b. External Recruitment Systems

| Location | Description | Status |
|---|---|---|
| `/home/azim/external_recruitment_agent/agent.py` | Standalone recruitment bot (`--mode live --send`) | ⚠️ Service defined, NOT seen in ps |
| `/home/azim/external_recruitment_bot_v2/` | Version 2 of external bot | ❓ UNKNOWN |
| `/home/azim/external_recruitment_bot_v3/` | Version 3 of external bot | ❓ UNKNOWN |
| `/home/azim/fazle-recruitment-agent.service` | systemd service file for external agent | Exists but not confirmed active |

### 8c. Recruitment Trigger Flow

```
Inbound message (unknown/new_lead/candidate role)
│
▼
bridge_poller: intent == "unknown"/"greeting"?
├── _is_recruit_trigger(text) → keyword match (job, কাজ, নিয়োগ, ভর্তি, চাকরি...)
├── _looks_like_recruit_followup(text) → contextual signals
└── _get_recruit_session(phone) → active session in DB?
│
▼ Any true → intent overridden to "recruitment"
│
▼
message_router → role == "candidate" OR intent == "recruitment"
│
▼
recruitment_ai.generate_recruitment_reply(phone, text, source, contact_context)
├── get_active_session(phone) → current funnel stage
├── ollama.generate_reply() with recruitment system prompt
├── intake_message() → update funnel stage
└── Return AI-generated Bangla recruitment reply
```

### 8d. Recruitment Funnel Stages

Stored in `fazle_recruitment_sessions` table. Funnel progresses through stages managed by `recruitment_flow.intake_message()`.

---

## 9. Intent Engine Analysis

| System | Type | Speed | Used When | Status |
|---|---|---|---|---|
| `modules/fazle_intent.classify(text)` | Keyword/regex (Bangla+English) | ~1ms | Every message, first pass | ✅ ACTIVE PRIMARY |
| `app.ollama.classify_intent_llm(text)` | LLM (qwen2.5:3b) | ~1-5s | Fallback when `intent == "unknown"` | ✅ ACTIVE FALLBACK |

**Intent categories handled by `modules/fazle_intent`:**
`recruitment`, `payment`, `salary`, `advance`, `attendance`, `leave`, `escort_duty`, `client_order`, `slip_submission`, `office_location`, `greeting`, `salary_query`, `payment_due`, `employee_salary_complaint`, `legal_issue`, `payment_issue`, `unknown`

**Conflict check:** No conflicts. Two-layer design is correct — fast keyword check first, LLM only for ambiguous messages.

**Safe auto-send intents** (bypass draft gate):
`recruitment`, `join`, `greeting`, `office_location`, `salary_query`, `payment_due`, `attendance`, `leave`, `escort_duty`

---

## 10. Employee Verification Flow

```
Any message with advance/slip intent
│
▼
identity_brain.detect_identity(phone, text)
├── wbom_contacts table lookup (by phone variants: 880xxx, 0xxx)
├── wbom_employees table lookup
├── rbac / user_role lookup
└── Returns: {role, display_name, identity_confidence, employee_id, identity_source}
│
▼
message_router routing by role:
│
├── role == "employee":
│   ├── get_verification_session(phone) → active session?
│   │   └── YES → advance_verification(phone, text, source, emp_id)
│   │             (collect: name → mobile → amount confirmation)
│   ├── intent == "slip_submission" → start_slip_verification()
│   ├── is_release_intent(text) → escort_lifecycle.handle_release_event()
│   └── is_advance_request(text) → start_advance_verification()
│
└── any role (not admin, not in session):
    └── is_advance_request(text) → start_advance_verification()
          └── employee_verification.start_advance_verification(phone, source, emp_id)
                ├── Creates verification session in DB
                └── Returns: multi-step confirmation prompt
│
▼
Employee found?
├── YES → payment_workflow.create_advance_request_draft()
│         └── Draft created in fazle_draft_replies → admin approval
└── NO → check_identity_mismatch(phone)
          └── Return mismatch notice
```

**Database tables in identity pipeline:**
- `wbom_contacts` — contact display name, phone, role
- `wbom_employees` — employee records, mobile, designation
- `fazle_admin_roles` — admin phone numbers
- `fazle_roles` — role definitions
- `fazle_unified_contacts` — unified contact view

---

## 11. Payment & Payroll Systems

### 11a. Payment Flow

```
Accountant sends SMS-style payment message via WhatsApp
│
▼
message_router: role == "accountant"
│   └── looks_like_payment_sms(text) → payment_ingest.ingest_payment_sms()
│         ├── regex parse: amount, mobile, method (bKash/Nagad/cash)
│         ├── rapidfuzz employee matching (wbom_employees)
│         ├── duplicate check (staging table)
│         └── finalize_payment() → payment_workflow
│               ├── auto_approved (high confidence) → direct insert
│               └── unmatched → pending staging entry
│
▼
Admin commands (PAID <id> <amount> <method>):
│   └── admin_commands.process_admin_command()
│         └── payment_workflow.finalize_payment()
│               └── fpe_cash_transactions insert
│                   + accountant notification (bridge)
```

### 11b. Payment Modules

| Module | Lines | Role | Status |
|---|---|---|---|
| `payment_workflow` | 340 | Core: draft creation, finalization, advance requests | ✅ ACTIVE |
| `payment_ingest` | 433 | SMS parse, employee match, cash shorthand | ✅ ACTIVE |
| `payment_correction` | 289 | Correction audit log | ✅ ACTIVE (via payment chain) |
| `payment` | 22 | Re-export stub (incomplete — bypassed by direct imports) | ⚠️ INCOMPLETE |

### 11c. Payroll Flow (FPE)

`fazle_payroll_engine` (FPE) handles full payroll lifecycle:
- Daily compute via `scheduler`
- FastAPI routes at `/api/fpe/*`
- Tables: `fpe_employees`, `fpe_cash_transactions`, `fpe_employee_ledger`, `fpe_gap_scan_runs`, etc.

---

## 12. Escort System

### 12a. Lifecycle Flow

```
Client sends escort order (vessel, lighter, destination)
│
▼
identity_brain: role == escort_client / intent == client_order
│
▼
escort.handle_escort_client_message(text, sender, source)
├── extract_escort_slip() → escort_slip_extractor
│   └── Parse: MV name, lighter, destination, date, quantity
├── create_escort_payment_draft() → payment_workflow
└── Admin notification via bridge2

Admin sends completed slip TO client (bridge2 outgoing)
│
▼
bridge_poller: _fetch_outgoing_escort_completions() [bridge2 only]
│   └── is_completed_escort_draft(text) → escort.handle_admin_escort_completion()
│         ├── Parse escort worker name + mobile from slip
│         ├── Save to escort_roster_entries
│         └── Trigger payment draft

Employee sends release text / OCR release slip
│
▼
escort_lifecycle.handle_release_event() / handle_ocr_release_slip()
├── Close active escort program
├── Compute day_count, payment amount
└── Create payment draft (fazle_draft_replies)
```

### 12b. Escort Database Tables

`escort_roster_entries`, `escort_order_groups`, `escort_order_lighters`, `escort_release_matches`, `escort_roster_audit_logs`, `escort_shift_logs`, `escort_slip_extractions`, `escort_calculation_config`

---

## 13. Admin / Accountant / Role System

### 13a. Role Hierarchy

| Role | Source | Routing |
|---|---|---|
| `admin` | ADMIN_NUMBERS env var | Admin commands → process_admin_command() |
| `accountant` | ACCOUNTANT_PHONE env var | Payment ingest → ingest_payment_sms() |
| `family` | identity_brain detection | Hardcoded personal reply, no business logic |
| `escort_client` / `client_escort_buyer` / `vip_client` / `repeat_client` | DB role lookup | Escort client flow |
| `candidate` | DB role or recruitment trigger | Recruitment funnel |
| `employee` | wbom_employees lookup | Verification / payroll / lifecycle |
| `supervisor` | DB role | Attendance parsing |
| `known_contact` | DB contacts table | KB → AI fallback |
| `unknown` / `new_lead` | No match | Intent → KB → AI |

### 13b. Admin Commands (modules/fazle_admin_commands — 1,329 lines)

| Command | Action |
|---|---|
| `APPROVE <id>` | Send pending draft reply |
| `APPROVE <id> <id>...` | Bulk approve |
| `REJECT <id>` | Cancel draft |
| `EDIT <id> <text>` | Edit then send |
| `PAID <id> <amount> <method>` | Record payment |
| `ADVANCE <id> <amount>` | Process advance |
| `ESCORTCONFIRM <...>` | Confirm escort assignment |
| `STATUS / DRAFTS` | Show pending list |
| Natural language queries | nl_router → nl_advance_record |

### 13c. Silent Skip Logic

Contacts named "al-aqsa", "escort", or "client" (case-insensitive) receive NO reply and NO draft — total silence. This protects internal staff numbers from auto-reply loops.

### 13d. Draft Always Logic

Contacts matching any of:
- `DRAFT_ALWAYS_PHONES` (env list)
- `DRAFT_ALWAYS_ROLES` (env list: accountant, vip_client, etc.)
- `DRAFT_ALWAYS_NAMES` (env list)
- `DRAFT_NAME_PREFIXES` (env list: "client", "escort", "office"...)

...are always routed to manual admin review regardless of intent.

---

## 14. AI / LLM Integration

| Component | Model | Purpose | Status |
|---|---|---|---|
| Ollama Docker container | qwen2.5:3b (active), qwen3:14b (available) | Primary LLM inference | ✅ RUNNING |
| `app/ollama.py` (257 lines) | qwen2.5:3b | `generate_reply()`, `classify_intent_llm()` | ✅ ACTIVE |
| `modules/rag` (389 lines) | Embedding + Qdrant | RAG pipeline for KB retrieval | ✅ ACTIVE (4 importers) |
| `modules/knowledge_base` (309 lines) | DB lookup + RAG | KB reply before AI fallback | ✅ ACTIVE |
| `modules/reviewed_reply_memory` (365 lines) | DB lookup | Admin-approved reply cache | ✅ ACTIVE |
| Open WebUI | chat.iamazim.com | Admin LLM chat UI | ✅ RUNNING |
| `/admin/chat` endpoint | qwen2.5:3b | Direct admin AI chat via Fazle Core | ✅ ACTIVE |

**Model routing:**
1. `intent.classify()` — no LLM (keyword only)
2. `generate_recruitment_reply()` — Ollama (recruitment-specific prompt)
3. `generate_reply()` — Ollama (general business context)
4. `classify_intent_llm()` — Ollama (fallback intent classification)

**External AI services NOT detected in current codebase:**
- No OpenAI API keys referenced
- No Claude (Anthropic) API in core app
- No local model files (piper-voices exists for TTS, separate)

---

## 15. URL, Domain & Subdomain Mapping

| Domain/Path | Nginx Target | Backend | App | Status |
|---|---|---|---|---|
| `iamazim.com` | 127.0.0.1:8200 | fazle-core | Fazle Core FastAPI | ✅ ACTIVE |
| `www.iamazim.com` | → iamazim.com redirect | — | redirect | ✅ ACTIVE |
| `fazle.iamazim.com` | 127.0.0.1:8200 | fazle-core | Fazle Core FastAPI | ✅ ACTIVE |
| `api.iamazim.com` | 127.0.0.1:8200 | fazle-core | Fazle Core FastAPI | ✅ ACTIVE |
| `chat.iamazim.com` | 172.22.0.2:8080 | open-webui (Docker) | AI Chat UI | ✅ ACTIVE |
| `vscode.iamazim.com` | 127.0.0.1:8443 | code-server (Docker) | VS Code Browser | ✅ ACTIVE |
| `iamazim.com/grafana/` | 127.0.0.1:3030 | Grafana (Docker) | Monitoring (LAN only) | ✅ ACTIVE (internal only) |
| `iamazim.com/legal/*` | /var/www/iamazim.com/legal/ | Static HTML | Legal pages | ✅ ACTIVE |
| `api.iamazim.com/api/wbom/` | 127.0.0.1:9900 | **DISABLED** | Old WBOM backend | ❌ DEAD (commented out) |
| `iamazim.com/api/fazle/wbom/` | 127.0.0.1:9900 | **DISABLED** | Old WBOM backend | ❌ DEAD (commented out) |

**Port 9900 (WBOM):** Referenced in nginx as `# DISABLED` — this backend no longer exists. It was the old "Dograh" system, migrated to Fazle in April 2026.

### Fazle Core Route Map (key endpoints)

| Route | Method | Handler | Purpose |
|---|---|---|---|
| `/webhook/meta` | GET/POST | main.py | Meta WhatsApp webhook |
| `/api/fazle/social/whatsapp/webhook` | GET/POST | main.py (nginx alias) | Alternative webhook path |
| `/bridge1/send` | POST | main.py | Bridge1 outbound send |
| `/bridge2/send` | POST | main.py | Bridge2 outbound send |
| `/health` | GET | main.py | Health probe |
| `/api/fpe/*` | various | fazle_payroll_engine.routes | Payroll engine API |
| `/api/escort-roster/*` | various | escort_roster.routes | Roster management |
| `/api/employees/*` | various | admin_employees | Employee CRUD |
| `/api/transactions/*` | various | admin_transactions | Transaction CRUD |
| `/api/social/*` | various | social_auto_reply.routes | Social reply management |
| `/admin/chat` | POST | main.py | Admin AI chat |
| `/payroll` | GET | main.py | Payroll SPA |
| `/docs` | — | blocked | Disabled in production |
| `/openapi.json` | — | blocked | Disabled in production |

---

## 16. Runtime Services Summary

| Process | PID | CPU | RAM | Since | Description |
|---|---|---|---|---|---|
| fazle-core (uvicorn) | 2218732 | 41.9% | ~93MB | May 31 | Main app — 569h CPU |
| media-processor | 2360164 | 6.6% | ~1.27GB | May 28 | Shared media server |
| vscode extension host | 3612291 | 6.3% | ~1.26GB | 14:33 | VS Code (active editing session) |
| social_auto_reply | 3423 | 0.0% | ~53MB | May 26 | Social auto-reply daemon |
| facebook_supervisor_agent | 2673 | 0.0% | ~42MB | May 26 | Facebook supervision |
| system-agent (uvicorn) | 1835475 | 1.3% | ~63MB | May 31 | Internal system agent :8300 |
| open-webui (uvicorn) | 894634 | 1.0% | ~1.11GB | May 31 | AI chat frontend |
| whatsapp-bridge (3x) | 779, 2253730, 4060699 | ~0.0% each | ~32MB each | May 26+ | Go bridge binaries |
| bridge3 loop | 1046 | 0.0% | ~3MB | May 26 | Bridge3 bash loop script |

---

## 17. Environment Variables

| Variable | Purpose | Used By |
|---|---|---|
| `ADMIN_META_NUMBER` | Primary Meta API admin phone | main.py, settings |
| `ADMIN_NUMBERS` | Comma-separated admin phone list | identity_brain, admin routing |
| `ACCOUNTANT_PHONE` | Accountant phone for silent-skip + routing | message_router, settings |
| `AUTO_REPLY_ENABLED` | Master switch for outbound auto-reply | bridge_poller (SAFE MODE) |
| `RECRUITMENT_AUTOREPLY_ENABLED` | Bypass SAFE MODE for recruitment replies | bridge_poller |
| `SOCIAL_AUTO_REPLY_SINGLE_ENGINE` | Route all social to standalone daemon | bridge_poller |
| `DRAFT_QUALITY_GATE` | Enable/disable quality gate for drafts | draft_quality |
| `DRAFT_ALWAYS_PHONES` | Phones always requiring manual review | bridge_poller |
| `DRAFT_ALWAYS_ROLES` | Roles always requiring manual review | bridge_poller |
| `DRAFT_ALWAYS_NAMES` | Name substrings requiring manual review | bridge_poller |
| `DRAFT_NAME_PREFIXES` | Name prefixes triggering draft gate | bridge_poller |
| `OLLAMA_MODEL` | Active LLM model name (qwen2.5:3b) | app/ollama.py |
| `OLLAMA_URL` | Ollama API endpoint (Docker internal) | app/ollama.py |
| `OLLAMA_URL_TEMPLATE` | URL template for multi-bridge Ollama | app/ollama.py |
| `DATABASE_URL_TEMPLATE` | PostgreSQL connection string template | app/database.py |
| `REDIS_URL_TEMPLATE` | Redis connection template | scheduler, outbound |
| `AI_SAFE_MODE` | Force uncertain/long replies to draft | bridge_poller |
| `APP_PORT` | Uvicorn listen port (8200) | run.py |
| `DEBUG` | Debug mode / uvicorn reload | run.py |
| `LOG_LEVEL` | Logging level | logging_setup.py |
| `INTERNAL_API_KEY` | API key for internal service calls | main.py |
| `META_APP_SECRET` | Meta webhook signature verification | main.py |
| `META_VERIFY_TOKEN` | Meta webhook verification token | main.py |
| `META_API_TOKEN` | Meta Graph API token | main.py |
| `META_PHONE_NUMBER_ID` | Meta phone number ID | main.py |
| `META_WABA_ID` | WhatsApp Business Account ID | main.py |
| `FB_PAGE_ACCESS_TOKEN` | Facebook page token | facebook_supervisor_agent |
| `FB_PAGE_ID` | Facebook page ID | facebook_supervisor_agent |
| `FB_BUSINESS_ID` | Facebook Business ID | facebook_supervisor_agent |
| `BACKUP_DIR` / `BACKUP_PG_CONTAINER` | Backup config | backup module |
| `SCHEDULER_ENABLED` / `SCHEDULER_TIMEZONE` | Scheduler config | scheduler |
| `PAYROLL_AUTO_COMPUTE_HOUR` | Daily payroll compute time | scheduler, fpe |
| `ESCORT_CLIENT_PHONES` | Explicit escort client phone list | identity_brain, settings |
| `ESCORT_STALE_DAYS` | Days before escort marked stale | escort_lifecycle |
| `FPE_CASH_AUTHORIZED_PHONES` | Phones authorized for cash transactions | admin_transactions |
| `FPE_INCOME_AUTHORIZED_PHONES` | Phones authorized for income records | admin_transactions |
| `OUTBOUND_ENABLED` / `OUTBOUND_BRIDGE_TIMEOUT_S` | Outbound queue config | outbound |
| `USE_OUTBOUND_QUEUE` | Enable queue-based outbound | bridge_poller |
| `REVIEWED_REPLY_MEMORY_ENABLED` | Enable admin-approved reply lookup | reviewed_reply_memory |
| `CONTACT_RISK_LEVELS` | JSON map of phone → risk level | bridge_poller |
| `MEDIA_PROCESSOR_URL` | URL for shared media processor | ocr, voice modules |
| `GAP_SCAN_ENABLED` | Enable FPE gap detection scan | gap_detector |
| `REPORT_CACHE_TTL_SEC` | Report cache TTL | reports |
| `OCR_CONCURRENCY` | Max parallel OCR tasks | main.py |
| `PAYROLL_BULK_CONCURRENCY` | Max parallel payroll computes | main.py |
| `HEALTH_DISK_WARN_PCT` / `HEALTH_DISK_CRIT_PCT` | Disk health thresholds | health endpoint |
| `HEALTH_MEM_CRIT_MB` | Memory health threshold | health endpoint |
| `DLQ_ALERT_INTERVAL_MIN` | Dead letter queue alert interval | outbound |

---

## 18. Database Tables

Grouped by domain:

**Core messaging:**
`wbom_whatsapp_messages`, `wbom_contacts`, `wbom_employees`, `wbom_relation_types`, `wbom_inbound_messages`

**Draft & reply system:**
`fazle_draft_replies`, `fazle_reviewed_replies`, `fazle_reviewed_reply_memory`

**Admin & roles:**
`fazle_admins`, `fazle_admin_roles`, `fazle_admin_audit`, `fazle_roles`, `fazle_contact_roles`, `fazle_unified_contacts`, `fazle_contact_aliases`

**Bridge infrastructure:**
`bridge_poller_cursor`, `processed_bridge_messages`, `processed_outgoing_escort_messages`, `outbound_safety_incidents`, `fazle_bridge_heartbeats`

**Recruitment:**
`fazle_recruitment_sessions`

**Escort:**
`escort_roster_entries`, `escort_order_groups`, `escort_order_lighters`, `escort_release_matches`, `escort_roster_audit_logs`, `escort_shift_logs`, `escort_slip_extractions`, `escort_calculation_config`

**Payment & payroll (FPE):**
`fpe_employees`, `fpe_cash_transactions`, `fpe_income_transactions`, `fpe_employee_ledger`, `fpe_employee_aliases`, `fpe_employee_resolution_links`, `fpe_employee_review_queue`, `fpe_gap_scan_runs`, `fpe_message_processing_state`, `fpe_normalization_audit_logs`, `fpe_parser_results`, `fpe_processing_diagnostics`, `fpe_review_audit_logs`, `fpe_sync_checkpoints`, `fpe_transaction_repairs`, `fpe_unmatched_messages`, `fpe_wa_messages`, `fpe_accounting_audit_logs`, `fazle_payment_drafts`, `fazle_payment_correction_log`

**Knowledge & AI:**
`fazle_knowledge_base`, `fazle_report_cache`

**Social auto-reply:**
`social_inbox_events`, `social_reply_queue`, `social_rate_limit_state`, `social_flagged_items`, `social_backlog_state`

**Outbound & scheduler:**
`fazle_outbound_queue`, `fazle_message_queue`, `fazle_queue_leases`, `fazle_processing_locks`

**Attendance:**
(handled via wbom tables + attendance_parser draft creation)

**System:**
`fazle_service_heartbeats`, `fazle_db_backups`, `fazle_state_version`, `fazle_runtime_nodes`, `fazle_contact_sync_log`

---

## 19. Dead Code & Orphan Modules

| Module/Path | Lines | Evidence | Risk if Deleted |
|---|---|---|---|
| `modules/employee_utils/` | 102 | 0 import callers in production code | LOW — dead utility |
| `modules/gap_detector/` | 480 | 0 import callers (GAP_SCAN_ENABLED env exists but no caller) | LOW — background scan |
| `modules/csv_import/` | 292 | 0 import callers | LOW — admin import tool |
| `modules/media/` | — | No `__init__.py` — not a Python package | NONE — already dead |
| `modules/reply/` | — | No `__init__.py` — not a Python package | NONE — already dead |
| `modules/recruitment/` | — | No `__init__.py` — not a Python package | NONE — already dead |
| `modules/context_memory/` | 105 | 1 caller — likely experimental | LOW |
| `/home/azim/external_recruitment_bot_v2/` | — | Service not in ps, v3 exists | LOW — superseded |
| `/home/azim/dograh/` | — | Listed in /home/azim — old system replaced Apr 2026 | NONE — confirm before delete |
| `127.0.0.1:9900` (WBOM backend) | — | Nginx routes commented as `# DISABLED` — nothing running on 9900 | NONE — already disabled |

**Note on `gap_detector`:** The env var `GAP_SCAN_ENABLED` exists, suggesting this module was planned to be called by scheduler, but the scheduler import chain doesn't confirm it. Treat as dormant, not deleted.

---

## 20. High-Risk Architectural Issues

### 🔴 CRITICAL: Phase 1 "Empty Stubs" List Is Wrong

The existing refactoring plan (`FAZLE_CORE_CONSOLIDATION_PLAN.md`) identifies these as "empty stubs to delete":
`accountant_summary`, `admin_commands`, `admin_employees`, `admin_transactions`, `attendance`, `attendance_parser`, `backup`

**ALL SEVEN are live production code with active callers:**

| Module | Lines | Active Importers | Impact if Deleted |
|---|---|---|---|
| `admin_commands` | 1,329 | 21 | ❌ All admin commands (APPROVE/REJECT/PAID) stop working |
| `admin_transactions` | 550 | 1 (FastAPI router in main.py) | ❌ Transaction CRUD API disappears |
| `admin_employees` | 390 | 1 (FastAPI router in main.py) | ❌ Employee management API disappears |
| `backup` | 288 | 36 | ❌ All scheduled backups fail |
| `attendance` | 244 | 11 | ❌ Attendance handling breaks |
| `attendance_parser` | 281 | 1 | ❌ Supervisor attendance parse breaks |
| `accountant_summary` | 157 | 9 | ❌ Accountant summary acks break |

**This is a production-critical blocker.** Phase 1 of refactoring must be skipped or replaced with a corrected list.

### 🟡 HIGH: Payment Import Path Inconsistency

`modules/payment/__init__.py` exists as a re-export layer for `payment_workflow`, but:
- `app/main.py:35` imports `payment_workflow` directly
- `message_router:47` imports `payment_workflow` directly
- `app/main.py:1195` imports `payment_ingest` directly

Two import paths exist for the same functions. If `payment_workflow` is moved/renamed, these callers will break independently.

### 🟡 HIGH: Social Auto-Reply Dual Execution

`social_auto_reply` is imported by both:
1. `bridge_poller` (calls `ingest_social_event()` inline, line 831-845)
2. A **standalone process** via `service_runner.py` (PID 3423)

When `SOCIAL_AUTO_REPLY_SINGLE_ENGINE=true`, bridge_poller deliberately skips its legacy router and delegates to the standalone daemon. This is intentional but creates a dependency: if the standalone process dies, bridge_poller silently skips all reply logic for those messages without fallback.

### 🟡 HIGH: Bridge Health Port Mismatch

Health checks to bridge1 (port 8082) and bridge2 (port 8081) return `404 page not found`. The bridges are alive (bridge1_db and bridge2_db probes pass in `/health`), but the bridges' own HTTP health endpoints are not responding on expected ports. Bridge port configuration may have shifted.

### 🟠 MEDIUM: Multiple Recruitment Bots (Coordination Unknown)

Three external recruitment agents exist:
- `external_recruitment_agent/` (v1 — has systemd service file)
- `external_recruitment_bot_v2/`
- `external_recruitment_bot_v3/`

The fazle-core internal `recruitment_flow` + `recruitment_ai` also runs simultaneously. If all are active, they may independently reply to the same candidate, creating conflicting conversations.

### 🟠 MEDIUM: phone normalization in 3 places

`normalize_phone()` exists in `user_role`, `number_identity`, and `message_router._phone_variants()`. These may have subtly different normalization rules (880xxx vs 0xxx handling), leading to lookup misses depending on which normalizer is called.

---

## 21. Safe Cleanup Candidates (READ-ONLY SUGGESTIONS — no action taken)

These are suggestions only. No changes made.

| Candidate | Type | Safety | Suggested Action |
|---|---|---|---|
| `modules/employee_utils/` | Dead module | ✅ Safe | Delete (0 importers, 102 lines) |
| `modules/gap_detector/` | Dormant module | ✅ Safe (verify gap_scan disabled) | Delete or document as dormant |
| `modules/csv_import/` | Dead module | ✅ Safe | Delete (0 importers) |
| `modules/media/` | Orphan dir | ✅ Safe | `rm -rf` (no `__init__.py`) |
| `modules/reply/` | Orphan dir | ✅ Safe | `rm -rf` (no `__init__.py`) |
| `modules/recruitment/` | Orphan dir | ✅ Safe | `rm -rf` (no `__init__.py`) |
| `/home/azim/dograh/` | Old app (pre-Apr 2026) | ⚠️ Verify first | Confirm no running process, then archive |
| `external_recruitment_bot_v2/` | Superseded by v3 | ⚠️ Verify first | Confirm not running |
| Nginx WBOM `# DISABLED` blocks | Dead config | ✅ Safe | Remove commented lines from nginx config |

**Modules incorrectly listed as safe to delete in refactoring plan:**
`accountant_summary`, `admin_commands`, `admin_employees`, `admin_transactions`, `attendance`, `attendance_parser`, `backup` — **DO NOT DELETE ANY OF THESE.**

**Correct "empty stubs" for Phase 1 refactoring:**
Only the three orphan directories have zero content and zero risk: `modules/media/`, `modules/reply/`, `modules/recruitment/`.

---

## 22. Module Dependency Graph

```
app/main.py
  ├── modules.fazle_intent
  ├── modules.fazle_bridge_poller
  │     ├── modules.message_router
  │     ├── modules.fazle_intent
  │     ├── modules.recruitment_flow
  │     ├── modules.recruitment_ai
  │     ├── modules.escort
  │     ├── modules.escort_lifecycle
  │     ├── modules.fazle_identity_brain
  │     ├── modules.observability
  │     ├── modules.ocr_processor
  │     ├── modules.voice_processor
  │     ├── modules.draft_quality
  │     └── modules.social_auto_reply
  ├── modules.escort_slip_extractor
  ├── modules.fazle_payment_workflow
  ├── modules.message_router
  │     ├── modules.fazle_intent
  │     ├── modules.fazle_identity_brain
  │     ├── modules.payroll_logic
  │     ├── modules.escort
  │     ├── modules.knowledge_base
  │     ├── modules.recruitment_flow
  │     ├── modules.recruitment_ai
  │     ├── modules.fazle_admin_commands
  │     │     └── modules.fazle_admin_commands.nl_router
  │     │     └── modules.fazle_admin_commands.nl_advance_record
  │     ├── modules.fazle_payment_workflow
  │     ├── modules.fazle_payment_ingest
  │     ├── modules.attendance
  │     ├── modules.attendance_parser
  │     ├── modules.employee_verification
  │     ├── modules.accountant_summary   [lazy]
  │     ├── modules.escort_lifecycle     [lazy]
  │     └── modules.reviewed_reply_memory [lazy]
  ├── modules.recruitment_flow
  ├── modules.outbound
  ├── modules.scheduler
  │     ├── modules.backup
  │     ├── modules.payroll
  │     └── modules.observability
  ├── modules.fazle_payroll_engine
  ├── modules.escort_roster
  ├── modules.admin_employees
  ├── modules.admin_transactions
  └── modules.social_auto_reply

Independent (no cross-module imports from core):
  modules.payment_correction → app.database only
  modules.observability → stdlib only
  modules.draft_quality → stdlib only
  modules.number_identity → stdlib only
  modules.user_role → app.database, stdlib

Dead (no importers):
  modules.employee_utils → modules.user_role (imported but nothing calls employee_utils)
  modules.gap_detector → standalone
  modules.csv_import → standalone
```

---

## 23. Full File & Module Relationship Map

| File | Type | Role | Status |
|---|---|---|---|
| `run.py` | Entry point | Uvicorn launcher | ✅ ACTIVE |
| `app/main.py` (2,059 lines) | FastAPI app | HTTP transport, webhook, all routes | ✅ ACTIVE |
| `app/config.py` | Config | Settings dataclass, env loading | ✅ ACTIVE |
| `app/database.py` | DB | asyncpg connection pool | ✅ ACTIVE |
| `app/bridge.py` | Bridge | HTTP clients for bridge1/bridge2 send API | ✅ ACTIVE |
| `app/ollama.py` (257 lines) | AI | LLM client for qwen2.5:3b | ✅ ACTIVE |
| `app/logging_setup.py` | Logging | Structured logging setup | ✅ ACTIVE |
| `app/critical_numbers.py` | Config | Critical phone numbers | ✅ ACTIVE |
| `modules/message_router/` (557 lines) | Router | All message routing logic | ✅ ACTIVE — CORE |
| `modules/bridge_poller/` (1,302 lines) | Poller | SQLite DM ingest for bridge1+bridge2 | ✅ ACTIVE — CORE |
| `modules/identity_brain/` (298 lines) | Identity | Role detection, confidence scoring | ✅ ACTIVE |
| `modules/intent/` (171 lines) | Intent | Keyword intent classifier | ✅ ACTIVE |
| `modules/escort/` (863 lines) | Escort | Client flow, completion, drafts | ✅ ACTIVE |
| `modules/escort_lifecycle/` (638 lines) | Escort | Release slips, lifecycle events | ✅ ACTIVE |
| `modules/escort_roster/` (multi-file) | Escort | Roster entries, FastAPI routes | ✅ ACTIVE |
| `modules/escort_slip_extractor/` | Escort | Text-based slip extraction | ✅ ACTIVE |
| `modules/payment_workflow/` (340 lines) | Payment | Draft creation, finalization | ✅ ACTIVE |
| `modules/payment_ingest/` (433 lines) | Payment | SMS/cash parse, employee match | ✅ ACTIVE |
| `modules/payment_correction/` (289 lines) | Payment | Correction audit | ✅ ACTIVE |
| `modules/payment/` (22 lines) | Payment | Re-export stub (incomplete) | ⚠️ PARTIAL |
| `modules/recruitment_flow/` (291 lines) | Recruitment | Session tracking, triggers | ✅ ACTIVE |
| `modules/recruitment_ai/` (206 lines) | Recruitment | AI reply generation | ✅ ACTIVE |
| `modules/admin_commands/` (1,329 lines) | Admin | Command processor + NL query | ✅ ACTIVE |
| `modules/admin_employees/` (390 lines) | Admin | Employee CRUD FastAPI routes | ✅ ACTIVE |
| `modules/admin_transactions/` (550 lines) | Admin | Transaction CRUD FastAPI routes | ✅ ACTIVE |
| `modules/accountant_summary/` (157 lines) | Accountant | Daily summary ack | ✅ ACTIVE |
| `modules/attendance/` (244 lines) | Attendance | Attendance handling | ✅ ACTIVE |
| `modules/attendance_parser/` (281 lines) | Attendance | Structured parse | ✅ ACTIVE |
| `modules/employee_verification/` (376 lines) | Employee | Verification sessions | ✅ ACTIVE |
| `modules/knowledge_base/` (309 lines) | KB | Reply lookup | ✅ ACTIVE |
| `modules/rag/` (389 lines) | AI | RAG retrieval pipeline | ✅ ACTIVE |
| `modules/reviewed_reply_memory/` (365 lines) | AI | Admin-approved reply cache | ✅ ACTIVE |
| `modules/draft_quality/` (84 lines) | Quality | Reply quality gate | ✅ ACTIVE |
| `modules/outbound/` (215 lines) | Outbound | Queue management | ✅ ACTIVE |
| `modules/observability/` (156 lines) | Metrics | Counter tracking | ✅ ACTIVE |
| `modules/scheduler/` (551 lines) | Scheduler | Cron jobs (backup, payroll, digest) | ✅ ACTIVE |
| `modules/backup/` (288 lines) | Backup | pg_dump + rotation | ✅ ACTIVE |
| `modules/social_auto_reply/` (225 lines + service_runner) | Social | Social reply daemon | ✅ ACTIVE (separate process) |
| `modules/fazle_payroll_engine/` (multi-file) | Payroll | Full payroll lifecycle + API | ✅ ACTIVE |
| `modules/payroll/` | Payroll | Payroll compute functions | ✅ ACTIVE |
| `modules/payroll_logic/` | Payroll | Context formatting | ✅ ACTIVE |
| `modules/rbac/` (340 lines) | Access | Role-based access control | ✅ ACTIVE |
| `modules/user_role/` (256 lines) | Roles | Phone normalization, role utils | ✅ ACTIVE |
| `modules/number_identity/` (107 lines) | Identity | Phone normalization | ✅ ACTIVE |
| `modules/ocr_processor/` | OCR | Image/PDF OCR | ✅ ACTIVE (lazy) |
| `modules/voice_processor/` | STT | Audio transcription | ✅ ACTIVE (lazy) |
| `modules/employee_utils/` (102 lines) | Utility | Employee get/create helper | ❌ DEAD (0 importers) |
| `modules/gap_detector/` (480 lines) | FPE | Gap detection scan | ❌ DORMANT (0 callers) |
| `modules/csv_import/` (292 lines) | Admin | CSV import tool | ❌ DEAD (0 callers) |
| `modules/context_memory/` (105 lines) | AI | Conversation context | ⚠️ NEAR-DEAD (1 caller) |
| `modules/gap_actions/` (280 lines) | FPE | Gap remediation | ⚠️ NEAR-DEAD (1 caller) |
| `modules/media_normalization/` | Media | Media normalization | ⚠️ UNVERIFIED |
| `modules/message_archive/` | Archive | Message archival | ⚠️ UNVERIFIED |
| `modules/contact_sync/` | Sync | Contact sync | ⚠️ UNVERIFIED |
| `modules/conversation_layer/` | AI | Conversation management | ⚠️ UNVERIFIED |
| `modules/reply_templates/` | Templates | Reply templates | ⚠️ UNVERIFIED |
| `modules/reports/` | Reports | Reporting | ⚠️ UNVERIFIED |
| `modules/image_hash/` | Media | Image dedup | ⚠️ UNVERIFIED |
| `modules/media/` (dir) | — | No `__init__.py` | ❌ ORPHAN |
| `modules/reply/` (dir) | — | No `__init__.py` | ❌ ORPHAN |
| `modules/recruitment/` (dir) | — | No `__init__.py` | ❌ ORPHAN |

---

*Audit completed 2026-06-01. Read-only mode maintained throughout. No files modified, no services restarted, no commands executed that could affect runtime state.*
