# Phase 1 — Push #2 Notes (N-Bridge Poller + Full Identifier Capture)

**Push:** Poller now loops over *any* number of bridges, and every message is fully identified.

## What changed (this push)
- `modules/fazle_bridge_poller/__init__.py`:
  - `_get_dynamic_bridge_configs()` — reads `whatsapp_bridges` registry (DB) → `BRIDGE_REGISTRY_JSON` env → legacy `BRIDGE_CONFIGS` fallback. Zero breaking change.
  - `start_pollers()` now uses dynamic list, skips webhook-only bridges (no `messages_db`), logs count + names.
  - `_enrich_core_with_identifiers()` — after each `INSERT` into `fazle_whatsapp_messages`, populating new 098 columns: `wa_message_id`, `wa_jid`, `wa_lid`, `wa_pn`, `group_jid`, `media_type`, `media_path`, `call_status`, `bridge_id_ref`, `raw_json`. Schema-tolerant (checks `information_schema` before UPDATE).
  - `modules.whatsapp_mcp.identifier.parse_identifier()` used for canonical JID/LID/PN derivation.
  - `_detect_call_status()` — captures `call` / `missed_call` from `media_type` or content.
- `examples/whatsapp_mcp_send.py` — one-command send demo (HTTP vs direct), plus identifier extraction demo.

## How to verify
```bash
# 1) Check identifier demo
python examples/whatsapp_mcp_send.py --demo-identifiers

# 2) Start app — see dynamic bridges in log
python run.py
# log: [whatsapp_mcp] registry ready (from=db, count=2) / Bridge pollers running for 2 bridge(s): ['wa-hr', 'wa-ops']

# 3) Send via MCP
curl -s -H "X-Internal-Key: $INTERNAL_API_KEY" -H Content-Type:application/json \
  -d '{"name":"whatsapp.send_message","arguments":{"to":"01710000001","message":"হ্যালো"}}' \
  http://127.0.0.1:8200/mcp/call | jq

# 4) List messages with new columns
curl -s -H "X-Internal-Key: $INTERNAL_API_KEY" \
  'http://127.0.0.1:8200/mcp/call' -d '{"name":"whatsapp.get_messages","arguments":{"limit":5}}' | jq
# expect wa_jid, group_jid, media_type, call_status, bridge_id_ref filled

# 5) Check group messages are persisted (read-only, never routed)
curl -s -H "X-Internal-Key: $INTERNAL_API_KEY" \
  'http://127.0.0.1:8200/api/bridges' | jq
```

## Next push (Push #3 — History Sync)
- `modules/whatsapp_mcp/sync.py` full bulk copy: SQLite `messages` → `fazle_whatsapp_messages`, chunked 1000, dedup by `wa_message_id+bridge_id`, progress via `bridge_sync_state`.
- `POST /api/bridges/{id}/sync/history?with_media=true` triggers it, `GET .../sync/status` polls.
- UI: progress bar in `app/static/wa-bridges.html`.

## Compatibility
- Old DBs without 098 columns: enrichment silently skips (no crash).
- Old .env with only BRIDGE1/2: registry falls back to `BRIDGE_CONFIGS` (3 bridges).
- No change to routing/RBAC — only persistence enriched.
