# Universal Installer & WhatsApp MCP Bridge — Roadmap (ভাগে ভাগে)

> **উদ্দেশ্য:** Fazle Core যাতে যে কোনো PC / VPS এ `one-command install` করা যায়, এবং যে কোনো WhatsApp Bridge (1 বা একাধিক) এর সাথে plug-and-play কানেকশন নেয়া যায়।
> **Constraint:** পুরো রিপো একবারে অডিট সম্ভব না (tool/storage limit) — তাই 5 টা Phase এ ভাগ করে, প্রতি Phase শেষে `arena/2e22ee83-fazle-core` ব্রাঞ্চে push।

---

## বর্তমান অবস্থা (Audit 2026-11-06)

- **Hardcoded 3 bridge:** `bridge1_url/db_path`, `bridge2_...`, `bridge3_...` — `app/config.py:113-148`, `app/bridge.py` singleton `_bridge1/2/3`, `modules/fazle_bridge_poller/BRIDGE_CONFIGS` 3-item list।
- **SQLite poller:** `file:...?mode=ro` read-only, 5s interval, dedup via `processed_bridge_messages`, LID→PN resolve via `whatsapp.db` lid_map।
- **Identifier gap:** `fazle_whatsapp_messages` এ `source_bridge, recipient, phone` আছে, কিন্তু `jid, lid, pn, message_id, media_type, group_jid, is_call, call_status` আলাদা কলাম নেই — পার্সার নির্ভর।
- **Identity routing:** `fazle_identity_brain.detect_identity()` + `message_router.process_message()` — বর্তমানে `.env ADMIN_NUMBERS / critical_phone_set / fazle_contacts` নির্ভর, কাস্টমাইজ UI নেই।
- **Installer:** `install.sh` শুধু VPS (`/home/azim`) path hardcoded, generic না।

---

## Phase Plan — 5 ভাগ

### Phase 1 — Universal Bridge Registry & MCP Server (এই ব্রাঞ্চের প্রথম কাজ)
**Goal:** N-bridge support + MCP tooling। Hardcoded 3-bridge → dynamic registry।

#### Part 1A — Bridge Registry (DB + Config + API) — *এই push এ আছে*
- [ ] `db/migrations/098_universal_bridge_registry.sql` → `whatsapp_bridges` table (id, bridge_id, label, base_url, messages_db_path, whatsapp_db_path, phone_number, direction, enabled, priority, created_at)
- [ ] `app/config.py` → `BRIDGE_REGISTRY_JSON` env (JSON array) fallback to legacy bridge1/2/3 for backward compat + helper `get_bridge_configs()` 
- [ ] `modules/whatsapp_mcp/registry.py` → `BridgeRegistry` class (load from DB + env, CRUD, health probe)
- [ ] `modules/whatsapp_mcp/identifier.py` → canonical `WhatsAppIdentifier` dataclass (jid, lid, pn, phone_880, phone_01, group_jid, message_id, push_name, is_from_me, media_type, call_type, timestamp)
- [ ] `app/bridge.py` → `BridgeClientPool` (N clients, circuit breaker per bridge, `send_via_any()`)
- [ ] API: `GET /api/bridges`, `POST /api/bridges`, `PATCH /api/bridges/{id}`, `DELETE`, `POST /api/bridges/{id}/test`

#### Part 1B — MCP Server (Model Context Protocol)
- [ ] `modules/whatsapp_mcp/mcp_server.py` → MCP stdio/SSE server exposing tools:
  - `whatsapp.list_bridges` → all configured bridges + health
  - `whatsapp.send_message` → `{bridge_id?, jid, text, media_path?}` → Python one-liner + auto-JID build (`8801...@s.whatsapp.net` vs `@g.us`)
  - `whatsapp.get_messages` → `{bridge_id, chat_jid?, limit, media_type?}` 
  - `whatsapp.get_contact` → `{jid_or_phone}` → resolve LID/PN + display_name + identity_role
  - `whatsapp.get_call_log` → missed/call trace per bridge
  - `whatsapp.get_groups` → group list + participants
- [ ] `modules/whatsapp_mcp/tools.py` → tool schemas (JSON Schema) for Claude/LLM auto-call
- [ ] Frontend: `/wa-bridges.html` — bridge add/edit/test UI

#### Part 1C — Enhanced Message Ingest
- [ ] Expand `fazle_whatsapp_messages` via migration 099: add `wa_message_id, wa_jid, wa_lid, wa_pn, media_type, media_path, group_jid, call_status, raw_json`
- [ ] Update `fazle_bridge_poller` → loop over `BridgeRegistry.all_enabled()` instead of hardcoded 3, store full identifier per row
- [ ] Outbound: log `direction=outgoing, bridge_id, wa_message_id` same table

**Deliverable Phase 1:** যে কোনো PC তে `BRIDGE_REGISTRY_JSON='[{"bridge_id":"b1","base_url":"http://localhost:8082",...}]'` দিয়ে 1..N bridge চালু, MCP tool দিয়ে `python -m whatsapp_mcp send` + dashboard থেকে test।

---

### Phase 2 — History Sync & Canonical Store
- [ ] `modules/whatsapp_mcp/sync.py` → `HistorySyncService`: first-install bulk copy (SQLite `messages` → `fazle_whatsapp_messages`), chunked 1000 rows, progress API `POST /api/bridges/{id}/sync/history` + `GET /api/bridges/{id}/sync/status`
- [ ] Deduplication: `wa_message_id + bridge_id` unique, `processed_bridge_messages` reuse
- [ ] Incremental: poller cursor per bridge (`bridge_poller_cursor` already per-bridge)
- [ ] Media: optional `--with-media` flag → trigger `POST /api/download` per media message
- [ ] UI: sync progress bar + "Copy-Paste" fallback (dump .db upload → import)

---

### Phase 3 — Identity Customization (Multi-tenant-lite)
- [ ] Current: `ADMIN_NUMBERS, fazle_contacts, fazle_identity_brain` hardcoded to Al-Rifa'i. New org needs own numbers/contacts/domains.
- [ ] `modules/whatsapp_mcp/identity_customizer.py` + migration 100: `org_profiles` (org_name, admin_numbers[], accountant_phone, company_name, domain_rules JSON)
- [ ] UI: `/setup/identity` wizard — step 1: add your WhatsApp numbers, step 2: import contacts CSV, step 3: map roles (admin/operator/accountant/escort/client), step 4: choose which parser routes active (recruitment/escort/payment/attendance)
- [ ] `fazle_identity_brain` → read `org_profiles` first, fallback to `settings.ADMIN_NUMBERS` for backward compat
- [ ] Per-bridge identity: `whatsapp_bridges.owner_phone` → auto-tag `identity_source=bridge_owner`

---

### Phase 4 — Modular Parser Pipeline (Domain-based Extract)
- [ ] Extract current `message_router` domain routing into `modules/whatsapp_mcp/pipeline.py` → `MessagePipeline` (steps: intake → identify → normalize → ocr/voice → intent → domain dispatch)
- [ ] Each step is pluggable: `parsers/escort.py`, `parsers/payment.py`, `parsers/recruitment.py`, `parsers/attendance.py` — org can enable/disable per domain in `org_profiles.domain_rules`
- [ ] OCR/Voice hooks: `MEDIA_PROCESSOR_URL` already exists, wrap as `pipeline.media_enrich(msg) → text`
- [ ] Event: emit `whatsapp.message.enriched` with full `WhatsAppIdentifier + extracted_data`

---

### Phase 5 — Universal Installer (One-Command)
- [ ] `install.sh` → `scripts/install/universal_install.sh` — detect OS (Ubuntu/Debian/WSL/macOS), install docker/postgres/redis/ollama/venv, generic paths (`$HOME/fazle-core` not `/home/azim`), interactive `.env` wizard (asks DB_URL, INTERNAL_API_KEY, BRIDGE_REGISTRY_JSON, ADMIN_NUMBERS)
- [ ] `docker-compose.yml` (prod) — postgres + redis + app + optional bridges (mock for dev)
- [ ] `Makefile` targets: `make install`, `make migrate`, `make sync-history`, `make dev`
- [ ] Docs: `docs/INSTALL.md` (Bangla + English) — VPS vs local PC steps, bridge binary download links
- [ ] Health: `GET /health` already, add `/api/install/status` — checks DB, bridge reachability, identity setup completeness

---

## Push Strategy (Storage-safe)

প্রতি Part শেষে commit + push `arena/2e22ee83-fazle-core` → GitHub। বড় ফাইল (media, logs, .db) commit হবে না (`.gitignore`).

| Push # | Content | File count |
|--------|---------|------------|
| 1 (এইটা) | Roadmap + 098 migration + registry + identifier scaffold | ~6 |
| 2 | MCP server + tools + /api/bridges endpoints | ~4 |
| 3 | BridgeClientPool + poller N-loop + enhanced ingest | ~3 |
| 4 | History sync service + API | ~3 |
| 5 | Identity customizer + org_profiles | ~4 |
| 6 | Pipeline refactor + installer | ~5 |

> **প্রশ্ন আপনার জন্য:** একবারে করা যাবে না — ভাগ করতেই হবে। উপরের 5 Phase ক্রম ঠিক আছে? নাকি Phase 3 (Identity) আগে চান? জানালে পরের push সেই অনুযায়ী সাজাব।

---

## Compatibility Guarantee

- Legacy `BRIDGE1_URL/DB_PATH` env → auto-migrated to `whatsapp_bridges` rows on first boot (no breaking change for existing VPS).
- Existing `fazle_whatsapp_messages` data untouched — new columns nullable.
- `app/bridge.py:get_bridge1/2/3` kept as wrappers → `BridgeClientPool.get("bridge1")`.

## References

- Current bridge code: `app/bridge.py`, `modules/fazle_bridge_poller/__init__.py`, `shared/bridge_orchestrator.py`
- Identity: `modules/fazle_identity_brain/__init__.py`, `modules/number_identity/__init__.py`
- Config: `app/config.py`, `.env.example`, `fazle-core.service`
