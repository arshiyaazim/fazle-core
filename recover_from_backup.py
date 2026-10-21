#!/usr/bin/env python3
import argparse
import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from app.database import close_db, fetch_val, init_db
from modules.fazle_identity_brain import detect_identity
from modules.fazle_message_archive import init_tables as init_archive_tables, save_message
from modules.number_identity import canonical_phone, phone_last10


@dataclass(frozen=True)
class BridgeSource:
    name: str
    messages_db: str
    whatsapp_db: str


BRIDGES = {
    "bridge1": BridgeSource(
        name="bridge1",
        messages_db="/home/azim/bridges/bridge1/store/messages.db",
        whatsapp_db="/home/azim/bridges/bridge1/store/whatsapp.db",
    ),
    "bridge2": BridgeSource(
        name="bridge2",
        messages_db="/home/azim/bridges/bridge2/store/messages.db",
        whatsapp_db="/home/azim/bridges/bridge2/store/whatsapp.db",
    ),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recover missing WhatsApp messages from bridge SQLite backups")
    parser.add_argument("--bridge", choices=["bridge1", "bridge2", "all"], default="all")
    parser.add_argument("--phone", action="append", dest="phones", default=[], help="Target phone number; repeatable")
    parser.add_argument("--since", default="", help="Inclusive ISO timestamp, e.g. 2026-04-01 or 2026-04-01T00:00:00+06:00")
    parser.add_argument("--until", default="", help="Exclusive ISO timestamp")
    parser.add_argument("--limit", type=int, default=0, help="Per-bridge row limit after filtering")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _load_lid_map(whatsapp_db: str) -> dict[str, str]:
    con = sqlite3.connect(f"file:{whatsapp_db}?mode=ro", uri=True, check_same_thread=False)
    try:
        return {
            str(row[0]): str(row[1])
            for row in con.execute("SELECT lid, pn FROM whatsmeow_lid_map")
        }
    finally:
        con.close()


def _fetch_bridge_rows(source: BridgeSource) -> list[dict]:
    lid_map = _load_lid_map(source.whatsapp_db)
    con = sqlite3.connect(f"file:{source.messages_db}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT id, chat_jid, sender, content, processed_text, timestamp, is_from_me
            FROM messages
            WHERE chat_jid NOT LIKE '%@g.us'
              AND chat_jid NOT LIKE '%@newsletter'
              AND chat_jid != 'status@broadcast'
              AND (content IS NOT NULL OR processed_text IS NOT NULL)
            ORDER BY datetime(timestamp) ASC
            """
        ).fetchall()
    finally:
        con.close()

    recovered = []
    for row in rows:
        text = (row["content"] or row["processed_text"] or "").strip()
        if not text:
            continue
        ts = datetime.fromisoformat(row["timestamp"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        chat_jid = row["chat_jid"] or ""
        sender = row["sender"] or ""
        sender_lid = str(sender).split(":")[0].split("@")[0]
        phone = ""
        if row["is_from_me"]:
            if chat_jid.endswith("@s.whatsapp.net"):
                phone = chat_jid.replace("@s.whatsapp.net", "")
        else:
            phone = lid_map.get(sender_lid, "")
            if not phone and chat_jid.endswith("@s.whatsapp.net"):
                phone = chat_jid.replace("@s.whatsapp.net", "")
        if not phone:
            continue
        recovered.append(
            {
                "id": row["id"],
                "phone": phone,
                "text": text,
                "timestamp": ts,
                "direction": "outbound" if row["is_from_me"] else "inbound",
                "chat_jid": chat_jid,
            }
        )
    return recovered


async def _message_exists(phone: str, direction: str, text: str, event_ts: datetime) -> bool:
    canon = canonical_phone(phone)
    last10 = phone_last10(canon or phone)
    exists = await fetch_val(
        """
        SELECT 1
        FROM fazle_whatsapp_messages
        WHERE direction = $1
          AND COALESCE(message_body, '') = $2
          AND ABS(EXTRACT(EPOCH FROM (received_at - $3::timestamptz))) < 2
          AND (
                canonical_phone = $4
             OR sender_number = $4
             OR contact_identifier = $4
             OR phone_last10 = $5
             OR right(regexp_replace(COALESCE(sender_number, ''), '\\D', '', 'g'), 10) = $5
             OR right(regexp_replace(COALESCE(contact_identifier, ''), '\\D', '', 'g'), 10) = $5
          )
        LIMIT 1
        """,
        direction,
        text,
        event_ts,
        canon or phone,
        last10,
    )
    return exists is not None


def _target_last10(phones: list[str]) -> set[str]:
    values = set()
    for phone in phones:
        canon = canonical_phone(phone)
        tail = phone_last10(canon or phone)
        if tail:
            values.add(tail)
    return values


async def _recover_bridge(
    source: BridgeSource,
    *,
    target_last10: set[str],
    since: datetime | None,
    until: datetime | None,
    limit: int,
    dry_run: bool,
) -> dict[str, int]:
    rows = _fetch_bridge_rows(source)
    if since:
        rows = [row for row in rows if row["timestamp"] >= since]
    if until:
        rows = [row for row in rows if row["timestamp"] < until]
    if target_last10:
        rows = [row for row in rows if phone_last10(row["phone"]) in target_last10]
    if limit > 0:
        rows = rows[:limit]

    scanned = inserted = skipped_existing = 0
    for row in rows:
        scanned += 1
        if await _message_exists(row["phone"], row["direction"], row["text"], row["timestamp"]):
            skipped_existing += 1
            continue
        identity = await detect_identity(row["phone"], row["text"])
        if not dry_run:
            await save_message(
                platform=source.name,
                sender=row["phone"],
                text=row["text"],
                direction=row["direction"],
                identity_role=identity.get("identity_role", ""),
                identity_confidence=identity.get("identity_confidence"),
                event_ts=row["timestamp"],
                source_ref=row["id"],
                source_context="recovered_backup",
                metadata={"chat_jid": row["chat_jid"], "recovered_from": source.messages_db},
            )
        inserted += 1
    return {
        "scanned": scanned,
        "inserted": inserted,
        "skipped_existing": skipped_existing,
    }


async def _main() -> int:
    args = _parse_args()
    since = _parse_ts(args.since)
    until = _parse_ts(args.until)
    target_last10 = _target_last10(args.phones)
    await init_db()
    await init_archive_tables()
    try:
        bridge_names = [args.bridge] if args.bridge != "all" else ["bridge1", "bridge2"]
        for bridge_name in bridge_names:
            summary = await _recover_bridge(
                BRIDGES[bridge_name],
                target_last10=target_last10,
                since=since,
                until=until,
                limit=args.limit,
                dry_run=args.dry_run,
            )
            print(
                f"{bridge_name}: scanned={summary['scanned']} inserted={summary['inserted']} "
                f"skipped_existing={summary['skipped_existing']} dry_run={args.dry_run}"
            )
    finally:
        await close_db()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))