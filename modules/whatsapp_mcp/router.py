"""
whatsapp_mcp.router — FastAPI router for Universal Bridge Registry + MCP

Mount: /api/bridges/*  (CRUD)  +  /mcp/* (MCP tools)
Auth: X-Internal-Key (same as other admin APIs)

This file is additive — no existing routes changed.
"""
from __future__ import annotations

import logging
from typing import Optional, Any

from fastapi import APIRouter, Depends, Request

log = logging.getLogger("fazle.whatsapp_mcp.router")

router = APIRouter(prefix="/api/bridges", tags=["whatsapp-mcp-bridges"])
mcp_router = APIRouter(prefix="/mcp", tags=["whatsapp-mcp"])

# ── Lazy import require_api_key to avoid circular import at module load ──────

def _require_key():
    from app.main import require_api_key  # local import
    return require_api_key

# ── /api/bridges CRUD ───────────────────────────────────────────────────────

@router.get("")
async def list_bridges(include_disabled: bool = False, _key: str = Depends(_require_key())):
    from .registry import get_registry
    reg = await get_registry()
    bridges = await reg.all(include_disabled=include_disabled)
    return {"bridges": [b.to_dict() for b in bridges], "loaded_from": reg.loaded_from, "count": len(bridges)}

@router.get("/{bridge_id}")
async def get_bridge(bridge_id: str, _key: str = Depends(_require_key())):
    from .registry import get_registry
    reg = await get_registry()
    cfg = reg.get(bridge_id)
    if not cfg:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"bridge_id {bridge_id} not found")
    return cfg.to_dict(include_secret=False)

@router.post("")
async def create_bridge(req: Request, _key: str = Depends(_require_key())):
    body = await req.json()
    from .registry import BridgeConfig, get_registry
    cfg = BridgeConfig(
        bridge_id=str(body.get("bridge_id") or body.get("id") or ""),
        label=str(body.get("label") or ""),
        base_url=str(body.get("base_url") or body.get("url") or ""),
        messages_db_path=str(body.get("messages_db_path") or body.get("messages_db") or ""),
        whatsapp_db_path=str(body.get("whatsapp_db_path") or body.get("whatsapp_db") or ""),
        phone_number=str(body.get("phone_number") or body.get("phone") or ""),
        phone_number_jid=str(body.get("phone_number_jid") or ""),
        direction=str(body.get("direction") or "both"),
        enabled=bool(body.get("enabled", True)),
        priority=int(body.get("priority", 100)),
        webhook_secret=str(body.get("webhook_secret") or ""),
        extra_json=dict(body.get("extra_json") or body.get("extra") or {}),
    )
    errs = cfg.validate()
    if errs:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail={"errors": errs})
    reg = await get_registry()
    await reg.upsert(cfg)
    return {"success": True, "bridge": cfg.to_dict()}

@router.patch("/{bridge_id}")
async def update_bridge(bridge_id: str, req: Request, _key: str = Depends(_require_key())):
    from .registry import get_registry
    reg = await get_registry()
    existing = reg.get(bridge_id)
    if not existing:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"bridge_id {bridge_id} not found")
    body = await req.json()
    # patch fields
    for k in ("label","base_url","messages_db_path","whatsapp_db_path","phone_number","phone_number_jid","direction","enabled","priority","webhook_secret","extra_json"):
        if k in body:
            setattr(existing, k, body[k])
    # re-validate
    errs = existing.validate()
    if errs:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail={"errors": errs})
    await reg.upsert(existing)
    return {"success": True, "bridge": existing.to_dict()}

@router.delete("/{bridge_id}")
async def delete_bridge(bridge_id: str, _key: str = Depends(_require_key())):
    from .registry import get_registry
    reg = await get_registry()
    ok = await reg.delete(bridge_id)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"bridge_id {bridge_id} not found")
    return {"success": True, "deleted": bridge_id}

@router.post("/{bridge_id}/test")
async def test_bridge(bridge_id: str, _key: str = Depends(_require_key())):
    from .registry import get_registry
    reg = await get_registry()
    cfg = reg.get(bridge_id)
    if not cfg:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"bridge_id {bridge_id} not found")
    # try HTTP probe
    import httpx
    result: dict[str, Any] = {"bridge_id": bridge_id, "base_url": cfg.base_url}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{cfg.base_url.rstrip('/')}/api/send-status", timeout=5.0)
            result["http_status"] = r.status_code
            try: result["body"] = r.json()
            except Exception: result["body_preview"] = r.text[:300]
            result["success"] = r.status_code == 200
    except Exception as e:
        result["success"] = False
        result["error"] = str(e)[:500]
    # also check DB file existence (if local path)
    import os
    if cfg.messages_db_path:
        result["messages_db_exists"] = os.path.exists(cfg.messages_db_path)
        result["messages_db_path"] = cfg.messages_db_path
    if cfg.whatsapp_db_path:
        result["whatsapp_db_exists"] = os.path.exists(cfg.whatsapp_db_path)
        result["whatsapp_db_path"] = cfg.whatsapp_db_path
    return result

@router.get("/{bridge_id}/sync/status")
async def sync_status(bridge_id: str, _key: str = Depends(_require_key())):
    from .sync import get_sync_status
    return await get_sync_status(bridge_id)

@router.post("/{bridge_id}/sync/history")
async def sync_history(bridge_id: str, req: Request, _key: str = Depends(_require_key())):
    body = {}
    try: body = await req.json()
    except Exception: pass
    from .sync import trigger_history_sync
    with_media = bool(body.get("with_media", False))
    limit = body.get("limit")
    try: limit = int(limit) if limit is not None else None
    except Exception: limit = None
    return await trigger_history_sync(bridge_id, with_media=with_media, limit=limit)

# ── /mcp/* (tool surface) ───────────────────────────────────────────────────

@mcp_router.get("/tools")
async def mcp_list_tools(_key: str = Depends(_require_key())):
    from .mcp_server import TOOL_SCHEMAS
    return {"tools": TOOL_SCHEMAS}

@mcp_router.post("/call")
async def mcp_call(req: Request, _key: str = Depends(_require_key())):
    body = await req.json()
    name = body.get("name") or body.get("tool") or ""
    arguments = body.get("arguments") or body.get("args") or {}
    from .mcp_server import call_tool
    result = await call_tool(name, arguments)
    return {"tool": name, "result": result}

@mcp_router.post("/tools/{tool_name:path}")
async def mcp_call_by_path(tool_name: str, req: Request, _key: str = Depends(_require_key())):
    body = {}
    try: body = await req.json()
    except Exception: pass
    from .mcp_server import call_tool
    result = await call_tool(tool_name, body)
    return {"tool": tool_name, "result": result}
