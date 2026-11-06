"""
whatsapp_mcp.sync — History Sync (Full Bulk Copy)

Copies bridge SQLite `messages` → `fazle_whatsapp_messages` + `bridge_sync_state`.

Features:
  - Chunked (default 500 rows), background asyncio task, progress in DB
  - Handles inbound + outbound (direction inferred from is_from_me)
  - Dedup via message_hash (ON CONFLICT DO NOTHING) + processed_bridge_messages
  - Identifier enrichment: JID/LID/PN/phone/group/media/call all via identifier.py
  - Call trace, group chat, media type preserved
  - Graceful on missing DB file / missing table
  - Webhook-only bridges (no messages_db_path) → immediate success with 0 rows

Usage:
  POST /api/bridges/{bridge_id}/sync/history  {"with_media": false, "limit": 1000}
  GET  /api/bridges/{bridge_id}/sync/status
  MCP: whatsapp.sync_history {bridge_id, with_media, limit}
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("fazle.whatsapp_mcp.sync")

# ── In-memory job registry (lightweight, survives process restart via DB) ─────
_jobs: dict[str, dict] = {}  # job_id → {bridge_id, status, started_at, progress}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _core_message_hash(source: str, source_message_ref: str) -> str:
    return hashlib.sha256(f"{source}|{source_message_ref}".encode("utf-8")).hexdigest()

def _parse_ts(val) -> Optional[datetime]:
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if not val:
        return None
    try:
        ts = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def _storage_canonical_phone(phone: Optional[str]) -> Optional[str]:
    try:
        from modules.phone_normalizer import storage_canonical_phone
        return storage_canonical_phone(phone)
    except Exception:
        return phone if phone and not str(phone).startswith(("unresolved:", "lid:")) else None

def _storage_phone_last10(phone: Optional[str]) -> Optional[str]:
    try:
        from modules.phone_normalizer import storage_phone_last10
        return storage_phone_last10(phone)
    except Exception:
        return None

def _load_lid_map_sync(whatsapp_db: str) -> dict[str, str]:
    lid_map: dict[str, str] = {}
    if not whatsapp_db or not os.path.exists(whatsapp_db):
        return lid_map
    try:
        con = sqlite3.connect(f"file:{whatsapp_db}?mode=ro", uri=True, check_same_thread=False, timeout=5.0)
        rows = con.execute("SELECT lid, pn FROM whatsmeow_lid_map").fetchall()
        con.close()
        for lid, pn in rows:
            lid_map[str(lid)] = str(pn)
    except Exception as e:
        log.debug("[sync] lid_map load skip %s: %s", whatsapp_db, e)
    return lid_map

def _fetch_history_chunk_sync(
    messages_db: str,
    whatsapp_db: str,
    offset: int,
    chunk_size: int = 500,
) -> tuple[list[dict], bool]:
    """Fetch one chunk of history from bridge SQLite (inbound+outbound, all types).

    Returns ([rows], has_more). Each row has: id, chat_jid, sender, content,
    timestamp, media_type, filename, url, is_from_me, chat_jid etc.
    """
    if not messages_db or not os.path.exists(messages_db):
        return [], False
    try:
        con = sqlite3.connect(f"file:{messages_db}?mode=ro", uri=True, check_same_thread=False, timeout=5.0)
        con.row_factory = sqlite3.Row
        # Check has_column for from_history_sync to avoid spam on old DBs
        try:
            from shared.sqlite_compat import has_column
            _has_hist = has_column(con, "messages", "from_history_sync")
        except Exception:
            _has_hist = False

        # Fetch chunk ordered by timestamp ASC (oldest first for stable history)
        # Include all messages (is_from_me 0+1) except pure system noise
        # We keep groups/newsletters/status — history sync is archival, not routing filter
        rows = con.execute(
            """
            SELECT id, chat_jid, sender, content, timestamp, media_type,
                   filename, url, is_from_me
            FROM messages
            ORDER BY datetime(timestamp) ASC
            LIMIT ? OFFSET ?
            """,
            (chunk_size, offset),
        ).fetchall()
        con.close()

        out = []
        lid_map = _load_lid_map_sync(whatsapp_db)
        for r in rows:
            msg = dict(r)
            # Resolve phone
            sender_lid = str(msg.get("sender") or "").split(":")[0].split("@")[0]
            phone = lid_map.get(sender_lid, "")
            if not phone:
                chat_jid = msg.get("chat_jid") or ""
                if chat_jid.endswith("@s.whatsapp.net"):
                    phone = chat_jid.replace("@s.whatsapp.net", "")
                elif sender_lid:
                    # outbound: sender is our own number, chat_jid is recipient
                    if chat_jid and "@s.whatsapp.net" in chat_jid:
                        phone = chat_jid.split("@")[0]
                    else:
                        phone = f"unresolved:{sender_lid}" if sender_lid else "unresolved:unknown"
                else:
                    phone = "unresolved:unknown"
            # direction
            is_from_me = msg.get("is_from_me")
            direction = "outbound" if is_from_me in (1, True, "1", "true") else "inbound"
            # For outbound, phone is recipient; for inbound, sender
            # But for storage, sender_number is always the counterparty for inbound,
            # and our own number for outbound? We keep phone as counterparty both ways
            # and use direction to distinguish (mirrors _save_raw_core_copy convention)
            # For outbound, the "sender_number" in fazle_whatsapp_messages is the recipient
            # (we sent to them) — consistent with existing _save_message for outbound.

            # Text fallback
            text = (msg.get("content") or "").strip()
            mt = str(msg.get("media_type") or "").strip().lower()
            if not text:
                if mt and (msg.get("filename") or msg.get("url")):
                    text = f"[media:{mt}]"
                elif mt in ("call", "missed_call"):
                    text = f"[call:{mt}]"
                else:
                    # empty unknown — keep as empty, will be skipped downstream
                    text = ""

            msg["phone"] = phone
            msg["text"] = text
            msg["direction"] = direction
            msg["lid_map_key"] = sender_lid
            out.append(msg)

        has_more = len(rows) == chunk_size
        return out, has_more
    except Exception as e:
        log.warning("[sync] fetch chunk offset=%s failed: %s", offset, e)
        return [], False

async def _insert_history_rows(bridge_id: str, rows: list[dict]) -> int:
    """Insert chunk rows into fazle_whatsapp_messages + enqueue. Returns inserted count."""
    inserted = 0
    for msg in rows:
        msg_id = str(msg.get("id") or "")
        if not msg_id:
            continue
        phone = msg.get("phone") or ""
        text = msg.get("text") or ""
        direction = msg.get("direction") or "inbound"
        chat_jid = str(msg.get("chat_jid") or "")
        media_type = str(msg.get("media_type") or "text").strip() or "text"
        source_ts = _parse_ts(msg.get("timestamp"))
        conv_key = f"{chat_jid if chat_jid.endswith('@g.us') else phone}:{bridge_id}" if (phone or chat_jid) else None
        receiver = None
        try:
            from app.config import get_settings as _gs
            s = _gs()
            receiver = {"bridge1": s.bridge1_number, "bridge2": s.bridge2_number, "bridge3": s.bridge3_number}.get(bridge_id)
        except Exception:
            receiver = None

        # Build hash for dedup (same as poller)
        msg_hash = _core_message_hash(bridge_id, msg_id)
        context = {
            "stage": "history_sync",
            "source_message_ref": msg_id,
            "chat_jid": chat_jid,
            "filename": msg.get("filename"),
            "media_type": msg.get("media_type"),
            "is_from_me": msg.get("is_from_me"),
            "bridge_store_preserved": True,
            "history_sync": True,
        }
        _actor_type = "external_user" if direction == "inbound" else "self_sent"
        # Determine group vs DM for enrichment
        is_group_msg = chat_jid.endswith("@g.us")

        try:
            from app.database import fetch_one, execute
            # Skip if hash exists
            existing = await fetch_one("SELECT message_id FROM fazle_whatsapp_messages WHERE message_hash=$1 LIMIT 1", msg_hash)
            if existing:
                continue
            row = await fetch_one(
                """
                INSERT INTO fazle_whatsapp_messages
                    (sender_number, original_sender_number, message_body, message_type,
                     direction, platform, is_processed, contact_identifier,
                     receiver_number, conversation_key, source_message_ref,
                     source_timestamp, source_context, message_hash,
                     canonical_phone, phone_last10, metadata_json, actor_type, actor_id)
                VALUES ($1, $2, $3, $4, $5, $6, false, $1,
                        $7, $8, $9, $10::timestamptz, $11, $12, $13, $14, $15::jsonb, $16, $17)
                ON CONFLICT (message_hash) DO NOTHING
                RETURNING message_id
                """,
                phone, phone, text or f"[media:{media_type}]", media_type, direction, bridge_id,
                receiver, conv_key, msg_id, source_ts,
                json.dumps(context, ensure_ascii=False), msg_hash,
                _storage_canonical_phone(phone),
                _storage_phone_last10(phone),
                json.dumps(context, ensure_ascii=False),
                _actor_type, None,
            )
            core_id = int(row["message_id"]) if row and row.get("message_id") is not None else None
            # Enrich identifier columns if migration applied
            try:
                from modules.fazle_bridge_poller import _enrich_core_with_identifiers
                await _enrich_core_with_identifiers(core_id, bridge_id, msg, phone)
            except Exception:
                pass
            # Also mark processed_bridge_messages so poller won't re-process same id via cursor edge
            try:
                await execute(
                    "INSERT INTO processed_bridge_messages (message_id, bridge, phone) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
                    msg_id, bridge_id, phone,
                )
            except Exception:
                pass
            inserted += 1
        except Exception as e:
            # Table not ready (pre-migration) → skip gracefully
            if "does not exist" in str(e).lower() or "no such table" in str(e).lower():
                log.warning("[sync] insert skipped (table missing): %s", e)
                break
            log.debug("[sync] insert row msg_id=%s failed: %s", msg_id, e)
            continue
    return inserted

# ── Public API ────────────────────────────────────────────────────────────────

async def trigger_history_sync(bridge_id: str, with_media: bool = False, limit: Optional[int] = None) -> dict:
    job_id = f"sync-{bridge_id}-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    from .registry import get_registry
    reg = await get_registry()
    cfg = reg.get(bridge_id)
    if not cfg:
        raise ValueError(f"bridge_id {bridge_id} not found. Available: {[b.bridge_id for b in await reg.all(include_disabled=True)]}")

    messages_db = cfg.messages_db_path
    whatsapp_db = cfg.whatsapp_db_path

    # Webhook-only bridge: no local DB to copy
    if not messages_db or not os.path.exists(messages_db):
        log.info("[sync] bridge=%s has no local messages.db (webhook-only or path missing: %s) — zero-row sync", bridge_id, messages_db)
        try:
            from app.database import execute
            await execute(
                """
                INSERT INTO bridge_sync_state (bridge_id, history_synced, history_total, history_copied, last_history_sync_at)
                VALUES ($1, true, 0, 0, NOW())
                ON CONFLICT (bridge_id) DO UPDATE SET history_synced=true, history_total=0, history_copied=0, last_history_sync_at=NOW()
                """,
                bridge_id,
            )
        except Exception as e:
            log.debug("[sync] bridge_sync_state upsert skip: %s", e)
        return {
            "job_id": job_id,
            "bridge_id": bridge_id,
            "with_media": with_media,
            "limit": limit,
            "status": "done",
            "copied": 0,
            "total": 0,
            "note": "webhook-only bridge: no local messages.db to copy — 0 rows (expected).",
        }

    # Count total if possible
    total = None
    try:
        con = sqlite3.connect(f"file:{messages_db}?mode=ro", uri=True, check_same_thread=False, timeout=5.0)
        total = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        con.close()
    except Exception:
        total = None

    # Init DB progress row
    try:
        from app.database import execute
        await execute(
            """
            INSERT INTO bridge_sync_state (bridge_id, history_synced, history_total, history_copied, last_history_sync_at)
            VALUES ($1, false, $2, 0, NOW())
            ON CONFLICT (bridge_id) DO UPDATE SET history_total=$2, history_copied=0, history_synced=false, last_history_sync_at=NOW()
            """,
            bridge_id, total or 0,
        )
    except Exception as e:
        log.debug("[sync] progress init skip (pre-migration): %s", e)

    _jobs[job_id] = {"bridge_id": bridge_id, "status": "running", "started_at": time.time(), "copied": 0, "total": total}

    # Launch background task
    asyncio.create_task(_run_history_sync(job_id, bridge_id, messages_db, whatsapp_db, with_media, limit, total))

    log.info("[sync] history sync queued bridge=%s job=%s total≈%s limit=%s", bridge_id, job_id, total, limit)
    return {
        "job_id": job_id,
        "bridge_id": bridge_id,
        "with_media": with_media,
        "limit": limit,
        "status": "running",
        "total": total,
        "copied": 0,
        "note": "Background sync started. Poll GET /api/bridges/{bridge_id}/sync/status for progress.",
    }

async def _run_history_sync(job_id: str, bridge_id: str, messages_db: str, whatsapp_db: str, with_media: bool, limit: Optional[int], total: Optional[int]):
    copied = 0
    offset = 0
    chunk_size = 500
    max_rows = limit if limit is not None else 10_000_000  # cap for safety (no infinite on huge DB)
    error = None
    try:
        while copied < max_rows:
            rows, has_more = await asyncio.to_thread(_fetch_history_chunk_sync, messages_db, whatsapp_db, offset, chunk_size)
            if not rows:
                break
            # respect limit
            if limit is not None and copied + len(rows) > limit:
                rows = rows[: limit - copied]
                has_more = False
            n = await _insert_history_rows(bridge_id, rows)
            copied += n
            offset += chunk_size
            _jobs[job_id]["copied"] = copied
            # Update DB progress
            try:
                from app.database import execute
                await execute("UPDATE bridge_sync_state SET history_copied=$2, history_total=$3, last_history_sync_at=NOW() WHERE bridge_id=$1", bridge_id, copied, total or offset)
            except Exception:
                pass
            log.info("[sync] bridge=%s job=%s progress %s/%s (offset %s)", bridge_id, job_id, copied, total or "?", offset)
            if not has_more:
                break
            # Small yield to avoid blocking event loop on big DB
            await asyncio.sleep(0.05)
            # Optional media download (deferred — not fetched during history, just URLs preserved)
            # with_media=true would trigger per-row bridge download via /api/download — kept for Phase 3 improvement

        # Mark done
        try:
            from app.database import execute
            await execute("UPDATE bridge_sync_state SET history_synced=true, history_copied=$2, last_history_sync_at=NOW() WHERE bridge_id=$1", bridge_id, copied)
        except Exception:
            pass
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["copied"] = copied
        log.info("[sync] bridge=%s job=%s DONE copied=%s", bridge_id, job_id, copied)

    except Exception as e:
        error = str(e)[:800]
        log.exception("[sync] bridge=%s job=%s FAILED: %s", bridge_id, job_id, e)
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = error
        try:
            from app.database import execute
            await execute("UPDATE bridge_sync_state SET history_synced=false WHERE bridge_id=$1", bridge_id)
        except Exception:
            pass

async def get_sync_status(bridge_id: str) -> dict:
    # Prefer in-memory job for latest, fallback to DB
    # Find latest job for this bridge
    latest_job = None
    for jid, j in _jobs.items():
        if j.get("bridge_id") == bridge_id:
            if not latest_job or j.get("started_at", 0) > latest_job.get("started_at", 0):
                latest_job = {"job_id": jid, **j}
    try:
        from app.database import fetch_one
        row = await fetch_one("SELECT * FROM bridge_sync_state WHERE bridge_id=$1", bridge_id)
        db_state = dict(row) if row else None
    except Exception as e:
        db_state = {"error": str(e)[:300]}
    out = {"bridge_id": bridge_id, "db_state": db_state}
    if latest_job:
        out["latest_job"] = latest_job
        out["status"] = latest_job.get("status")
        out["copied"] = latest_job.get("copied")
        out["total"] = latest_job.get("total")
    elif db_state:
        out["status"] = "done" if db_state.get("history_synced") else "running" if db_state.get("history_total", 0) > 0 else "not_started"
        out["copied"] = db_state.get("history_copied")
        out["total"] = db_state.get("history_total")
    else:
        out["status"] = "not_started"
    return out

async def list_sync_jobs() -> list[dict]:
    return [{"job_id": jid, **j} for jid, j in _jobs.items()]
