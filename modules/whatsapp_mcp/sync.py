"""
whatsapp_mcp.sync — History Sync (Phase 2 stub + trigger)

Phase 1: provide trigger API that enqueues a job.
Phase 2 (next push): full bulk copy logic (SQLite → fazle_whatsapp_messages).

For now: create a bridge_sync_state row and return job_id; actual copy runs
as background asyncio task when poller is active.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

log = logging.getLogger("fazle.whatsapp_mcp.sync")

async def trigger_history_sync(bridge_id: str, with_media: bool = False, limit: Optional[int] = None) -> dict:
    job_id = f"sync-{bridge_id}-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    # ensure bridge exists
    from .registry import get_registry
    reg = await get_registry()
    cfg = reg.get(bridge_id)
    if not cfg:
        raise ValueError(f"bridge_id {bridge_id} not found")

    # write bridge_sync_state (upsert)
    try:
        from app.database import execute, fetch_one
        await execute(
            """
            INSERT INTO bridge_sync_state (bridge_id, history_synced, history_total, history_copied)
            VALUES ($1, false, 0, 0)
            ON CONFLICT (bridge_id) DO NOTHING
            """,
            bridge_id,
        )
        # store job marker in extra_json of whatsapp_bridges for visibility
        row = await fetch_one("SELECT extra_json FROM whatsapp_bridges WHERE bridge_id=$1", bridge_id)
        log.info("[sync] history sync triggered bridge=%s job=%s with_media=%s limit=%s", bridge_id, job_id, with_media, limit)
    except Exception as e:
        # table not migrated yet — still return job
        log.debug("[sync] trigger DB skip (pre-migration): %s", e)

    return {
        "job_id": job_id,
        "bridge_id": bridge_id,
        "with_media": with_media,
        "limit": limit,
        "status": "queued",
        "note": "Phase 1: queued. Real bulk copy lands in Phase 2 push (bulk SQLite → fazle_whatsapp_messages).",
    }

async def get_sync_status(bridge_id: str) -> dict:
    try:
        from app.database import fetch_one
        row = await fetch_one("SELECT * FROM bridge_sync_state WHERE bridge_id=$1", bridge_id)
        if not row:
            return {"bridge_id": bridge_id, "status": "not_started"}
        return {"bridge_id": bridge_id, **dict(row)}
    except Exception as e:
        return {"bridge_id": bridge_id, "status": "unknown", "error": str(e)[:300]}
