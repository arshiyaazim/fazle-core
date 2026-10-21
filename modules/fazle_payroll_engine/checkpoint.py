
"""
Fazle Payroll Engine — Sync checkpoint management.

Checkpoints record the last processed message per (source, source_number, chat_jid).
They persist across restarts so historical sync resumes from where it left off.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.database import execute, fetch_one

log = logging.getLogger("fazle.fpe.checkpoint")


async def get_checkpoint(source: str, source_number: str, chat_jid: str) -> Optional[dict]:
    """Return checkpoint row or None if this source has never been synced."""
    return await fetch_one(
        """
        SELECT last_message_id, last_timestamp, total_ingested, last_sync_at, last_checked_at
        FROM fpe_sync_checkpoints
        WHERE source = $1 AND source_number = $2 AND chat_jid = $3
        """,
        source, source_number, chat_jid,
    )


async def touch_checkpoint(source: str, source_number: str, chat_jid: str) -> None:
    """Update last_checked_at to NOW() — called every sync pass even with 0 new messages."""
    await execute(
        """
        UPDATE fpe_sync_checkpoints
        SET last_checked_at = NOW()
        WHERE source = $1 AND source_number = $2 AND chat_jid = $3
        """,
        source, source_number, chat_jid,
    )
    log.debug(
        "[fpe.checkpoint] touched source=%s num=%s jid=%s",
        source, source_number, chat_jid,
    )


async def update_checkpoint(
    source: str,
    source_number: str,
    chat_jid: str,
    last_message_id: Optional[str],
    last_timestamp: Optional[datetime],
    ingested_count: int = 0,
) -> None:
    """Upsert checkpoint — safe to call on every batch."""
    await execute(
        """
        INSERT INTO fpe_sync_checkpoints
            (source, source_number, chat_jid, last_message_id, last_timestamp,
             total_ingested, last_sync_at)
        VALUES ($1, $2, $3, $4, $5, $6, NOW())
        ON CONFLICT (source, source_number, chat_jid) DO UPDATE
        SET last_message_id = EXCLUDED.last_message_id,
            last_timestamp  = EXCLUDED.last_timestamp,
            total_ingested  = fpe_sync_checkpoints.total_ingested + $6,
            last_sync_at    = NOW()
        """,
        source, source_number, chat_jid,
        last_message_id, last_timestamp, ingested_count,
    )
    log.debug(
        "[fpe.checkpoint] updated source=%s num=%s jid=%s last_id=%s +%d",
        source, source_number, chat_jid, last_message_id, ingested_count,
    )
