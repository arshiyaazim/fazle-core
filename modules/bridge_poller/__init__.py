"""
Fazle Core — Bridge SQLite Poller (Phase 3B)

Polls both bridge SQLite message stores every 5 seconds.
Pipeline: inbound SQLite row → LID→phone resolve → dedup check
          → classify intent → Ollama reply → bridge send API → checkpoint

Design choices:
- Read-only SQLite access (uri=?mode=ro) — never writes to bridge DBs
- Timestamp cursor stored in PostgreSQL `bridge_poller_cursor` (persists across restarts)
- Dedup table `processed_bridge_messages` as safety net (handles cursor edge cases)
- On fresh start (no cursor): begins from NOW() — avoids replying to historical messages
- SQLite queries run in thread pool (sync) so asyncio loop is never blocked

Ingest policy (v1.0.2 — locked):
- DMs (@s.whatsapp.net): ALWAYS persisted to wbom_whatsapp_messages before
  any router/draft logic. No early return drops a real DM silently.
- Groups (@g.us), newsletters (@newsletter), status@broadcast: SKIPPED ENTIRELY
  at SQL level — not persisted, no draft, no reply. Group chats are out of
  scope for this engine by owner directive (2026-04-27).
- LID-unresolved DMs are persisted with phone='unresolved:<lid>' so no real
  inbound is lost; counted via observability for alerting.
- Auto-reply remains gated by AUTO_REPLY_ENABLED + DRAFT_QUALITY_GATE.
"""

import asyncio
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.config import get_settings
from app.database import execute, fetch_one, fetch_all, fetch_val
from app.bridge import get_bridge1, get_bridge2
from modules.message_router import process_message, get_primary_admin
from modules.intent import classify as classify_intent

_settings = get_settings()

log = logging.getLogger("fazle.bridge_poller")

POLL_INTERVAL = 5  # seconds
REPLY_COOLDOWN = 60  # minimum seconds between replies to same number

# Per-bridge SQLite paths — loaded from settings at startup
BRIDGE_CONFIGS = [
    {
        "name": "bridge1",
        "messages_db": "/home/azim/whatsapp-mcp/whatsapp-bridge/store/messages.db",
        "whatsapp_db": "/home/azim/whatsapp-mcp/whatsapp-bridge/store/whatsapp.db",
        "get_bridge": get_bridge1,
    },
    {
        "name": "bridge2",
        "messages_db": "/home/azim/whatsapp2/store/messages.db",
        "whatsapp_db": "/home/azim/whatsapp2/store/whatsapp.db",
        "get_bridge": get_bridge2,
    },
]

# ── Schema ─────────────────────────────────────────────────────────────────────

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS bridge_poller_cursor (
    bridge      TEXT PRIMARY KEY,
    last_ts     TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS processed_bridge_messages (
    message_id  TEXT    NOT NULL,
    bridge      TEXT    NOT NULL,
    phone       TEXT,
    processed_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (message_id, bridge)
);

CREATE INDEX IF NOT EXISTS idx_pbm_bridge_ts
    ON processed_bridge_messages (bridge, processed_at DESC);
"""


async def init_tables():
    for stmt in _INIT_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            await execute(stmt)
    log.info("Bridge poller tables ready")


# ── Cursor helpers ─────────────────────────────────────────────────────────────

async def _get_cursor(bridge: str) -> datetime:
    """Return the last processed timestamp for this bridge.
    Defaults to NOW() on first run — avoids blasting old messages."""
    row = await fetch_one(
        "SELECT last_ts FROM bridge_poller_cursor WHERE bridge = $1", bridge
    )
    if row and row["last_ts"]:
        ts = row["last_ts"]
        # asyncpg returns timezone-aware datetime already
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    # First run — start from 5 minutes ago to catch very recent messages
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    await _set_cursor(bridge, now)
    return now


async def _set_cursor(bridge: str, ts: datetime):
    await execute(
        """
        INSERT INTO bridge_poller_cursor (bridge, last_ts) VALUES ($1, $2)
        ON CONFLICT (bridge) DO UPDATE SET last_ts = EXCLUDED.last_ts
        """,
        bridge, ts,
    )


# ── Dedup helpers ──────────────────────────────────────────────────────────────

async def _is_processed(msg_id: str, bridge: str) -> bool:
    val = await fetch_val(
        "SELECT 1 FROM processed_bridge_messages WHERE message_id=$1 AND bridge=$2",
        msg_id, bridge,
    )
    return val is not None


async def _mark_processed(msg_id: str, bridge: str, phone: str):
    await execute(
        """
        INSERT INTO processed_bridge_messages (message_id, bridge, phone)
        VALUES ($1, $2, $3)
        ON CONFLICT DO NOTHING
        """,
        msg_id, bridge, phone,
    )


# ── SQLite fetch (sync — runs in thread pool) ─────────────────────────────────

def _load_lid_map(whatsapp_db: str) -> dict[str, str]:
    """Load lid→phone mapping from whatsapp.db."""
    lid_map: dict[str, str] = {}
    try:
        con = sqlite3.connect(f"file:{whatsapp_db}?mode=ro", uri=True, check_same_thread=False)
        rows = con.execute("SELECT lid, pn FROM whatsmeow_lid_map").fetchall()
        con.close()
        for lid, pn in rows:
            lid_map[str(lid)] = str(pn)
    except Exception as e:
        log.warning(f"LID map load error ({whatsapp_db}): {e}")
    return lid_map


def _fetch_new_messages(
    messages_db: str,
    whatsapp_db: str,
    since_ts: datetime,
) -> tuple[list[dict], datetime]:
    """
    Fetch inbound personal messages newer than since_ts from SQLite.
    Returns (messages, max_ts_seen).
    Runs synchronously — call via run_in_executor.
    """
    messages: list[dict] = []
    max_ts = since_ts

    try:
        # Use read-only URI mode — never modify bridge DBs
        con = sqlite3.connect(f"file:{messages_db}?mode=ro", uri=True, check_same_thread=False)
        con.row_factory = sqlite3.Row

        # Convert aware datetime to naive UTC string for SQLite comparison
        # SQLite timestamps stored as '2026-04-23 06:44:29+02:00' (ISO with tz)
        # Use datetime cast in SQLite to handle timezone-aware comparison
        ts_iso = since_ts.isoformat()

        rows = con.execute(
            """
            SELECT id, chat_jid, sender, content, timestamp, media_type, processed_text
            FROM messages
            WHERE is_from_me = 0
              AND datetime(timestamp) > datetime(:since)
              AND chat_jid NOT LIKE '%@newsletter'
              AND chat_jid != 'status@broadcast'
              AND chat_jid NOT LIKE '%@g.us'
              AND (content IS NOT NULL OR processed_text IS NOT NULL)
            ORDER BY datetime(timestamp) ASC
            LIMIT 50
            """,
            {"since": ts_iso},
        ).fetchall()

        # v1.0.2: visibility on what we filter out (groups/newsletters/status)
        try:
            skipped_row = con.execute(
                """
                SELECT
                  SUM(CASE WHEN chat_jid LIKE '%@g.us' THEN 1 ELSE 0 END) AS groups,
                  SUM(CASE WHEN chat_jid LIKE '%@newsletter' THEN 1 ELSE 0 END) AS newsletters,
                  SUM(CASE WHEN chat_jid = 'status@broadcast' THEN 1 ELSE 0 END) AS status
                FROM messages
                WHERE is_from_me = 0
                  AND datetime(timestamp) > datetime(:since)
                """,
                {"since": ts_iso},
            ).fetchone()
            if skipped_row:
                from modules import observability as _obs
                bn = messages_db  # bridge identifier (full path is unique)
                if skipped_row["groups"]:
                    _obs.inc("messages_skipped_total", value=float(skipped_row["groups"]),
                             labels={"reason": "group", "db": bn})
                if skipped_row["newsletters"]:
                    _obs.inc("messages_skipped_total", value=float(skipped_row["newsletters"]),
                             labels={"reason": "newsletter", "db": bn})
                if skipped_row["status"]:
                    _obs.inc("messages_skipped_total", value=float(skipped_row["status"]),
                             labels={"reason": "status", "db": bn})
        except Exception as _sk_err:
            log.debug(f"skipped-count query failed: {_sk_err}")
        con.close()

        lid_map = _load_lid_map(whatsapp_db)

        for row in rows:
            msg = dict(row)

            # Resolve sender LID → phone
            sender_lid = str(msg.get("sender", "")).split(":")[0].split("@")[0]
            phone = lid_map.get(sender_lid, "")

            if not phone:
                # Fallback: try chat_jid if it's a s.whatsapp.net JID
                chat_jid = msg.get("chat_jid", "")
                if chat_jid.endswith("@s.whatsapp.net"):
                    phone = chat_jid.replace("@s.whatsapp.net", "")
                else:
                    # v1.0.2: do NOT silently drop. Tag and let downstream persist.
                    phone = f"unresolved:{sender_lid}" if sender_lid else "unresolved:unknown"
                    try:
                        from modules import observability as _obs
                        _obs.inc("messages_lid_unresolved_total",
                                 labels={"db": messages_db})
                    except Exception:
                        pass
                    log.warning(f"LID unresolved → tagging phone={phone} jid={chat_jid}")

            # Text: prefer content, fallback to processed_text (STT/OCR)
            text = (msg.get("content") or msg.get("processed_text") or "").strip()
            if not text:
                continue

            # Parse timestamp for cursor update
            try:
                ts_str = msg["timestamp"]
                # Python 3.7+ fromisoformat handles +HH:MM offsets
                ts_dt = datetime.fromisoformat(ts_str)
                if ts_dt.tzinfo is None:
                    ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                if ts_dt > max_ts:
                    max_ts = ts_dt
            except Exception as _ts_err:
                log.debug(f"ts parse error for msg {msg.get('id')}: {_ts_err}")

            msg["phone"] = phone
            msg["text"] = text
            messages.append(msg)

    except Exception as e:
        log.error(f"SQLite fetch error ({messages_db}): {e}")

    return messages, max_ts


# ── Reply cooldown (in-memory per process) ────────────────────────────────────
_last_reply: dict[str, float] = {}  # phone → unix timestamp of last reply


def _can_reply(phone: str) -> bool:
    import time
    last = _last_reply.get(phone, 0)
    return (time.time() - last) >= REPLY_COOLDOWN


def _record_reply(phone: str):
    import time
    _last_reply[phone] = time.time()


# ── Main poll loop ─────────────────────────────────────────────────────────────

async def _poll_bridge(config: dict):
    bridge_name: str = config["name"]
    messages_db: str = config["messages_db"]
    whatsapp_db: str = config["whatsapp_db"]
    get_bridge = config["get_bridge"]

    log.info(f"[{bridge_name}] Poller started")

    # Load cursor from DB
    cursor = await _get_cursor(bridge_name)
    log.info(f"[{bridge_name}] Starting from cursor: {cursor.isoformat()}")

    while True:
        try:
            loop = asyncio.get_event_loop()
            messages, new_cursor = await loop.run_in_executor(
                None, _fetch_new_messages, messages_db, whatsapp_db, cursor
            )

            if messages:
                log.info(f"[{bridge_name}] {len(messages)} new message(s) to process")

            for msg in messages:
                msg_id: str = msg["id"]
                phone: str = msg["phone"]
                text: str = msg["text"]

                # Dedup check
                if await _is_processed(msg_id, bridge_name):
                    continue

                # Mark processed immediately (prevents duplicate reply on crash-restart)
                await _mark_processed(msg_id, bridge_name, phone)

                log.info(f"[{bridge_name}] from={phone} text={text[:80]!r}")

                # Detect identity before routing (for logging)
                from modules.identity_brain import detect_identity
                identity = await detect_identity(phone, text)
                id_role = identity["identity_role"]
                id_conf = identity["identity_confidence"]

                # Save inbound with identity metadata
                await _save_message(bridge_name, phone, text, "inbound",
                                    identity_role=id_role, identity_confidence=id_conf)
                try:
                    from modules import observability as _obs
                    _obs.inc("dm_messages_ingested_total",
                             labels={"bridge": bridge_name})
                except Exception:
                    pass

                # v1.0.2: never run router/draft/reply on unresolved-LID messages
                # (we still kept them in DB above for audit).
                if phone.startswith("unresolved:"):
                    continue

                # Cooldown check — don't spam the same person
                if not _can_reply(phone):
                    log.info(f"[{bridge_name}] Cooldown active for {phone}, skipping reply")
                    continue

                # Classify intent for draft storage (process_message re-classifies internally)
                msg_intent = classify_intent(text)

                # Full routing — admin commands, recruitment, escort, payment, KB, AI
                reply, admin_note = await process_message(phone, text, bridge_name)

                if reply:
                    if _settings.auto_reply_enabled:
                        bridge = get_bridge()
                        sent = await bridge.send(phone, reply)
                        if sent:
                            _record_reply(phone)
                            await _save_message(bridge_name, phone, reply, "outbound",
                                                identity_role=id_role, identity_confidence=id_conf,
                                                workflow=msg_intent)
                            log.info(f"[{bridge_name}] Replied to {phone}")
                        else:
                            log.warning(f"[{bridge_name}] Send failed to {phone}")
                    else:
                        log.warning(
                            f"SAFE MODE: reply suppressed for {phone} ({bridge_name}). Saving draft."
                        )
                        await _save_draft(bridge_name, phone, reply, msg_intent)

                if admin_note and _settings.auto_reply_enabled:
                    await _notify_admin_bridge(admin_note)

            # Advance cursor even if no messages (uses max_ts from fetch)
            if new_cursor > cursor:
                cursor = new_cursor
                await _set_cursor(bridge_name, cursor)

            # Heartbeat (B15.3)
            try:
                from app.database import execute as _exec
                await _exec(
                    """INSERT INTO fazle_service_heartbeats (service, last_seen, last_message_id, queue_depth)
                       VALUES ($1, NOW(), $2, $3)
                       ON CONFLICT (service)
                       DO UPDATE SET last_seen = NOW(),
                                     last_message_id = EXCLUDED.last_message_id,
                                     queue_depth = EXCLUDED.queue_depth""",
                    f"bridge_poller:{bridge_name}",
                    (messages[-1]["id"] if messages else None),
                    len(messages),
                )
            except Exception as _hb_err:
                log.warning(f"[{bridge_name}] heartbeat write failed: {_hb_err}")

        except asyncio.CancelledError:
            log.info(f"[{bridge_name}] Poller stopped")
            break
        except Exception as e:
            log.exception(f"[{bridge_name}] Poll loop error: {e}")

        await asyncio.sleep(POLL_INTERVAL)


# ── Public API ─────────────────────────────────────────────────────────────────

async def start_pollers():
    """Initialize DB tables and launch background poll tasks for both bridges."""
    await init_tables()
    for config in BRIDGE_CONFIGS:
        asyncio.create_task(_poll_bridge(config))
    log.info("Bridge pollers running for bridge1 + bridge2")


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _save_draft(source: str, recipient: str, reply_text: str, intent: str):
    """Store a suppressed reply as a draft (safe mode).

    B25 hotfix: passes through draft_quality gate first. Bad drafts are still
    persisted (for audit) but with status='rejected_quality'/'rejected_fallback'
    and meta.quality_reason — they never appear in the admin pending list.
    """
    from modules.draft_quality import check_draft_quality
    from modules import observability as _obs
    ok, reason = check_draft_quality(reply_text)
    if not ok:
        _obs.inc("drafts_rejected_total", labels={"reason": reason or "unknown", "source": source})
        log.warning(f"[draft_quality] rejected source={source} recipient={recipient} reason={reason}")
        try:
            await execute(
                """
                INSERT INTO fazle_draft_replies
                    (source, recipient, reply_text, intent, draft_only, status, created_at, meta)
                VALUES ($1, $2, $3, $4, true, $5, NOW(),
                        jsonb_build_object('quality_reason', $6, 'gate', 'b25'))
                """,
                source, recipient, reply_text or "", intent,
                "rejected_fallback" if reason == "llm_fallback" else "rejected_quality",
                reason or "unknown",
            )
        except Exception as e:
            log.warning(f"Draft save (rejected) error: {e}")
        return
    try:
        await execute(
            """
            INSERT INTO fazle_draft_replies
                (source, recipient, reply_text, intent, draft_only, status, created_at)
            VALUES ($1, $2, $3, $4, true, 'pending', NOW())
            """,
            source, recipient, reply_text, intent,
        )
    except Exception as e:
        log.warning(f"Draft save error: {e}")


async def _save_message(
    source: str,
    sender: str,
    text: str,
    direction: str,
    identity_role: str = "",
    identity_confidence: int = 0,
    workflow: str = "",
):
    try:
        await execute(
            """
            INSERT INTO wbom_whatsapp_messages
                (sender_number, message_body, message_type, direction,
                 platform, is_processed, contact_identifier,
                 identity_role, identity_confidence, workflow_triggered)
            VALUES ($1, $2, 'text', $3, $4, true, $1, $5, $6, $7)
            """,
            sender, text, direction, source,
            identity_role or None, identity_confidence or None, workflow or None,
        )
    except Exception as e:
        log.warning(f"Message save error: {e}")


async def _notify_admin_bridge(notification: dict):
    """Send admin notification via the appropriate bridge."""
    admin_phone = notification.get("admin_phone", "")
    text = notification.get("text", "")
    bridge_src = notification.get("bridge", "bridge2")
    if not admin_phone or not text:
        return
    try:
        bridge = get_bridge1() if bridge_src == "bridge1" else get_bridge2()
        await bridge.send(f"{admin_phone}@s.whatsapp.net", text)
        log.info(f"[bridge_poller] admin notified: {admin_phone}")
    except Exception as e:
        log.error(f"[bridge_poller] admin notify error: {e}")
