import json
import logging
from datetime import datetime
from typing import Any

import asyncpg

from app.database import execute, fetch_val
from modules.number_identity import (
    append_critical_log,
    build_message_hash,
    canonical_phone,
    is_critical_phone,
    phone_last10,
)

log = logging.getLogger("fazle.message_archive")


_SCHEMA_SQL = """
ALTER TABLE fazle_whatsapp_messages
    ADD COLUMN IF NOT EXISTS canonical_phone TEXT,
    ADD COLUMN IF NOT EXISTS phone_last10 TEXT,
    ADD COLUMN IF NOT EXISTS source_message_ref TEXT,
    ADD COLUMN IF NOT EXISTS source_timestamp TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source_context TEXT,
    ADD COLUMN IF NOT EXISTS message_hash TEXT,
    ADD COLUMN IF NOT EXISTS critical_contact BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS critical_log_path TEXT,
    ADD COLUMN IF NOT EXISTS original_sender_number TEXT;

CREATE INDEX IF NOT EXISTS idx_fazle_messages_canonical_phone
    ON fazle_whatsapp_messages (canonical_phone, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_fazle_messages_phone_last10
    ON fazle_whatsapp_messages (phone_last10, received_at DESC);

DROP INDEX IF EXISTS uq_fazle_messages_hash;
CREATE UNIQUE INDEX IF NOT EXISTS uq_fazle_messages_hash
    ON fazle_whatsapp_messages (message_hash);
"""


async def init_tables() -> None:
    for stmt in _SCHEMA_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            await execute(stmt)


async def save_message(
    *,
    platform: str,
    sender: str,
    text: str,
    direction: str,
    identity_role: str = "",
    identity_confidence: int | None = None,
    workflow: str = "",
    event_ts: datetime | None = None,
    source_ref: str = "",
    source_context: str = "live",
    metadata: dict[str, Any] | None = None,
    conn: asyncpg.Connection | None = None,
) -> bool:
    canonical_sender = canonical_phone(sender)
    last10 = phone_last10(canonical_sender or sender)
    critical = is_critical_phone(canonical_sender or sender, identity_role)
    message_hash = build_message_hash(
        platform=platform,
        canonical_sender=canonical_sender or sender,
        direction=direction,
        text=text,
        event_ts=event_ts,
        source_ref=source_ref,
    )
    meta = dict(metadata or {})
    meta.setdefault("canonical_phone", canonical_sender)
    meta.setdefault("phone_last10", last10)
    meta.setdefault("source_context", source_context)
    meta.setdefault("source_ref", source_ref)
    fetch_value = conn.fetchval if conn is not None else fetch_val
    exec_value = conn.execute if conn is not None else execute
    row = await fetch_value(
        """
        INSERT INTO fazle_whatsapp_messages
            (sender_number, message_body, message_type, direction,
             platform, is_processed, contact_identifier,
             identity_role, identity_confidence, workflow_triggered,
             received_at, metadata_json, canonical_phone,
             phone_last10, source_message_ref, source_timestamp,
             source_context, message_hash, critical_contact,
             original_sender_number)
        VALUES ($1, $2, 'text', $3, $4, true, $5, $6, $7, $8,
                COALESCE($9, NOW()), $10::jsonb, $11, $12, $13, $9,
                $14, $15, $16, $17)
        ON CONFLICT (message_hash) DO NOTHING
        RETURNING message_id
        """,
        canonical_sender or sender,
        text,
        direction,
        platform,
        canonical_sender or sender,
        identity_role or None,
        identity_confidence,
        workflow or None,
        event_ts,
        json.dumps(meta, ensure_ascii=False),
        canonical_sender or None,
        last10 or None,
        source_ref or None,
        source_context or None,
        message_hash,
        critical,
        sender or None,
    )
    if not row:
        return False

    # Link to contact if phone match exists
    try:
        contact_id = await fetch_value(
            """SELECT contact_id FROM fazle_contacts
               WHERE RIGHT(whatsapp_number, 10) = RIGHT($1, 10)
               LIMIT 1""",
            canonical_sender or sender,
        )
        if contact_id:
            await exec_value(
                "UPDATE fazle_whatsapp_messages SET contact_id=$2 WHERE message_id=$1",
                row,
                contact_id,
            )
    except Exception as e:
        log.warning(f"Failed to link contact for message {row}: {e}")

    if critical:
        log_path = append_critical_log(
            phone=canonical_sender or sender,
            direction=direction,
            text=text,
            platform=platform,
            identity_role=identity_role,
            event_ts=event_ts,
            original_phone=sender,
        )
        if log_path:
            await exec_value(
                "UPDATE fazle_whatsapp_messages SET critical_log_path=$2 WHERE message_id=$1",
                row,
                log_path,
            )
    return True