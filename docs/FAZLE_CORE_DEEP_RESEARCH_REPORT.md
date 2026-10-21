# Fazle Core — Deep Research Report

> **Pre-unification schema note.** Table names in this document refer to the
> pre-unification schema. See `audits/prefix_unification_2026-10-21.md` for the
> current table names.
**Date:** 2026-05-06  
**Scope:** Complete codebase audit — no code changes made.

---

## 1. Repository Layout

```
/home/azim/core/
├── app/                    ← FastAPI application (main process)
│   ├── main.py             ← Application entry-point, all HTTP routes
│   ├── config.py           ← Pydantic settings (reads .env)
│   ├── database.py         ← asyncpg connection pool helpers
│   ├── bridge.py           ← Bridge1/Bridge2 HTTP clients
│   ├── ollama.py           ← LLM (Ollama) integration
│   ├── logging_setup.py
│   ├── error_log.py
│   ├── critical_numbers.py ← Hardcoded critical phone constants
│   └── static/
│       └── dashboard.html  ← Full single-page admin dashboard (all tabs)
├── frontend/
│   └── templates/          ← Empty (dashboard is served from app/static/)
├── modules/                ← Business-logic modules (see §3)
├── db/
│   ├── new_tables.sql      ← Fazle-specific table definitions
│   ├── merge_preview.sql
│   └── migrations/         ← 008 numbered SQL migrations (001–008)
├── scripts/                ← CI tests, import helpers, git sprint script
├── docs/                   ← Architecture, API, roadmap docs
├── resources/              ← Business rule text files (Cash Payment logic etc.)
├── reports/
├── logs/
├── run.py                  ← Uvicorn entrypoint
├── requirements.txt
├── Dockerfile
└── fazle-core.service      ← systemd unit (host deployment)
```

---

## 2. Main Application

### Framework
- **FastAPI** (async), served by **Uvicorn**
- Entry: `run.py` → `app.main:app`

### Port & Bind Address
| Setting | Value |
|---|---|
| Host | `127.0.0.1` (localhost only) |
| Port | **8200** (env `APP_PORT`, default 8200) |
| Debug/reload | `False` in production |

### API Key Authentication
All protected endpoints require the header `X-Internal-Key`. The value is checked against:
1. `INTERNAL_API_KEY` env var (legacy single key)
2. Per-admin SHA-256 hashed API keys stored in `fazle_admins` table (Batch 19 RBAC)

---

## 3. Inbound Channels (Bridges)

Three entry surfaces all funnel into the same `process_message()` router:

| Channel | Route | Number | Port |
|---|---|---|---|
| Meta WhatsApp Cloud API | `POST /webhook/meta` | Meta phone number ID (env) | — |
| Bridge 1 (HR) | `POST /webhook/mcp1` | 8801958122300 | 8080 |
| Bridge 2 (OPS) | `POST /webhook/mcp2` | 8801880446111 | 8081 |

Bridge 1 and Bridge 2 are Go-based WhatsApp bridges running in Docker at `localhost:8080` and `localhost:8081`.  
A background **Bridge Poller** (`modules/fazle_bridge_poller`) also polls these bridges via SQLite DB files:
- Bridge1: `/home/azim/bridges/bridge1/store/messages.db`
- Bridge2: `/home/azim/bridges/bridge2/store/messages.db`

---

## 4. Database

### Connection
- Driver: `asyncpg` (async PostgreSQL)
- Container: `ai-postgres` (Docker), database name: `postgres`
- URL from env: `DATABASE_URL`
- Pool: min=2, max=10 connections

### Redis
- URL: `redis://localhost:6379/9`
- Used by outbound queue (Batch 15)

### Supporting Services
- **Ollama** at `localhost:11434`, model `qwen2.5:3b` — local LLM for AI replies

---

## 5. Database Tables (Complete Schema Reference)

### 5.1 `fazle_employees_legacy` — Core Employee Registry
| Column | Type | Notes |
|---|---|---|
| `employee_id` | SERIAL PK | |
| `employee_mobile` | VARCHAR(20) UNIQUE | Phone used for identity lookup |
| `employee_name` | VARCHAR(100) | |
| `designation` | VARCHAR(30) | Escort / Seal-man / Security Guard / Supervisor / Labor |
| `joining_date` | DATE | |
| `status` | VARCHAR(20) | Active / Inactive / On Leave / Terminated |
| `basic_salary` | DECIMAL(10,2) | Added in migration 014 |
| `bkash_number` | VARCHAR(20) | Added in migration 014 |
| `nagad_number` | VARCHAR(20) | Added in migration 014 |
| `nid_number` | VARCHAR(20) | Added in migration 014 |
| `bank_account` | VARCHAR(50) | |
| `emergency_contact` | VARCHAR(20) | |
| `address` | TEXT | |
| `created_at`, `updated_at` | TIMESTAMPTZ | |

**How frontend uses it:**  
The "Payroll" and "Transactions" dashboard tabs query this table to show employee names alongside salary runs and cash transactions. The identity brain (`modules/fazle_identity_brain`) looks up `employee_mobile` to classify inbound senders.

---

### 5.2 `wbom_escort_programs` — Escort Duty Records
| Column | Type | Notes |
|---|---|---|
| `program_id` | SERIAL PK | |
| `mother_vessel` | VARCHAR(100) | MV name from client order |
| `lighter_vessel` | VARCHAR(100) | Lighter vessel name |
| `master_mobile` | VARCHAR(20) | Lighter master's phone |
| `destination` | VARCHAR(100) | |
| `escort_employee_id` | INT FK→fazle_employees_legacy | Assigned guard |
| `escort_mobile` | VARCHAR(20) | Guard's mobile |
| `program_date` | DATE | Start date |
| `shift` | VARCHAR(1) | D (Day) or N (Night) |
| `status` | VARCHAR(20) | Assigned/Running/Completed/Cancelled |
| `start_date`, `end_date` | DATE | Lifecycle dates (added mig-014) |
| `end_shift` | VARCHAR(1) | D or N at release |
| `release_point` | VARCHAR(100) | Where guard was released |
| `day_count` | INT / FLOAT | Number of days worked |
| `conveyance` | DECIMAL(10,2) | Travel allowance |
| `capacity` | VARCHAR(20) | Vessel capacity (MT) |
| `completion_time` | TIMESTAMPTZ | When duty ended |
| `remarks` | TEXT | JSON blob: sender_phone, escort_name, etc. |
| `contact_id` | INT FK→fazle_contacts | Client who placed the order |

---

### 5.3 `wbom_attendance` — Daily Attendance Log
| Column | Type | Notes |
|---|---|---|
| `attendance_id` | SERIAL PK | |
| `employee_id` | INT FK→fazle_employees_legacy | |
| `attendance_date` | DATE | |
| `status` | VARCHAR(20) | Present / Absent / Leave / Half-day |
| `location` | VARCHAR(100) | Site/vessel name |
| `check_in_time` | TIMESTAMPTZ | |
| `check_out_time` | TIMESTAMPTZ | |
| `remarks` | TEXT | |
| `recorded_by` | VARCHAR(50) | 'escort-lifecycle' for auto-backfill |
| `created_at` | TIMESTAMPTZ | |
| UNIQUE | `(employee_id, attendance_date)` | One row per day per employee |

---

### 5.4 `fazle_cash_transactions_archive` — All Money Movements
| Column | Type | Notes |
|---|---|---|
| `transaction_id` | SERIAL PK | |
| `employee_id` | INT FK→fazle_employees_legacy | |
| `program_id` | INT FK→wbom_escort_programs | Optional link |
| `transaction_type` | VARCHAR(20) | advance / escort_payment / Advance / Food / Conveyance / Salary / Deduction / Other |
| `amount` | DECIMAL(10,2) | |
| `payment_method` | VARCHAR(10) | Cash / Bkash / Nagad / Rocket / Bank |
| `payment_mobile` | VARCHAR(20) | Bkash/Nagad number used |
| `employee_phone` | TEXT | Guard's phone (added Batch 12) |
| `payment_number` | TEXT | Bkash/Nagad number (added Batch 12) |
| `transaction_date` | DATE | DEFAULT CURRENT_DATE (added mig-003) |
| `transaction_time` | TIMESTAMPTZ | |
| `status` | VARCHAR(20) | Pending / Completed / Failed |
| `reference_number` | VARCHAR(50) | |
| `remarks` | TEXT | "Draft #ID — approved by admin" |
| `created_by` | VARCHAR(50) | |
| `reversal_of` | INT FK→self | For reversals (Batch 28) |
| `is_reversal` | BOOLEAN | |
| `reversal_reason` | TEXT | |

---

### 5.5 `fazle_payment_drafts` — Payment Approval Queue
| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `draft_type` | TEXT | escort_payment / advance / salary |
| `employee_id` | INT FK→fazle_employees_legacy | |
| `employee_name` | TEXT | |
| `employee_mobile` | TEXT | |
| `escort_program_id` | INT FK→wbom_escort_programs | |
| `duty_days` | FLOAT | |
| `expected_amount` | FLOAT | |
| `approved_amount` | FLOAT | |
| `payment_method` | TEXT | bkash / nagad / cash |
| `payment_number` | TEXT | |
| `status` | TEXT | pending / approved / rejected / sent |
| `source` | TEXT | bridge1 / bridge2 / meta |
| `draft_text` | TEXT | Formatted Bengali message sent to admin |
| `admin_reply` | TEXT | Raw admin reply stored |
| `accountant_msg` | TEXT | Formatted message sent to accountant |
| `created_at`, `updated_at` | TIMESTAMPTZ | |

---

### 5.6 `fazle_draft_replies` — Outbound Reply Queue
| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `recipient` | TEXT | Phone number |
| `reply_text` | TEXT | Draft reply content |
| `intent` | TEXT | attendance / escort / payment / generic |
| `draft_type` | TEXT | Added mig-005 |
| `meta` | JSONB | Extra context added mig-005 |
| `source` | TEXT | bridge1 / bridge2 / meta |
| `status` | TEXT | pending / approved / rejected / sent |
| `approved_at` | TIMESTAMPTZ | |
| `admin_phone` | TEXT | Which admin to notify |
| `created_at` | TIMESTAMPTZ | |

---

### 5.7 Other Fazle Tables
| Table | Purpose |
|---|---|
| `fazle_knowledge_base` | Auto-reply FAQ templates (12 recruitment + escort/payment categories) |
| `fazle_recruitment_sessions` | Per-phone recruitment intake conversation state |
| `fazle_contact_roles` | Seed identity rules (accountant, escort buyers, family, VIPs etc.) |
| `fazle_admins` | Admin users with roles |
| `fazle_admin_roles` | Many-to-many admin↔role |
| `fazle_admin_audit` | Every command attempt logged |
| `fazle_roles` | Role definitions (viewer/operator/accountant/admin/superadmin) |
| `fazle_report_cache` | Cached report payloads (10-min TTL) |
| `fazle_report_runs` | Report execution audit log |
| `fazle_service_heartbeats` | Bridge poller liveness timestamps |
| `fazle_reviewed_reply_memory` | Approved reply patterns for reuse |
| `wbom_payroll_runs` | Monthly payroll computation results |
| `wbom_payroll_run_items` | Line items per payroll run |
| `wbom_payroll_approval_log` | State machine transitions |
| `wbom_salary_records` | Legacy monthly salary records |
| `wbom_employee_requests` | Self-service advance/salary query requests |
| `wbom_cases` | Incident/case tracking |
| `fazle_contacts` | WhatsApp contact directory |
| `fazle_whatsapp_messages` | Full message archive |
| `wbom_staging_payments` | Imported payment staging area |

---

## 6. Modules Map

```
modules/
├── admin_commands/       ← All WhatsApp command parsing & execution
│   └── nl_router/        ← Natural-language admin query router
├── attendance/           ← Guard check-in via WhatsApp keyword
├── attendance_parser/    ← Supervisor bulk attendance from list format
├── backup/               ← Automated DB backup (Batch 18)
├── bridge_poller/        ← Background poll of bridge SQLite DBs
├── contact_sync/         ← Sync contacts to fazle_contacts
├── context_memory/       ← In-process 3-message rolling context window
├── csv_import/           ← Bulk employee/data import
├── draft_quality/        ← Draft quality scoring
├── employee_utils/       ← Employee lookup helpers
├── employee_verification/← Multi-step identity verification for payments
├── escort/               ← Vessel order parsing & escort draft creation
├── escort_lifecycle/     ← Release detection, program close, attendance backfill
├── escort_slip_extractor/← OCR-based release slip extraction
├── gap_actions/          ← Gap response actions (Batch 25)
├── gap_detector/         ← Detect conversation gaps for follow-up
├── identity_brain/       ← Unified sender role detection
├── image_hash/           ← Perceptual hash for duplicate image detection
├── intent/               ← Intent classifier (classify())
├── knowledge_base/       ← KB lookup (fazle_knowledge_base)
├── media/                ← Media download & storage
├── media_normalization/  ← Normalize media messages to text
├── message_archive/      ← Save all messages to fazle_whatsapp_messages
├── message_router/       ← MASTER ROUTER: dispatches all inbound messages
├── number_identity/      ← Phone number normalization
├── observability/        ← Prometheus-style metrics (Batch 22)
├── ocr_processor/        ← OCR on images via media_processor service
├── outbound/             ← Redis-backed async outbound queue (Batch 15)
├── payment/              ← Re-export shim → payment_workflow
├── payment_correction/   ← REVERSE/ADJUST commands (Batch 28)
├── payment_ingest/       ← Accountant payment data ingestion (Batch 12)
├── payment_workflow/     ← Core payment draft creation & finalization
├── payroll/              ← Monthly payroll compute (Batch 14)
├── payroll_logic/        ← Salary context for AI replies
├── rag/                  ← RAG index over knowledge base (Batch 21)
├── rbac/                 ← Role-Based Access Control (Batch 19)
├── recruitment/          ← Recruitment tools
├── recruitment_flow/     ← Intake funnel state machine
├── reply/                ← Reply helpers
├── reply_templates/      ← Canned emergency/incident/vendor reply templates
├── reports/              ← Report builders (daily/payroll/cash/recon) (Batch 17)
├── reviewed_reply_memory/← Learn from approved drafts (Batch 26)
├── scheduler/            ← APScheduler jobs (Batch 16)
├── user_role/            ← Legacy role detection wrapper
└── voice_processor/      ← Voice message transcription
```

---

## 7. Frontend Dashboard (`/dashboard`)

### Access
URL: `http://localhost:8200/dashboard` (requires `X-Internal-Key` login via localStorage)  
Served from: `/home/azim/core/app/static/dashboard.html`  
Technology: Single HTML file — pure vanilla JavaScript, no framework.

### Tabs (in nav order)

| Tab | Route | What it shows |
|---|---|---|
| **Overview** | `/dashboard/overview` | System health, bridge status, backup freshness, scheduler horizon |
| **Drafts** | `/dashboard/drafts` | Pending reply drafts + pending payment drafts, approve/reject actions |
| **Gaps** | `/dashboard/gaps` | Unanswered conversation gaps requiring follow-up |
| **Conversations** | `/dashboard/conversations` | Full message history per contact |
| **Recruitment** | `/dashboard/recruitment` | Active recruitment sessions, funnel stages, scores |
| **Payroll** | `/dashboard/payroll` | Monthly payroll runs by employee, status transitions |
| **Escort Duty** | `/dashboard/escort` | wbom_escort_programs list: active/completed programs |
| **Transactions** | `/dashboard/transactions` | fazle_cash_transactions_archive: advances, payments, method breakdown |
| **Attendance** | `/dashboard/attendance` | wbom_attendance log: present/absent by date/employee |
| **Reports** | `/dashboard/reports` | On-demand: daily, payroll, cash, recon, escort reports |
| **Users (B19)** | `/dashboard/users` | Admin user management (add/role/remove) |
| **Audit** | `/dashboard/audit` | fazle_admin_audit log of all command attempts |
| **Backups** | `/dashboard/backups` | Backup list, freshness, trigger manual backup |
| **Scheduler** | `/dashboard/scheduler` | APScheduler job status, manual trigger |
| **RAG (B21)** | `/dashboard/rag` | Knowledge base index status |
| **Observability (B22)** | `/dashboard/obs` | HTTP request metrics, latency histograms |
| **Chat** | `/dashboard/chat` | Floating AI chat (send test messages, inspect replies) |

### API Endpoints the Dashboard Calls
```
GET  /dashboard                → Serves dashboard.html
GET  /health                   → System probe (db, bridges, disk, mem, outbound)
GET  /health/deep              → Extended health with bridge connectivity
GET  /drafts                   → fazle_draft_replies (pending)
GET  /payment-drafts           → fazle_payment_drafts (pending)
GET  /conversations            → Recent message threads
GET  /employees                → fazle_employees_legacy list
GET  /escort-programs          → wbom_escort_programs
GET  /transactions             → fazle_cash_transactions_archive
GET  /attendance               → wbom_attendance records
GET  /payroll/runs             → wbom_payroll_runs
GET  /reports/{name}           → Report by name (daily_summary, monthly_payroll…)
GET  /scheduler/status         → APScheduler jobs
GET  /backups/list             → Backup files
POST /backups/now              → Trigger manual backup
GET  /metrics/json             → Observability metrics
GET  /admin/users              → fazle_admins list
POST /admin/users              → Add admin
PATCH /admin/users/{phone}/role→ Change role
POST /chat                     → Internal AI chat test
```

---

## 8. Message Routing — Identity & Flow Priority

Every inbound message (from all three channels) is processed by `modules/message_router/process_message()`:

```
Priority order:
 0. Emergency keywords     → immediate admin alert + ack
 1. family                 → personal ack, no workflow
 2. escort_client roles    → vessel order / escort workflow
 3. admin                  → command parsing (APPROVE, PAID, ADVANCE…)
 4. supervisor             → attendance_parser bulk check-in
 5. accountant             → payment/finance KB route + AI
 6. candidate              → recruitment funnel
 7. employee               → verification → slip/advance/salary/attendance
 8. known contacts         → KB → AI
 9. unknown                → intent engine → KB → AI
```

**Identity detection** (`modules/fazle_identity_brain`) resolves role in this priority:
1. `settings` — admin numbers from env
2. `fazle_contact_roles` seed rules (supervisor, accountant, vip_client, family…)
3. `fazle_employees_legacy` — employee_mobile match
4. `fazle_contacts` — contact directory match
5. Text keyword hint → `candidate`
6. `unknown`

---

## 9. Escort Order → Escort Duty Flow

### Step 1: Client Places Order
A client (role: `client_escort_buyer`, `vip_client`, or `repeat_client`) sends a WhatsApp message containing vessel details.

**Detection** (`modules/escort/__init__.py`):
- Message contains keywords like `MV`, `mother vessel`, `lighter`, `এস্কর্ট`, vessel names, mobile numbers, cargo types (wheat, corn, soya, coal…)
- `_MV_LABEL_RE`, `_LIGHTER_*`, `_CARGO_RE`, `_MOBILE_RE` regex patterns extract structured data

**What gets saved to `wbom_escort_programs`:**
```
mother_vessel, lighter_vessel, master_mobile,
destination, program_date, shift (D/N), status='draft'
remarks = JSON{sender_phone, source_bridge, escort_name, escort_mobile,
               capacity, importer, cargo_type}
```

**Admin draft** created in `fazle_draft_replies` with formatted template:
```
Mother Vessel: MV XXXX
Lighter Vessel: YYY
Master's number: 01XXXXXXXX
Escort's name: [blank — admin fills in]
Escort mobile: [blank — admin fills in]
Date: DD/MM/YYYY (D/N)
Al-Aqsa Security Service
```

### Step 2: Admin Assigns Escort
Admin sends `ESCORTCONFIRM <order_id> | <escort_name> | <escort_mobile> | <date> | <D or N>` via WhatsApp.

**Processing** (`modules/admin_commands/__init__.py` `_ESCORTCONFIRM_RE`):
- Updates `wbom_escort_programs` with `escort_employee_id`, `escort_mobile`, `status='Assigned'`
- Sends completed slip to the original client (via the bridge they messaged on)
- Notifies admin with delivery confirmation

### Step 3: Guard On Duty
Guard is now on the vessel. Their daily presence can be:
- **Self-reported**: Guard sends "হাজির" / "present" / "on duty" → attendance module creates attendance draft → admin APPROVEs → row inserted in `wbom_attendance`
- **Supervisor-reported**: Supervisor sends bulk list → `attendance_parser` module processes it

---

## 10. Escort Release Flow

### Guard Sends Release Message
Guard sends any of:
```
Bengali: "ডিউটি শেষ", "রিলিজ", "ছুটি দিন", "ভেসেল ছেড়েছি"
English: "release", "duty done", "duty finished", "program completed"
```
Or sends a **release slip photo** → OCR extraction via `modules/escort_slip_extractor`

### System Processing (`modules/escort_lifecycle/__init__.py`)
1. `is_release_intent(text)` → True
2. `find_active_program_for_employee(employee_id)` — finds latest non-completed program
3. **Admin command alternative**: `RELEASE <program_id> <YYYY-MM-DD> <D|N> <release_point> [days=X]`

### Program Closure
`close_program()` executes:
```sql
UPDATE wbom_escort_programs
SET status='Completed',
    completion_time=NOW(),
    end_date=<date>,
    end_shift=<D|N>,
    release_point=<location>,
    day_count=<computed days>
WHERE program_id=$1
```
- `day_count` = `(end_date - program_date).days + 1` (minimum 1)
- Idempotent — re-running on an already-Completed program returns `already_closed=True`

### Attendance Backfill
`backfill_attendance_for_program()`:
```sql
INSERT INTO wbom_attendance
  (employee_id, attendance_date, status, location, recorded_by)
VALUES ($eid, $date, 'Present', $mother_vessel, 'escort-lifecycle')
ON CONFLICT (employee_id, attendance_date) DO NOTHING
```
Loops from `program_date` to `end_date`, inserting one row per day. `recorded_by='escort-lifecycle'` marks auto-backfilled rows.

### Payment Draft Created
`create_escort_payment_draft()` calculates:
- `daily_rate` = `basic_salary / 30`
- `expected` = `duty_days × daily_rate`
- `advances` = SUM from `fazle_cash_transactions_archive` (type='advance', last 60 days)
- `net_payable` = `max(expected - advances, 0)`

Formatted Bengali draft saved to `fazle_payment_drafts`:
```
💼 এস্কর্ট পেমেন্ট রিকোয়েস্ট:
কর্মী: [name]
ডিউটি: [MV name]
দিন: [X.X]
প্রত্যাশিত: ৳X,XXX
অগ্রিম কর্তন: ৳X,XXX
নেট দেয়: ৳X,XXX
বিকাশ/নগদ: [number]

✅ অনুমোদন দিতে: PAID <draft_id> <amount> bkash
```

---

## 11. Salary Calculation (Monthly Payroll)

**Module:** `modules/payroll/__init__.py`  
**Default rate:** ৳800/day for escort duty (`DEFAULT_PER_PROGRAM_RATE`)  
(The payment_workflow uses `basic_salary / 30` per day for immediate drafts; payroll module uses the fixed ৳800 rate for monthly runs.)

**Formula:**
```
basic_salary         = fazle_employees_legacy.basic_salary
program_allowance    = SUM(day_count × rate) for all Completed programs in period
total_advances       = SUM(fazle_cash_transactions_archive.amount) WHERE type='advance' AND date IN period
gross_salary         = basic_salary + program_allowance + other_allowance
net_salary           = max(gross_salary - total_advances - total_deductions, 0)
```

**State machine** on `wbom_payroll_runs.status`:
```
draft → reviewed → approved → locked → paid
                             ↘ cancelled (from any non-paid state)
```

**Admin commands for payroll:**
```
PAYROLL COMPUTE YYYY-MM [employee_id]   → compute run (idempotent)
PAYROLL SUBMIT <run_id>                 → draft → reviewed
PAYROLL APPROVE <run_id>                → reviewed → approved
PAYROLL LOCK <run_id>                   → approved → locked
PAYROLL PAID <run_id> <amount> <method> [ref=XX] → locked → paid
PAYROLL CANCEL <run_id> <reason>        → any → cancelled
PAYROLL LIST YYYY-MM [status]           → list runs
```

All transitions are logged to `wbom_payroll_approval_log`.

---

## 12. Security Guard Attendance System

### How Attendance Is Counted

There are **three distinct pathways** that write to `wbom_attendance`:

#### Pathway A — Self-Report via WhatsApp
1. Guard sends a message containing keywords: `হাজির`, `উপস্থিত`, `present`, `on duty`, `check in`, `checked in`, etc.
2. `modules/attendance/is_attendance_message()` returns `True`
3. `handle_attendance_message()`:
   - Looks up `fazle_employees_legacy` by `employee_mobile` (tries both `0X` and `880X` formats)
   - Extracts status (Present/Absent) and optional location from message
   - Creates a draft in `fazle_draft_replies` (intent='attendance')
   - Sends draft text to admin for approval
4. Admin sends `APPROVE <draft_id>` → `save_attendance()` writes row to `wbom_attendance`

#### Pathway B — Escort Lifecycle Auto-Backfill
When a program closes (`status → Completed`):
- `backfill_attendance_for_program()` loops through every day from `program_date` to `end_date`
- Inserts `Present` for each day with `recorded_by='escort-lifecycle'`
- Uses `ON CONFLICT DO NOTHING` — does not overwrite manually-recorded rows

#### Pathway C — Supervisor Bulk Report
A supervisor sends a formatted attendance list.  
`modules/attendance_parser/` parses it and calls `save_supervisor_attendance()` after admin approval.

#### Attendance Record Fields
- `status`: Present / Absent / Leave / Half-day
- `location`: site name, or vessel name from escort program
- `recorded_by`: who created the record ('escort-lifecycle', supervisor phone, admin phone)
- UNIQUE constraint on `(employee_id, attendance_date)` prevents duplicate daily entries

#### Dashboard View
The **Attendance tab** in the dashboard queries `wbom_attendance` filtered by date range and/or employee. Shows daily status grid per employee.

---

## 13. Admin-Accountant Conversation Flow

This is the payment notification chain that happens after admin approves a payment.

### Full Flow
```
Guard/Employee (WhatsApp)
      │
      │ [release / advance request]
      ▼
Fazle Core (process_message)
      │ creates draft in fazle_payment_drafts
      ▼
Admin (WhatsApp — Bridge1/Bridge2)
      │ receives draft text
      │
      │ PAID <id> <amount> <method>    ← for escort payment
      │ ADVANCE <id> <amount> <method> ← for advance
      ▼
process_admin_command() → _cmd_paid()
      │
      ├─ finalize_payment()
      │    ├─ INSERT fazle_cash_transactions_archive
      │    │    (employee_id, amount, type, method, "Draft #N — approved by admin")
      │    ├─ UPDATE fazle_payment_drafts SET status='sent', accountant_msg=...
      │    └─ returns accountant_msg (formatted Bengali text)
      │
      ▼
Accountant (WhatsApp — typically Bridge1/Bridge2)
      receives:
      💳 পেমেন্ট নির্দেশনা
      কর্মী: [name]
      মোবাইল: [phone]
      পরিমাণ: ৳X,XXX
      পদ্ধতি: Bkash/Nagad/Cash
      ধরন: এস্কর্ট পেমেন্ট / অগ্রিম
      Draft: #ID
```

### Key Points
- The accountant's phone is identified via `fazle_contact_roles` seed rule (role=`accountant`)
- The accountant receives formatted payment instructions; they then physically execute the Bkash/Nagad/cash transfer
- The `accountant_msg` is stored in `fazle_payment_drafts.accountant_msg` for audit
- Every payment is recorded in `fazle_cash_transactions_archive` **before** the accountant message is sent

### Accountant Inbound Messages
When the accountant messages back, the router (`message_router`) identifies them as `accountant` role and routes to:
- `knowledge_base.get_reply()` for FAQ-type queries
- AI (`ollama`) for general queries
- They can also use admin commands if granted `operator` or `accountant` RBAC role

---

## 14. Employee Advance Request Flow

### Detection
`modules/payment_workflow/is_advance_request()` detects keywords:
```
Bengali: অগ্রিম, অগ্রীম, আগাম, টাকা দরকার, টাকা লাগবে, বেতন আগে, দেন ভাই…
English: advance, cash advance, need money, loan…
```

### Processing (Employee sends advance request)
1. Message detected as `advance_request` intent
2. `modules/employee_verification` may run to confirm employee identity
3. `create_advance_request_draft()` assembles context:
   - Fetches `fazle_employees_legacy` for name, mobile, bkash_number, basic_salary
   - Queries `fazle_cash_transactions_archive` for `paid_this_month` (SUM for current month)
   - Queries `wbom_escort_programs` for `active_duties` count
4. Draft saved to `fazle_payment_drafts` (type='advance'):
   ```
   💰 অগ্রিম পেমেন্ট রিকোয়েস্ট:
   কর্মী: [name]
   মোবাইল: [phone]
   চাওয়া পরিমাণ: ৳X,XXX / অনির্দিষ্ট
   এই মাসে পেয়েছে: ৳X,XXX
   সক্রিয় ডিউটি: X
   বিকাশ/নগদ: [number]

   ✅ অনুমোদন দিতে: ADVANCE <id> <পরিমাণ> bkash/nagad/cash
   🚫 বাতিল করতে: REJECT <id>
   ```
5. Draft sent to admin for review

### Admin Approves
Admin sends: `ADVANCE <draft_id> <amount> bkash`

`finalize_payment()` is called:
- `txn_type = 'advance'`
- `INSERT INTO fazle_cash_transactions_archive` with `transaction_type='advance'`
- `UPDATE fazle_payment_drafts SET status='sent'`
- Accountant notification sent

### How Advances Affect Salary
In `payroll.compute_run()`:
```python
advances = SUM(fazle_cash_transactions_archive.amount)
           WHERE employee_id=$1 AND transaction_type='advance'
           AND transaction_date BETWEEN period_start AND period_end

net_salary = max(gross_salary - total_advances, 0)
```
An `advance` component line item is also inserted into `wbom_payroll_run_items` with sign=`'-'` for transparency.

---

## 15. How Data Flows to the Frontend

### Transactions Tab
- API: `GET /transactions?page=1&limit=50&employee_id=X&date_from=...`
- DB query: `SELECT * FROM fazle_cash_transactions_archive LEFT JOIN fazle_employees_legacy ...`
- Shows: transaction_date, employee_name, transaction_type, amount, payment_method, status, remarks

### Employees Tab
- API: `GET /employees`
- DB query: `SELECT * FROM fazle_employees_legacy ORDER BY employee_name`
- Shows: ID, name, designation, mobile, bkash_number, basic_salary, status

### Draft Approval Actions
- Dashboard Drafts tab has inline **Approve** / **Reject** buttons
- POST to `/drafts/{id}/approve` or `/drafts/{id}/reject`
- Triggers same logic as WhatsApp `APPROVE <id>` command

---

## 16. RBAC Roles & Permissions

| Role | Level | Key Permissions |
|---|---|---|
| `viewer` | 1 | Read-only: status, reports, backup list, payroll list |
| `operator` | 2 | approve, reject, edit drafts, paid, advance, release, escortconfirm |
| `accountant` | 3 | payimport, payroll_compute, payroll transitions, payroll_paid |
| `admin` | 4 | schedule_run, backup_now, user_list |
| `superadmin` | 5 | user_add, user_role, user_remove, user_apikey |

All commands are audited in `fazle_admin_audit`. Phones in env `ADMIN_NUMBERS` are auto-bootstrapped as `superadmin`.

---

## 17. Safe Mode

`AUTO_REPLY_ENABLED=false` (default in production) means:
- All outbound replies are **suppressed** and saved as drafts in `fazle_draft_replies`
- Admin `APPROVE <id>` is the only way to send a message to an external party
- **Exception**: Recruitment auto-replies bypass safe mode when `RECRUITMENT_AUTOREPLY_ENABLED=true`
- Admin commands still execute fully (PAID, ADVANCE etc.) even in safe mode

---

## 18. Payment Correction (Batch 28)

Admin commands for after-the-fact corrections:

```
REVERSE <draft_id> <reason>
→ Inserts a negative fazle_cash_transactions_archive row (is_reversal=True, reversal_of=original_id)
→ Updates original draft status to 'reversed'

ADJUST <draft_id> <new_amount> <method> [reason]
→ REVERSE the original + create a new corrected fazle_cash_transactions_archive row
→ Updates draft with new approved_amount
```

---

## 19. Key External Service Ports Summary

| Service | Port | Description |
|---|---|---|
| **Fazle Core** | **8200** | Main FastAPI app (localhost only) |
| Bridge 1 (HR) | 8080 | Go WhatsApp bridge — number 8801958122300 |
| Bridge 2 (OPS) | 8081 | Go WhatsApp bridge — number 8801880446111 |
| Ollama (LLM) | 11434 | Local AI — model qwen2.5:3b |
| Media Processor | 8090 | OCR & media extraction service |
| Redis | 6379 | Outbound message queue (DB 9) |
| PostgreSQL | 5432 | ai-postgres container, database: postgres |
| Fazle Agent | 8300 | NL admin query agent (separate process) |

---

## 20. End-to-End Data Flow Diagram

```
WhatsApp User
    │
    ▼
Bridge1/Bridge2/Meta (webhook)
    │
    ▼
app/main.py (dedup → save_message → _process_message)
    │
    ▼
modules/message_router/process_message()
    │
    ├─ detect_identity()
    │    └─ fazle_contact_roles → fazle_employees_legacy → fazle_contacts → text_hint
    │
    ├─ [escort_client] → modules/escort → wbom_escort_programs (draft)
    │                                   → fazle_draft_replies (admin notif)
    │
    ├─ [admin]         → modules/fazle_admin_commands → 
    │                    APPROVE → fazle_draft_replies(sent) → delivery
    │                    PAID/ADVANCE → fazle_cash_transactions_archive
    │                                 → fazle_payment_drafts(sent)
    │                                 → accountant notification
    │                    RELEASE → wbom_escort_programs(Completed)
    │                            → wbom_attendance (backfill)
    │                            → fazle_payment_drafts (payment draft)
    │                    PAYROLL COMPUTE → wbom_payroll_runs + items
    │
    ├─ [employee/guard] → attendance module → fazle_draft_replies
    │                  → advance request → fazle_payment_drafts
    │                  → release message → escort_lifecycle
    │
    └─ [unknown/candidate] → recruitment_flow → fazle_recruitment_sessions
                           → knowledge_base → reply
                           → Ollama AI → reply
    │
    ▼
Reply saved to fazle_draft_replies (SAFE MODE) OR sent immediately
```

---

*Report generated by deep codebase analysis — 2026-05-06. No code was modified.*
