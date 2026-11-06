# Fazle Core — Universal Install Guide

> **যে কোনো PC / VPS এ এক কমান্ডে ইনস্টল** — Ubuntu, Debian, WSL, macOS (brew).
> পুরনো `install.sh` (`/home/azim` hardcoded) এখন `scripts/install/universal_install.sh` এ generic করা হয়েছে।

---

## Quick Start (local PC / new VPS)

### 1) Clone
```bash
git clone https://github.com/arshiyaazim/fazle-core.git
cd fazle-core
git checkout arena/2e22ee83-fazle-core   # এই MCP/Universal branch (merge হলে main)
```

### 2) One-command install
```bash
bash scripts/install/universal_install.sh
# প্রশ্নগুলোর উত্তর দিন (DATABASE_URL, ADMIN_NUMBERS, BRIDGE_REGISTRY_JSON …)
# বা non-interactive:
# INTERNAL_API_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))') \
# ADMIN_NUMBERS=8801710000001 BRIDGE_REGISTRY_JSON='[{"bridge_id":"wa-hr","base_url":"http://localhost:8082","messages_db_path":"/home/me/whatsapp1/store/messages.db","phone_number":"8801710000001"}]' \
# bash scripts/install/universal_install.sh --yes
```

### 3) Run
```bash
# venv + native Postgres/Redis (ইনস্টলারে চেক করে)
venv/bin/python run.py
# → http://localhost:8200/

# অথবা Dockerে (postgres+redis auto)
docker-compose up -d
# logs: docker-compose logs -f app
```

### 4) Configure bridges + identity (browser)
```
http://localhost:8200/static/wa-bridges.html   — N bridge add/test/history-sync/send
http://localhost:8200/static/setup-identity.html — org name, admin numbers, contacts CSV
http://localhost:8200/                        — Admin Dashboard
```

---

## WhatsApp Bridge Setup (যে কোনো ব্রিজ, যে কোনো সংখ্যা)

### Option A — `BRIDGE_REGISTRY_JSON` (recommended for new installs)
`.env` এ এক লাইন:
```env
BRIDGE_REGISTRY_JSON='[{"bridge_id":"wa-hr","base_url":"http://localhost:8082","messages_db_path":"/home/azim/whatsapp1/store/messages.db","whatsapp_db_path":"/home/azim/whatsapp1/store/whatsapp.db","phone_number":"8801710000001","label":"HR"},{"bridge_id":"wa-ops","base_url":"http://localhost:8081","messages_db_path":"/home/azim/whatsapp2/store/messages.db","phone_number":"8801810000002","label":"OPS"}]'
# webhook-only bridge (no local DB, Meta webhook only):
# {"bridge_id":"meta","base_url":"https://graph.facebook.com","enabled":true}
```
- `bridge_id` — slug, unique (e.g. `wa-hr-01`)
- `base_url` — bridge HTTP (`/api/send`, `/api/download`, `/api/send-status`)
- `messages_db_path` — SQLite `messages.db` absolute path (খালি = webhook-only, poll skip)
- `phone_number` — that bridge's own WhatsApp number (880…)
- `direction` — `both`|`inbound`|`outbound` (default `both`)
- `priority` — low = preferred for outbound failover

Legacy `BRIDGE1_URL/DB_PATH` এখনো কাজ করে — প্রথম boot এ auto-seed হয়ে `whatsapp_bridges` টেবিলে যাবে।

### Option B — Dashboard UI
`wa-bridges.html` → ➕ Add Bridge → Test → Save

### Option C — API
```bash
curl -H "X-Internal-Key: $INTERNAL_API_KEY" -H Content-Type:application/json \
  -d '{"bridge_id":"wa-hr-01","base_url":"http://localhost:8082","messages_db_path":"/home/me/whatsapp1/store/messages.db","phone_number":"8801710000001"}' \
  http://localhost:8200/api/bridges
```

### Verify
```bash
curl -H "X-Internal-Key: $INTERNAL_API_KEY" http://localhost:8200/api/bridges
curl -H "X-Internal-Key: $INTERNAL_API_KEY" -X POST http://localhost:8200/api/bridges/wa-hr-01/test
```

---

## History Sync (প্রথম ইনস্টলে পুরনো মেসেজ কপি)

```bash
# Trigger (background, chunked 500)
curl -H "X-Internal-Key: $INTERNAL_API_KEY" -H Content-Type:application/json \
  -d '{"limit":5000}' http://localhost:8200/api/bridges/wa-hr-01/sync/history
# Poll progress
curl -H "X-Internal-Key: $INTERNAL_API_KEY" http://localhost:8200/api/bridges/wa-hr-01/sync/status
# বা UI: wa-bridges.html → History Sync → Sync Status
```
- প্রতিটি মেসেজে `wa_message_id, wa_jid, wa_lid, wa_pn, group_jid, media_type, call_status, bridge_id_ref` সেভ হয় — filtering via `whatsapp.get_messages`.
- webhook-only bridge → 0 row (expected).
- dedup: `message_hash` + `processed_bridge_messages` — দ্বিতীয়বার sync করলে skip।

---

## Identity Customization (নিজের নাম্বার/কন্টাক্ট)

অন্য প্রতিষ্ঠান/ব্যক্তি ব্যবহার করলে তাদের নিজস্ব নাম্বার/কন্টাক্ট ভিন্ন:

### UI (recommended)
`http://localhost:8200/static/setup-identity.html`
- Step 1: Org Name, Company Name, Admin Numbers (comma), Accountant Phone, bridge_owner_map, domain_rules (recruitment/escort/payment/attendance/rag toggles)
- Step 2: Contacts CSV (`phone,name,role` — e.g. `88017...,Rahim,admin`)
- Step 3: Verify → Effective Admins

### API
```bash
# Get/Set org profile
curl -H "X-Internal-Key: $INTERNAL_API_KEY" http://localhost:8200/api/org/profile
curl -H "X-Internal-Key: $INTERNAL_API_KEY" -H Content-Type:application/json \
  -d '{"org_name":"My Org","company_name":"My Company","admin_numbers":"8801710000001,8801810000002","domain_rules":{"recruitment":true,"escort":false}}' \
  http://localhost:8200/api/org/profile

# Import contacts CSV
curl -H "X-Internal-Key: $INTERNAL_API_KEY" -H Content-Type:application/json \
  -d '{"csv":"phone,name,role\n8801710000001,Rahim,admin\n8801710000002,Karim,employee"}' \
  http://localhost:8200/api/org/contacts/import

# Check which admins are effective
curl -H "X-Internal-Key: $INTERNAL_API_KEY" http://localhost:8200/api/org/effective-admins
```
`fazle_identity_brain.detect_identity()` এখন `org_profiles.admin_numbers` আগে দেখে, তারপর `.env ADMIN_NUMBERS` fallback — cache 30s।

---

## Auto Python Send (MCP)

### HTTP (any language)
```bash
curl -H "X-Internal-Key: $INTERNAL_API_KEY" -H Content-Type:application/json \
  -d '{"name":"whatsapp.send_message","arguments":{"to":"01710000001","message":"হ্যালো MCP"}}' \
  http://localhost:8200/mcp/call
# Group:  "to":"120363...@g.us"
# Media:  "media_path":"/path/photo.jpg"
```

### Python (inside venv)
```python
from modules.whatsapp_mcp.mcp_server import call_tool
res = await call_tool("whatsapp.send_message", {"to": "01710000001", "message": "হ্যালো"})
# or direct pool:
from modules.whatsapp_mcp.bridge_pool import get_pool
await get_pool().send_strict("wa-hr-01", "8801710000001@s.whatsapp.net", "হ্যালো")
```
Demo: `python examples/whatsapp_mcp_send.py --to 01710000001 --text "হ্যালো" --demo-identifiers`

### MCP tools list
```bash
curl -H "X-Internal-Key: $INTERNAL_API_KEY" http://localhost:8200/mcp/tools | jq .tools[].name
# whatsapp.list_bridges, send_message, get_messages, get_contact, get_call_log, get_groups, get_bridge_status, sync_history
```

### Message identifiers captured per row
`wa_message_id, wa_jid (@s.whatsapp.net), wa_lid, wa_pn, phone_880/phone_01, group_jid (@g.us), media_type (text/image/video/audio/document/call/missed_call), media_path, call_status, direction (inbound/outbound), bridge_id, timestamp, push_name`

Filter: `POST /mcp/call {"name":"whatsapp.get_messages","arguments":{"bridge_id":"wa-hr-01","media_type":"image","limit":20}}`

---

## VPS Deploy (systemd)

ইনস্টলার শেষে জিজ্ঞেস করবে — `y` দিলে:
```bash
sudo cp fazle-core.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fazle-core
journalctl -u fazle-core -f
sudo systemctl restart fazle-core  # after any .env/git change
```

`fazle-core.service` এখন `WorkingDirectory` + `EnvironmentFile` auto-patched to your clone path (not `/home/azim`).

Nginx example (`/etc/nginx/sites-enabled/fazle.iamazim.com.conf`):
```nginx
location / {
  proxy_pass http://127.0.0.1:8200;
  proxy_set_header Host $host;
}
# blocks /docs raw
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `DATABASE_URL` connection refused | `docker-compose up -d postgres` বা local Postgres start করুন; `psql $DATABASE_URL -c "select 1"` test |
| Bridge poller `messages.db not found` | path check: `ls -l $BRIDGE1_DB_PATH`; webhook-only হলে খালি রাখুন (poll skip, normal) |
| `LID unresolved: ...` warning | `whatsapp.db` path ভুল — `BRIDGE*_WHATSAPP_DB_PATH` ঠিক করুন |
| Admin not recognized | `setup-identity.html` এ admin_numbers সেট করুন বা `.env ADMIN_NUMBERS` চেক |
| History sync 0 rows | webhook-only bridge? DB path exists? `POST /api/bridges/{id}/test` দিয়ে path check |
| MCP 403 | `X-Internal-Key` must equal `INTERNAL_API_KEY` or per-admin key from `fazle_admins` |
| Port 8200 in use | `.env APP_PORT=8201` + `systemctl restart fazle-core` |

---

## Upgrade from old install (`/home/azim` VPS)

Legacy `.env` with `BRIDGE1_URL` etc. already works — first boot auto-seeds `whatsapp_bridges`. To move fully to new registry:

```bash
git pull origin main  # after merge
bash scripts/install/universal_install.sh  # will keep .env, patch service path
curl -H "X-Internal-Key: $INTERNAL_API_KEY" http://localhost:8200/api/bridges # verify seeded
# Optionally set BRIDGE_REGISTRY_JSON and delete old BRIDGE1 vars from .env
```

---

## File map for this feature

```
docker-compose.yml                          PC/VPS universal compose (postgres+redis+app)
scripts/install/universal_install.sh        one-command installer (OS detect + .env wizard)
docs/INSTALL.md                             this file
docs/UNIVERSAL_BRIDGE_MCP_ROADMAP.md        5-phase plan
docs/UNIVERSAL_BRIDGE_PHASE2_NOTES.md       Push #2 notes
app/static/wa-bridges.html                  N-bridge dashboard
app/static/setup-identity.html              identity wizard
modules/whatsapp_mcp/{registry,identifier,bridge_pool,mcp_server,sync,org_profile,router}.py
db/migrations/098_universal_bridge_registry.sql
db/migrations/099_org_profile_and_identity_customization.sql
examples/whatsapp_mcp_send.py                auto-send demo
```
