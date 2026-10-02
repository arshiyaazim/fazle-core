# Fazle Core

**Repository:** <https://github.com/arshiyaazim/fazle-core><br>
**Documentation reviewed:** 2026-10-02

Fazle Core is a Python/FastAPI operations backend for a WhatsApp-first security,
recruitment, payroll, and vessel-escort business. It integrates WhatsApp and
Meta message channels with operator dashboards, PostgreSQL-backed workflows,
and AI-assisted search and reply drafting. It is company-specific software,
not a general chatbot platform.

This repository contains the application and its integrations. It does **not**
bundle or install production databases, WhatsApp bridge binaries, AI gateways,
model weights, or other separately operated services.

## What the application does

- Ingests messages from external WhatsApp bridges and Meta webhooks, resolves
  sender identity, and routes work to recruitment, escort, payment, attendance,
  and admin workflows.
- Supports the Fazle Payroll Engine (FPE), employee lookup, payment and income
  tracking, reconciliation, and review queues. `fpe_cash_transactions` is the
  canonical cash ledger; `wbom_cash_transactions` is legacy and must not receive
  new writes.
- Provides escort intake, roster and dispatch-related views, slip review,
  payment drafts, and client-billing profile/payment-tracking workflows.
- Serves operator dashboards, reply and payment-draft review, knowledge-base
  management, and the AI chat console.
- Provides retrieval (BM25/RAG), read-oriented business tools, scheduled jobs,
  backups, health checks, and observability endpoints.

The application supports pieces of these business domains; it is not a
double-entry general ledger or a complete ERP. Financial and outbound actions
must continue to follow the code's authorization and review paths.

## Architecture and service boundaries

`app/main.py` composes the FastAPI application and starts its database pool,
pollers, workers, scheduler, and other in-process components. Business logic is
organized under `modules/`; shared runtime and policy helpers live under
`shared/`. The application uses raw SQL through `asyncpg` (no ORM).

| Component | Relationship to this repository |
|---|---|
| PostgreSQL | Required application database. Connection is configured with `DATABASE_URL`. |
| Redis | Supporting service used by queue/runtime helpers; configured with `REDIS_URL`. |
| Qdrant | Optional external vector service for RAG. The RAG module also supports an embedded local store; availability and configuration affect vector search. |
| WhatsApp bridges 1–3 | Separate services/binaries with their own WhatsApp sessions and SQLite stores. This repository contains pollers, webhook handling, and send integrations—not the bridge binaries or their session data. |
| Meta APIs | External webhook and messaging APIs; credentials and Meta-side configuration are not included. |
| Ollama and models | Ollama is a separately installed runtime. Model weights are not in this repository and must already be available to Ollama. The configured local default is `hermes3:3b`. |
| OmniRoute and Groq | Optional provider integrations. OmniRoute is an external OpenAI-compatible gateway; Groq is a cloud provider. Their credentials are not included. |
| 9Router | Separate gateway with a gated, development-oriented routing path; it is not the normal reply-provider chain and is not enabled by this repository alone. |
| Hermes runner | Optional, separately installed service for the explicit admin `HERMES` relay. It is distinct from the local Ollama model and is disabled until separately configured. |
| Media processor | Optional external service used by media/OCR/voice integrations. |

Conversational reply generation currently follows the configured provider path
in `app/llm.py`: OmniRoute, Groq, local Ollama/Hermes, then Kimi through the
Ollama client. Providers without credentials or an available service are
skipped or fall through. Other workloads (such as intent classification and
chat) have separate handling; `PRIMARY_AI_PROVIDER` is retained for
compatibility and does not override the reply chain. Check the workload's code
before changing provider settings. The 9Router path requires additional
database-backed route configuration and its single-upstream-attempt guarantee.

## Database and migrations

`DATABASE_URL` must point to a PostgreSQL database with the schema expected by
the application. The main migration path for new schema changes is
[`db/migrations/`](db/migrations/), managed by [`db/migrate.py`](db/migrate.py).
[`db/MIGRATION_INVENTORY.md`](db/MIGRATION_INVENTORY.md) documents migration
sources and known history/tracking gaps. Application startup does not replace
reviewing and applying migrations: use an isolated development/test database,
inspect the migration and its impact, and follow the inventory and operations
guidance before applying it.

## Dependencies and separately operated applications

### Python dependencies

Runtime dependencies are pinned or bounded in [`requirements.txt`](requirements.txt):
FastAPI/Uvicorn, Pydantic Settings, asyncpg, HTTPX, cryptography, multipart
handling, RapidFuzz, dotenv loading, PyMuPDF, python-docx, Pillow, Qdrant
client, and Sentence Transformers. Test and browser dependencies are listed
separately in [`tests/requirements-test.txt`](tests/requirements-test.txt).

Install runtime and test dependencies with:

```bash
python -m pip install -r requirements.txt
python -m pip install -r tests/requirements-test.txt
```

### External services

These applications are not vendored in this repository and must be installed,
configured, authenticated, and maintained independently:

- PostgreSQL and Redis are required for a complete deployment. Qdrant is
  optional unless hybrid/vector RAG is enabled.
- The WhatsApp MCP/bridge server must be checked out or installed separately.
  It owns WhatsApp sessions, QR pairing, ports, SQLite stores, and its own
  service units. Configure its three URLs and store paths in `.env` only after
  its ports and directories are confirmed.
- Ollama is a separately installed local model runtime. After installing it,
  start the daemon and pull the model named by `OLLAMA_MODEL`, for example:

  ```bash
  ollama serve
  ollama pull hermes3:3b
  ollama list
  ```

  On Windows, install Ollama using its official installer and keep
  `OLLAMA_URL=http://127.0.0.1:11434`. On Linux, use the official Ollama
  installer and run it as its own service; do not expose port 11434 publicly.
- Hermes and `hermes-runner` are separate applications with their own model,
  web UI, MCP configuration, and login/authentication. Configure
  `HERMES_RUNNER_URL` plus the two distinct Core-to-Hermes secrets only after
  the runner is protected on loopback or behind an authenticated reverse
  proxy. The repository includes the one-time Core identity helper
  [`scripts/create_hermes_mcp_admin.py`](scripts/create_hermes_mcp_admin.py).
- OmniRoute is a separate OpenAI-compatible gateway. `OMNIROUTE_URL` and
  `OMNIROUTE_API_KEY` authenticate Core's provider calls; they do not log a
  user into an OmniRoute web interface.

### Customer messaging provider profile

Recruitment and verified employee informational messages use the existing
identity, recent-history, knowledge-base, and policy pipeline. Employee
attendance-history questions use a sender-resolved, read-only attendance
query; attendance submissions continue through the existing draft workflow.
The model never receives unrestricted database credentials or another
employee's records.

For the recommended local-backup profile, configure the real `.env` as:

```env
OMNIROUTE_API_KEY=<real-key-when-available>
GROQ_API_KEY=
GROQ_FALLBACK_ENABLED=false
OLLAMA_REPLY_DISABLED=false
UNIFIED_AI_ROUTING_ENABLED=false
```

The reply chain is then OmniRoute → local Ollama. Missing OmniRoute
credentials, gateway errors, timeouts, rate limits, or exhausted credits
fall through to Ollama. Hermes customer dispatch remains separately
feature-flagged and, when enabled, receives only the already prepared
identity-scoped context. Do not expose Ollama, OmniRoute, Hermes, PostgreSQL,
Redis, or Qdrant publicly.

The optional read-only AI database setup uses `FAZLE_AI_READER_DB_URL` and
`FAZLE_AI_READER_PASSWORD`; the memory database uses
`OLLAMA_MEMORY_DB_URL` and `OLLAMA_MEMORY_OWNER_PASSWORD`. These are not
needed for the core employee identity/payroll query path, but are required
when the read-only AI tools are enabled.

### Vessel Register read-only connection

The Vessel Register Site can consume Core's canonical records through its
server-side `/api/core` proxy. Core exposes the existing read-only FPE GET
contract for health, transactions, employee search, unmatched/review data, and
pipeline statistics. A privately configured `FAZLE_CORE_READ_KEY` is accepted
only by those read-scoped GET routes; it is not accepted by mutation, send,
admin, or maintenance routes. Browser identity headers and `sender_role` are
never trusted as authorization.

The message router's optional operational context is read from Core's own
PostgreSQL `wbom_escort_programs` records. It does not call the Site, write
records, enqueue WhatsApp messages, post a ledger transaction, or treat a
draft preview as approved/sent. Ambiguous vessel matches are omitted so the
conversation can request confirmation.

The detailed local/preview contract is documented in
[`docs/VESSEL_REGISTER_READONLY_INTEGRATION.md`](docs/VESSEL_REGISTER_READONLY_INTEGRATION.md).

Do not copy credentials from any of these services into `.env.example`.

## Local desktop installation

The application has no frontend build step; FastAPI serves the static pages
directly. Use a dedicated development database and local-only keys.

### Windows PowerShell

```powershell
git clone https://github.com/arshiyaazim/fazle-core.git
Set-Location fazle-core
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python db\migrate.py --dry-run
python db\migrate.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8200 --reload
```

Before starting, edit `.env` with a reachable local PostgreSQL database,
`INTERNAL_API_KEY`, and any optional service URLs. Keep `AUTO_REPLY_ENABLED`
and `RECRUITMENT_AUTOREPLY_ENABLED` disabled for local work unless the test
explicitly requires outbound behavior.

### Linux/macOS/WSL

```bash
git clone https://github.com/arshiyaazim/fazle-core.git
cd fazle-core
python3 -m venv .venv
source .venv/bin/activate
cp .env.example .env
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python db/migrate.py --dry-run
python db/migrate.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8200 --reload
```

The migration runner applies all unapplied SQL files in
[`db/migrations/`](db/migrations/) and records them in `schema_migrations`.
Only run it against the intended development database.

## VPS installation and service deployment

The production system is intended to run on a Linux VPS as the unprivileged
`azim` user, with Nginx terminating public TLS and Fazle Core bound to
`127.0.0.1:8200`. The checked-in service unit currently uses `/home/azim/core`
and `/home/azim/.venv`; use those paths consistently on a new deployment.
The older `install.sh` assumes `/home/azim/fazle-core` and is not a drop-in
replacement for the current service unit.

On a fresh VPS, after installing system packages such as Python, PostgreSQL
client tools, Git, Redis, and Nginx:

```bash
sudo -u azim git clone https://github.com/arshiyaazim/fazle-core.git /home/azim/core
sudo -u azim python3 -m venv /home/azim/.venv
sudo -u azim /home/azim/.venv/bin/pip install --upgrade pip
sudo -u azim /home/azim/.venv/bin/pip install -r /home/azim/core/requirements.txt
sudo -u azim cp /home/azim/core/.env.example /home/azim/core/.env
sudo chmod 600 /home/azim/core/.env
sudo -u azim /home/azim/.venv/bin/python /home/azim/core/db/migrate.py --dry-run
sudo -u azim /home/azim/.venv/bin/python /home/azim/core/db/migrate.py
sudo cp /home/azim/core/fazle-core.service /etc/systemd/system/fazle-core.service
sudo systemctl daemon-reload
sudo systemctl enable --now fazle-core.service
curl -fsS http://127.0.0.1:8200/health
```

Edit `/home/azim/core/.env` before the migration/start steps. For production,
store sensitive values in the approved secure environment layer where used by
the VPS, keep database credentials out of Git, and confirm the database backup
and migration state before restarting. See [`docs/OPERATIONS.md`](docs/OPERATIONS.md)
for status, logs, backups, monitoring, and restart procedures. Do not run
`sudo systemctl restart` merely because a file changed; a production restart
requires the deployment/restart gate.

### VPS external applications

Install PostgreSQL/Redis/Qdrant, the WhatsApp MCP/bridge services, Ollama,
OmniRoute, and Hermes using their own deployment sources and service units.
Confirm each service locally before connecting it to Fazle Core:

```bash
curl -fsS http://127.0.0.1:11434/api/tags       # Ollama
curl -fsS http://127.0.0.1:20128/v1/models      # OmniRoute, if enabled
curl -fsS http://127.0.0.1:8093/health          # Hermes runner, if supported
curl -fsS http://127.0.0.1:8081/health          # bridge example
```

The exact WhatsApp MCP and Hermes installation commands are intentionally not
invented here: their source repositories, binary names, ports, and service
units are external to this repository and must match the deployed version.
Keep all of them loopback-only unless Nginx adds explicit authentication and
rate limiting.

## Local development

### Prerequisites

- Python 3 and the packages pinned/listed in `requirements.txt`.
- A dedicated local PostgreSQL database with the expected schema.
- Redis if you need queue/runtime features that depend on it.
- Optional, separately run services for the integrations you are developing
  (for example bridges, Ollama, Qdrant, or the media processor).

The root [`.env.example`](.env.example) lists the small set of useful local
settings. Copy it to `.env`, replace the database URL and API-key placeholder,
and keep `.env` local. Its reply switches are deliberately safe for development.
`ADMIN_NUMBERS` can bootstrap listed numbers as superadmins, so leave it blank
unless you are using a disposable local database and intentionally want that
behavior.

Create a virtual environment, install dependencies, and start the API:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8200 --reload
```

On Linux/macOS/WSL, activate with `source .venv/bin/activate` and copy the
example with `cp .env.example .env`. Set up PostgreSQL and any optional
supporting services separately; this command does not install or start them.
The application serves directly from the source tree and has no frontend build
step.

[`install.sh`](install.sh) is **not** a cross-platform development installer:
it hard-codes a production Linux path, uses `sudo` to install/enable a systemd
unit, and restarts the service. Do not run it as a local setup shortcut.
Production deployment and restart procedures are in
[`docs/OPERATIONS.md`](docs/OPERATIONS.md) and
[`docs/DEPLOYMENT_RESTART_GATE.md`](docs/DEPLOYMENT_RESTART_GATE.md).

## Local URLs

With the development command above:

| URL | Page |
|---|---|
| <http://127.0.0.1:8200/> | Main dashboard |
| <http://127.0.0.1:8200/payroll> | Payroll/FPE |
| <http://127.0.0.1:8200/escort-roster> | Escort roster |
| <http://127.0.0.1:8200/dispatch> | Dispatch views |
| <http://127.0.0.1:8200/drafts> | Reply drafts |
| <http://127.0.0.1:8200/kb> | Knowledge-base management |
| <http://127.0.0.1:8200/chat-lab> | AI chat console |
| <http://127.0.0.1:8200/wa-chat> | WhatsApp workspace |
| <http://127.0.0.1:8200/health> | Basic health check |
| <http://127.0.0.1:8200/docs> | Local interactive API docs |

Most admin and mutation APIs require `X-Internal-Key`; some operations also
apply role checks backed by the database. The documented production Nginx
configuration proxies the app at `https://fazle.iamazim.com` and blocks
`/docs` and `/openapi.json`; the actual public host depends on deployment
configuration.

## Admin account setup and authentication

Admin web pages can authenticate with either the privileged internal API key or
an admin username/password. Password login is exchanged for a login token; the
password and token are stored as hashes in `fazle_admins`.
There is no supported `ADMIN_USERNAME` or `ADMIN_PASSWORD` environment
variable.

For a fresh local or VPS database:

1. Set a unique `INTERNAL_API_KEY` and, only when intentionally bootstrapping,
   list the owner phone number in `ADMIN_NUMBERS`.
2. Apply migrations and start Fazle Core.
3. Use the authenticated admin user-management flow from the Payroll/Admin
   page, or the protected `/admin/users` API, to set the admin name, username,
   password, phone, and role.
4. Sign in at `/payroll` or another Fazle Core admin page using that username
   and password, then remove any temporary bootstrap values that are no longer
   required.

OmniRoute, Ollama, Hermes, and WhatsApp MCP/bridge interfaces are separate
applications. A Fazle Core login does not authenticate those UIs; protect each
one independently and keep its raw service port on loopback or behind an
authenticated reverse proxy.

## Safety and authorization

- `AUTO_REPLY_ENABLED` defaults to `false`. The code has a separate
  `RECRUITMENT_AUTOREPLY_ENABLED` exception, so keep both disabled during local
  development unless testing that behavior intentionally.
- `INTERNAL_API_KEY` is privileged. Do not reuse a production key locally or
  publish it. Authenticated operator keys and role assignments are managed
  through the application and database; roles are not a hardcoded role list.
- Admin username/password login is handled by `/api/admin/login`; the password
  hash and login-token hash live in `fazle_admins`. Do not add admin credentials
  to `.env.example` or commit them to `.env`.
- Admin pages may share Fazle Core's session/token flow, but OmniRoute, Ollama,
  Hermes, and the WhatsApp MCP/bridge UIs are separate applications. Configure
  authentication for each service independently and do not expose their raw
  ports publicly.
- Keep financial writes on the canonical FPE paths, preserve audit/review
  behavior, and do not add a second cash-ledger writer.
- Treat model output and inbound message content as untrusted. AI assistance
  does not replace application authorization or human approval for sensitive
  operations.
- Never commit `.env`, credentials, tokens, private database URLs, or live
  WhatsApp/session data.

## Testing

Install test dependencies with:

```sh
python -m pip install -r tests/requirements-test.txt
```

On a POSIX-compatible shell (including WSL), run the fast unit suite with
`make test-unit`. Integration/database tests need a dedicated test database;
the test Compose configuration requires `TEST_DB_PASSWORD` and binds its
database to loopback. **Never run `tests/e2e/` in the same pytest process as
other test directories**; the test collection hook enforces this isolation.
See the [developer guide](docs/DEVELOPER_GUIDE.md) for test-suite details.

## Further documentation

| Document | Use it for |
|---|---|
| [`SYSTEM_ATLAS.md`](SYSTEM_ATLAS.md) | Project orientation and canonical document map |
| [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) | Runtime, frontend, workflow, AI, and testing details |
| [`docs/MODULE_MAP.md`](docs/MODULE_MAP.md) | Module responsibilities, routes, tables, and dependencies |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Component and message-flow architecture |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | Production services, monitoring, and operations |
| [`docs/DEPLOYMENT_RESTART_GATE.md`](docs/DEPLOYMENT_RESTART_GATE.md) | Production restart safety gate |
| [`db/MIGRATION_INVENTORY.md`](db/MIGRATION_INVENTORY.md) | Migration sources and governance |
| [`knowledge_base/00_governance/CANONICAL_BUSINESS_RULES.md`](knowledge_base/00_governance/CANONICAL_BUSINESS_RULES.md) | Canonical business naming and workflow rules |
| [`BUSINESS-CONSTITUTION.md`](BUSINESS-CONSTITUTION.md) | Financial and architectural invariants |
