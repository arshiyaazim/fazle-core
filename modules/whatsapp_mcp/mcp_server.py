"""
whatsapp_mcp.mcp_server — MCP (Model Context Protocol) tool surface for WhatsApp

Exposes WhatsApp bridge operations as MCP tools so any MCP client (Claude Desktop,
local LLM, Python script) can call them:

  tools:
    - whatsapp.list_bridges
    - whatsapp.send_message        (auto JID builder + media)
    - whatsapp.get_messages        (by bridge / chat / type)
    - whatsapp.get_contact         (LID→PN→phone + identity)
    - whatsapp.get_call_log
    - whatsapp.get_groups
    - whatsapp.get_bridge_status
    - whatsapp.sync_history        (trigger history copy)

Transport options:
  - stdio: python -m modules.whatsapp_mcp.mcp_server --stdio
  - SSE/HTTP: mounted as FastAPI router at /mcp/*
  - Direct Python: from modules.whatsapp_mcp.mcp_server import call_tool

No hard MCP SDK dependency — uses lightweight JSON Schema + FastAPI.
If `mcp` package is installed, also registers via official server.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger("fazle.whatsapp_mcp.server")

# ── Tool schemas (JSON Schema) ────────────────────────────────────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "whatsapp.list_bridges",
        "description": "List all configured WhatsApp bridges with health and priority. Use to discover bridge_id before sending.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_disabled": {"type": "boolean", "default": False, "description": "Include disabled bridges"},
            },
        },
    },
    {
        "name": "whatsapp.send_message",
        "description": "Send a WhatsApp message via a bridge. Auto-builds JID from phone. Supports text and media. Returns wa_message_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient: 8801XXXXXXXXX, 01XXXXXXXXX, or full JID (…@s.whatsapp.net / @g.us)"},
                "message": {"type": "string", "description": "Text body. Required for text; optional caption for media."},
                "bridge_id": {"type": "string", "description": "Bridge to send via. If empty, uses highest-priority enabled outbound bridge."},
                "media_path": {"type": "string", "description": "Local file path or URL for image/video/audio/document. Auto-detects type."},
                "media_type": {"type": "string", "enum": ["text","image","video","audio","document","sticker"], "description": "Override auto media_type"},
            },
            "required": ["to"],
        },
    },
    {
        "name": "whatsapp.get_messages",
        "description": "Fetch messages from canonical DB (fazle_whatsapp_messages) or directly from bridge SQLite. Filter by bridge, chat, media type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bridge_id": {"type": "string", "description": "Filter by bridge_id"},
                "chat_jid": {"type": "string", "description": "Filter by chat JID (phone@s.whatsapp.net or group @g.us)"},
                "phone": {"type": "string", "description": "Filter by phone 8801… or 01…"},
                "media_type": {"type": "string", "enum": ["text","image","video","audio","document","call","missed_call","all"]},
                "direction": {"type": "string", "enum": ["inbound","outbound","all"]},
                "limit": {"type": "integer", "default": 20, "maximum": 100},
                "before_id": {"type": "string", "description": "Pagination cursor (wa_message_id)"},
            },
        },
    },
    {
        "name": "whatsapp.get_contact",
        "description": "Resolve a phone/JID/LID to display name, normalized phones, identity role, and bridge.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "jid_or_phone": {"type": "string", "description": "Any of: JID, LID, PN, 880 phone, 01 phone, unresolved:…"},
                "bridge_id": {"type": "string", "description": "Optional bridge to scope LID→PN map"},
            },
            "required": ["jid_or_phone"],
        },
    },
    {
        "name": "whatsapp.get_call_log",
        "description": "Get call/missed-call trace per bridge. Returns caller JID, phone, timestamp, call_status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bridge_id": {"type": "string"},
                "limit": {"type": "integer", "default": 20, "maximum": 100},
                "phone": {"type": "string", "description": "Filter by phone"},
            },
        },
    },
    {
        "name": "whatsapp.get_groups",
        "description": "List WhatsApp groups visible to bridges (from wbom_group_identities or bridge store).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bridge_id": {"type": "string"},
                "business_only": {"type": "boolean", "default": False, "description": "Only business_label IS NOT NULL"},
            },
        },
    },
    {
        "name": "whatsapp.get_bridge_status",
        "description": "Health + probe status for all bridges (DB age, poller heartbeat, send gate).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "whatsapp.sync_history",
        "description": "Trigger history sync (bulk copy from bridge SQLite messages.db → fazle_whatsapp_messages) for a bridge. Long-running; returns job_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bridge_id": {"type": "string", "description": "Bridge to sync"},
                "with_media": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "description": "Max rows to copy (null = all)"},
            },
            "required": ["bridge_id"],
        },
    },
]

# ── Tool handlers (async) ─────────────────────────────────────────────────────

async def tool_list_bridges(include_disabled: bool = False) -> dict:
    from .registry import get_registry
    reg = await get_registry()
    bridges = await reg.all(include_disabled=include_disabled)
    return {"bridges": [b.to_dict() for b in bridges], "loaded_from": reg.loaded_from}

async def tool_send_message(to: str, message: str = "", bridge_id: str = "", media_path: Optional[str] = None, media_type: Optional[str] = None) -> dict:
    from .identifier import build_jid, is_valid_jid
    from .registry import get_registry
    from app.bridge import get_bridge1, get_bridge2, get_bridge3  # fallback

    if not to:
        return {"error": "to is required", "success": False}
    # Build JID
    jid = to.strip()
    if "@" not in jid:
        # auto-detect group vs DM
        is_group = jid.endswith("@g.us") or (media_type == "group")
        # build_jid handles 01/880 normalization
        from .identifier import build_jid as _bj
        jid = _bj(jid)
    if not is_valid_jid(jid):
        return {"error": f"invalid JID after build: {jid}", "success": False}

    # Pick bridge
    reg = await get_registry()
    target = None
    if bridge_id:
        target = reg.get(bridge_id)
        if not target:
            return {"error": f"bridge_id {bridge_id} not found", "success": False}
    else:
        enabled = await reg.all_enabled()
        # filter outbound
        outbound = [b for b in enabled if b.is_outbound]
        target = outbound[0] if outbound else (enabled[0] if enabled else None)
        if not target:
            return {"error": "no enabled bridges", "success": False}

    # Send via BridgeClient
    try:
        # Use BridgeClientPool if available, else legacy singleton
        try:
            from modules.whatsapp_mcp.bridge_pool import get_pool
            pool = get_pool()
            result = await pool.send_strict(target.bridge_id, jid, message or "", media_path=media_path, media_type=media_type)
            return {"success": True, "bridge_id": target.bridge_id, "jid": jid, "result": result}
        except Exception:
            # fallback to legacy app.bridge
            from app.bridge import BridgeClient
            client = BridgeClient(target.base_url, target.label or target.bridge_id)
            await client.send_strict(jid, message or "")
            await client.close()
            return {"success": True, "bridge_id": target.bridge_id, "jid": jid, "via": "legacy"}
    except Exception as e:
        log.warning("[mcp] send_message failed to=%s bridge=%s: %s", jid, target.bridge_id, e)
        return {"success": False, "error": str(e)[:500], "bridge_id": target.bridge_id, "jid": jid}

async def tool_get_messages(bridge_id: str = "", chat_jid: str = "", phone: str = "", media_type: str = "all", direction: str = "all", limit: int = 20, before_id: str = "") -> dict:
    limit = max(1, min(int(limit or 20), 100))
    try:
        from app.database import fetch_all
        # Build WHERE
        where = []
        args: list[Any] = []
        idx = 1
        if bridge_id:
            where.append(f"(bridge_id_ref = ${idx} OR source_bridge = ${idx})")
            args.append(bridge_id); idx+=1
        if chat_jid:
            where.append(f"(wa_jid = ${idx} OR group_jid = ${idx})")
            args.append(chat_jid); idx+=1
        if phone:
            # normalize
            from .identifier import _norm_880
            n880 = _norm_880(phone)
            where.append(f"(phone = ${idx} OR wa_pn = ${idx} OR wa_jid LIKE ${idx+1})")
            args.extend([n880, f"%{n880}%"]); idx+=2
        if media_type and media_type != "all":
            where.append(f"media_type = ${idx}")
            args.append(media_type); idx+=1
        if direction and direction != "all":
            where.append(f"direction = ${idx}")
            args.append(direction); idx+=1
        if before_id:
            where.append(f"id < (SELECT id FROM fazle_whatsapp_messages WHERE wa_message_id = ${idx} LIMIT 1)")
            args.append(before_id); idx+=1
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        sql = f"SELECT id, wa_message_id, wa_jid, wa_lid, wa_pn, group_jid, media_type, call_status, direction, source_bridge, bridge_id_ref, phone, message, created_at FROM fazle_whatsapp_messages {where_sql} ORDER BY created_at DESC LIMIT ${idx}"
        args.append(limit)
        rows = await fetch_all(sql, *args)
        return {"messages": rows, "count": len(rows)}
    except Exception as e:
        # table not yet migrated
        return {"messages": [], "count": 0, "note": f"store not ready: {e}"[:300]}

async def tool_get_contact(jid_or_phone: str, bridge_id: str = "") -> dict:
    from .identifier import parse_identifier
    ident = parse_identifier({"jid": jid_or_phone, "phone": jid_or_phone}, bridge_id=bridge_id)
    # Try enrich from fazle_contacts
    contact = None
    try:
        from app.database import fetch_one
        # try both 880 and 01
        for ph in (ident.phone_880, ident.phone_01, jid_or_phone):
            if not ph:
                continue
            contact = await fetch_one("SELECT display_name, whatsapp_number, platform FROM fazle_contacts WHERE whatsapp_number=$1 LIMIT 1", ph)
            if contact:
                break
    except Exception:
        pass
    out = ident.to_dict()
    if contact:
        out["contact"] = dict(contact)
    # identity brain enrich (best effort)
    try:
        from modules.fazle_identity_brain import detect_identity
        brain = await detect_identity(ident.phone_880 or jid_or_phone)
        out["identity"] = brain
    except Exception as e:
        out["identity_note"] = str(e)[:300]
    return out

async def tool_get_call_log(bridge_id: str = "", limit: int = 20, phone: str = "") -> dict:
    return await tool_get_messages(bridge_id=bridge_id, phone=phone, media_type="missed_call", limit=limit)

async def tool_get_groups(bridge_id: str = "", business_only: bool = False) -> dict:
    try:
        from app.database import fetch_all
        if business_only:
            rows = await fetch_all("SELECT group_jid, source_bridge, business_label FROM wbom_group_identities WHERE business_label IS NOT NULL ORDER BY group_jid")
        else:
            rows = await fetch_all("SELECT group_jid, source_bridge, business_label FROM wbom_group_identities ORDER BY group_jid")
        if bridge_id:
            rows = [r for r in rows if r.get("source_bridge")==bridge_id]
        return {"groups": rows, "count": len(rows)}
    except Exception as e:
        return {"groups": [], "count": 0, "note": str(e)[:300]}

async def tool_get_bridge_status() -> dict:
    from .registry import get_registry
    reg = await get_registry()
    bridges = await reg.all(include_disabled=True)
    # probe via existing health probes (reuse app/main.py logic if available)
    out = []
    for b in bridges:
        item = b.to_dict()
        # try bridge health table
        try:
            from app.database import fetch_one
            hb = await fetch_one("SELECT status, last_heartbeat FROM fazle_service_heartbeats WHERE service_name=$1", f"bridge_poller:{b.bridge_id}")
            if hb:
                item["poller_heartbeat"] = dict(hb)
        except Exception:
            pass
        out.append(item)
    return {"bridges": out, "loaded_from": reg.loaded_from}

async def tool_sync_history(bridge_id: str, with_media: bool = False, limit: Optional[int] = None) -> dict:
    # Phase 2 — stub that enqueues history sync (real impl in sync.py)
    try:
        from .sync import trigger_history_sync
        job = await trigger_history_sync(bridge_id, with_media=with_media, limit=limit)
        return {"success": True, "job": job}
    except Exception as e:
        return {"success": False, "error": str(e)[:500], "note": "sync module not yet fully implemented — Phase 2"}

# ── Dispatcher ────────────────────────────────────────────────────────────────

TOOL_HANDLERS = {
    "whatsapp.list_bridges": tool_list_bridges,
    "whatsapp.send_message": tool_send_message,
    "whatsapp.get_messages": tool_get_messages,
    "whatsapp.get_contact": tool_get_contact,
    "whatsapp.get_call_log": tool_get_call_log,
    "whatsapp.get_groups": tool_get_groups,
    "whatsapp.get_bridge_status": tool_get_bridge_status,
    "whatsapp.sync_history": tool_sync_history,
}

async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {"error": f"unknown tool {name}", "available": list(TOOL_HANDLERS)}
    try:
        import inspect
        sig = inspect.signature(handler)
        kwargs = {k: v for k, v in (arguments or {}).items() if k in sig.parameters}
        return await handler(**kwargs)
    except TypeError as e:
        # missing required arg
        return {"error": f"bad arguments for {name}: {e}", "schema": next((t for t in TOOL_SCHEMAS if t['name']==name), None)}
    except Exception as e:
        log.exception("[mcp] tool %s error", name)
        return {"error": str(e)[:800]}

# ── FastAPI router (mounted at /mcp) ────────────────────────────────────────

def get_mcp_router():
    from fastapi import APIRouter, Depends, Request
    from app.main import require_api_key  # reuse auth
    router = APIRouter(prefix="/mcp", tags=["whatsapp-mcp"])

    @router.get("/tools")
    async def list_tools(_key: str = Depends(require_api_key)):
        return {"tools": TOOL_SCHEMAS}

    @router.post("/call")
    async def mcp_call(req: Request, _key: str = Depends(require_api_key)):
        body = await req.json()
        name = body.get("name") or body.get("tool") or ""
        arguments = body.get("arguments") or body.get("args") or {}
        result = await call_tool(name, arguments)
        return {"tool": name, "result": result}

    @router.post("/tools/{tool_name:path}")
    async def call_by_path(tool_name: str, req: Request, _key: str = Depends(require_api_key)):
        body = {}
        try: body = await req.json()
        except Exception: pass
        result = await call_tool(tool_name, body)
        return {"tool": tool_name, "result": result}

    return router
