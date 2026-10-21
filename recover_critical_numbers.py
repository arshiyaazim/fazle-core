#!/usr/bin/env python3
import argparse
import asyncio
import os
import shutil
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import get_settings
from app.critical_numbers import CRITICAL_NUMBERS, normalize_phone_880
from app.database import close_db, fetch_all, fetch_one, get_pool, init_db
from modules.fazle_identity_brain import detect_identity
from modules.fazle_message_archive import init_tables as init_archive_tables, save_message
from modules.number_identity import canonical_phone, format_critical_log_line, phone_last10


REPORT_PATH = "/home/azim/core/reports/critical_recovery_report.txt"


@dataclass(frozen=True)
class BridgeSource:
    name: str
    messages_db: str
    whatsapp_db: str


BRIDGES = (
    BridgeSource(
        name="bridge1",
        messages_db="/home/azim/bridges/bridge1/store/messages.db",
        whatsapp_db="/home/azim/bridges/bridge1/store/whatsapp.db",
    ),
    BridgeSource(
        name="bridge2",
        messages_db="/home/azim/bridges/bridge2/store/messages.db",
        whatsapp_db="/home/azim/bridges/bridge2/store/whatsapp.db",
    ),
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recover and validate all critical WhatsApp numbers")
    parser.add_argument("--since", default="", help="Inclusive ISO timestamp")
    parser.add_argument("--until", default="", help="Exclusive ISO timestamp")
    parser.add_argument("--number", action="append", dest="numbers", default=[], help="Optional critical number override")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _critical_numbers(selected: list[str]) -> list[str]:
    if selected:
        return sorted({normalize_phone_880(number) for number in selected if normalize_phone_880(number)})
    return list(CRITICAL_NUMBERS)


def _load_lid_map(whatsapp_db: str) -> dict[str, str]:
    con = sqlite3.connect(f"file:{whatsapp_db}?mode=ro", uri=True, check_same_thread=False)
    try:
        return {str(row[0]): str(row[1]) for row in con.execute("SELECT lid, pn FROM whatsmeow_lid_map")}
    finally:
        con.close()


def _load_bridge_rows(source: BridgeSource, targets_last10: set[str], since: datetime | None, until: datetime | None) -> list[dict]:
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

    out = []
    for row in rows:
        text = (row["content"] or row["processed_text"] or "").strip()
        if not text:
            continue
        ts = datetime.fromisoformat(row["timestamp"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if since and ts < since:
            continue
        if until and ts >= until:
            continue
        chat_jid = row["chat_jid"] or ""
        sender = row["sender"] or ""
        sender_lid = str(sender).split(":")[0].split("@")[0]
        raw_phone = ""
        if row["is_from_me"]:
            if chat_jid.endswith("@s.whatsapp.net"):
                raw_phone = chat_jid[:-15]
        else:
            raw_phone = lid_map.get(sender_lid, "")
            if not raw_phone and chat_jid.endswith("@s.whatsapp.net"):
                raw_phone = chat_jid[:-15]
        canon = canonical_phone(raw_phone)
        if not canon or phone_last10(canon) not in targets_last10:
            continue
        out.append(
            {
                "id": row["id"],
                "source_name": source.name,
                "source_label": source.name,
                "phone": canon,
                "direction": "outbound" if row["is_from_me"] else "inbound",
                "timestamp": ts,
                "text": text,
                "chat_jid": chat_jid,
            }
        )
    return out


def _discover_phone_backup_sources() -> list[str]:
    found = []
    for root in ("/home/azim/backups",):
        if not os.path.isdir(root):
            continue
        for base, _dirs, files in os.walk(root):
            for name in files:
                lower = name.lower()
                if lower.startswith("msgstore") and ".db" in lower:
                    found.append(os.path.join(base, name))
                elif lower in {"wa.db", "wa.db.crypt14", "wa.db.crypt15"}:
                    found.append(os.path.join(base, name))
    return sorted(found)


def _message_key(phone: str, direction: str, ts: datetime, text: str) -> tuple[str, str, str, str]:
    canon = canonical_phone(phone)
    return (
        canon,
        direction,
        ts.astimezone(timezone.utc).isoformat(),
        __import__("hashlib").sha256((text or "").encode("utf-8")).hexdigest(),
    )


async def _fetch_db_messages(numbers: list[str], since: datetime | None, until: datetime | None) -> dict[str, list[dict]]:
    rows = await fetch_all(
        """
        SELECT message_id, sender_number, contact_identifier, canonical_phone,
               phone_last10, direction, COALESCE(message_body, '') AS body,
               COALESCE(source_timestamp, received_at) AS event_ts,
               source_context, critical_contact, identity_role, critical_log_path,
               original_sender_number, platform
        FROM fazle_whatsapp_messages
        WHERE phone_last10 = ANY($1::text[])
           OR right(regexp_replace(COALESCE(canonical_phone, ''), '\\D', '', 'g'), 10) = ANY($1::text[])
           OR right(regexp_replace(COALESCE(sender_number, ''), '\\D', '', 'g'), 10) = ANY($1::text[])
           OR right(regexp_replace(COALESCE(contact_identifier, ''), '\\D', '', 'g'), 10) = ANY($1::text[])
        ORDER BY COALESCE(source_timestamp, received_at) ASC, message_id ASC
        """,
        [number[-10:] for number in numbers],
    )
    out = defaultdict(list)
    for row in rows:
        ts = row["event_ts"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if since and ts < since:
            continue
        if until and ts >= until:
            continue
        canon = canonical_phone(
            row.get("canonical_phone") or row.get("sender_number") or row.get("contact_identifier") or ""
        )
        if not canon:
            continue
        out[canon].append({**row, "event_ts": ts, "canonical_phone": canon})
    return out


async def _normalize_existing_message_rows(conn, numbers: list[str]) -> None:
    rows = await conn.fetch(
        """
        SELECT message_id, sender_number, contact_identifier, canonical_phone, critical_log_path
        FROM fazle_whatsapp_messages
        WHERE phone_last10 = ANY($1::text[])
           OR right(regexp_replace(COALESCE(canonical_phone, ''), '\\D', '', 'g'), 10) = ANY($1::text[])
           OR right(regexp_replace(COALESCE(sender_number, ''), '\\D', '', 'g'), 10) = ANY($1::text[])
           OR right(regexp_replace(COALESCE(contact_identifier, ''), '\\D', '', 'g'), 10) = ANY($1::text[])
        """,
        [number[-10:] for number in numbers],
    )
    settings = get_settings()
    os.makedirs(settings.critical_log_dir, exist_ok=True)
    for row in rows:
        canon = canonical_phone(row["canonical_phone"] or row["sender_number"] or row["contact_identifier"] or "")
        if not canon:
            continue
        log_path = row.get("critical_log_path") or ""
        canonical_log_path = os.path.join(settings.critical_log_dir, f"{canon}.txt")
        if log_path and log_path != canonical_log_path and os.path.exists(log_path):
            if os.path.exists(canonical_log_path):
                with open(log_path, "r", encoding="utf-8") as src, open(canonical_log_path, "a", encoding="utf-8") as dst:
                    dst.write(src.read())
                os.remove(log_path)
            else:
                shutil.move(log_path, canonical_log_path)
        await conn.execute(
            """
            UPDATE fazle_whatsapp_messages
            SET canonical_phone = $2,
                phone_last10 = $3,
                critical_contact = true,
                critical_log_path = CASE WHEN critical_log_path IS NOT NULL THEN $4 ELSE critical_log_path END
            WHERE message_id = $1
            """,
            row["message_id"],
            canon,
            canon[-10:],
            canonical_log_path,
        )


async def _unify_critical_contacts(conn, numbers: list[str]) -> dict[str, str]:
    names = {}
    for number in numbers:
        rows = await conn.fetch(
            """
            SELECT display_name, updated_at
            FROM fazle_contacts
            WHERE regexp_replace(COALESCE(whatsapp_number, ''), '\\D', '', 'g') = $1
            ORDER BY updated_at DESC NULLS LAST, display_name DESC
            """,
            number,
        )
        unified = await conn.fetchrow(
            "SELECT display_name, last_updated FROM fazle_unified_contacts WHERE phone = $1",
            number,
        )
        candidates = []
        for row in rows:
            if row["display_name"]:
                candidates.append((row["display_name"], row["updated_at"]))
        if unified and unified["display_name"]:
            candidates.append((unified["display_name"], unified["last_updated"]))
        latest_name = ""
        if candidates:
            latest_name = sorted(candidates, key=lambda item: (item[1] is not None, item[1], len(item[0]), item[0]), reverse=True)[0][0]
        names[number] = latest_name
        if latest_name:
            await conn.execute(
                """
                INSERT INTO fazle_unified_contacts (phone, display_name, source_bridge, last_updated)
                VALUES ($1, $2, 'critical_recovery', NOW())
                ON CONFLICT (phone) DO UPDATE
                    SET display_name = EXCLUDED.display_name,
                        source_bridge = EXCLUDED.source_bridge,
                        last_updated = NOW()
                """,
                number,
                latest_name,
            )
            await conn.execute(
                """
                INSERT INTO fazle_contacts (whatsapp_number, display_name, platform, last_seen, updated_at)
                VALUES ($1, $2, 'whatsapp', NOW(), NOW())
                ON CONFLICT (whatsapp_number, platform) DO UPDATE
                    SET display_name = EXCLUDED.display_name,
                        updated_at = NOW(),
                        last_seen = NOW()
                """,
                number,
                latest_name,
            )
        for alias_name, _updated_at in candidates:
            if alias_name:
                await conn.execute(
                    """
                    INSERT INTO fazle_contact_aliases (phone, alias_name, source_bridge, last_seen)
                    VALUES ($1, $2, 'critical_recovery', NOW())
                    ON CONFLICT (phone, alias_name) DO UPDATE
                        SET source_bridge = EXCLUDED.source_bridge,
                            last_seen = NOW()
                    """,
                    number,
                    alias_name,
                )
    return names


async def _sync_transcript_file(conn, number: str) -> tuple[str, int]:
    settings = get_settings()
    os.makedirs(settings.critical_log_dir, exist_ok=True)
    path = os.path.join(settings.critical_log_dir, f"{number}.txt")
    existing = set()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            existing = set(handle.readlines())
    rows = await conn.fetch(
        """
        SELECT COALESCE(source_timestamp, received_at) AS event_ts,
               platform, direction, COALESCE(message_body, '') AS body,
               COALESCE(identity_role, '') AS identity_role,
               COALESCE(original_sender_number, sender_number, '') AS original_sender_number,
               message_id
        FROM fazle_whatsapp_messages
        WHERE canonical_phone = $1
        ORDER BY COALESCE(source_timestamp, received_at) ASC, message_id ASC
        """,
        number,
    )
    appended = 0
    with open(path, "a", encoding="utf-8") as handle:
        for row in rows:
            ts = row["event_ts"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            line = format_critical_log_line(
                phone=number,
                direction=row["direction"],
                text=row["body"],
                platform=row["platform"],
                identity_role=row["identity_role"],
                event_ts=ts,
                original_phone=row["original_sender_number"],
            )
            if line in existing:
                continue
            handle.write(line)
            existing.add(line)
            appended += 1
    await conn.execute(
        "UPDATE fazle_whatsapp_messages SET critical_log_path = $2 WHERE canonical_phone = $1",
        number,
        path,
    )
    return path, appended


async def _recover_number(conn, number: str, db_rows: list[dict], source_rows: list[dict], dry_run: bool) -> dict:
    db_keys = {_message_key(row["canonical_phone"], row["direction"], row["event_ts"], row["body"]) for row in db_rows}
    source_map = {}
    for row in source_rows:
        source_map.setdefault(_message_key(row["phone"], row["direction"], row["timestamp"], row["text"]), row)
    missing_keys = [key for key in source_map if key not in db_keys]
    recovered = 0
    if not dry_run and missing_keys:
        async with conn.transaction():
            for key in missing_keys:
                row = source_map[key]
                identity = await detect_identity(row["phone"], row["text"])
                inserted = await save_message(
                    platform=row["source_name"],
                    sender=row["phone"],
                    text=row["text"],
                    direction=row["direction"],
                    identity_role=identity.get("identity_role", ""),
                    identity_confidence=identity.get("identity_confidence"),
                    event_ts=row["timestamp"],
                    source_ref=row["id"],
                    source_context="recovered_backup",
                    metadata={"chat_jid": row["chat_jid"], "recovered_from": row["source_label"]},
                    conn=conn,
                )
                if inserted:
                    recovered += 1
    return {
        "backup_total": len(source_map),
        "recovered": recovered if not dry_run else len(missing_keys),
        "missing_before": len(missing_keys),
    }


def _available_sources_note(phone_backup_sources: list[str], source_rows: list[dict]) -> str:
    if source_rows:
        if phone_backup_sources:
            return "bridge_sqlite + phone_backup"
        return "bridge_sqlite"
    if phone_backup_sources:
        return "phone_backup"
    return "Recovery not possible: source data unavailable"


async def _build_report(numbers: list[str], since: datetime | None, until: datetime | None, dry_run: bool) -> str:
    pool = get_pool()
    phone_backup_sources = _discover_phone_backup_sources()
    bridge_rows = []
    tails = {number[-10:] for number in numbers}
    for bridge in BRIDGES:
        bridge_rows.extend(_load_bridge_rows(bridge, tails, since, until))

    by_source_number = defaultdict(list)
    for row in bridge_rows:
        by_source_number[row["phone"]].append(row)

    async with pool.acquire() as conn:
        await _normalize_existing_message_rows(conn, numbers)
        names = await _unify_critical_contacts(conn, numbers)
        db_before = await _fetch_db_messages(numbers, since, until)
        summaries = {}
        for number in numbers:
            result = await _recover_number(conn, number, db_before.get(number, []), by_source_number.get(number, []), dry_run)
            summaries[number] = result
        db_after = await _fetch_db_messages(numbers, since, until)
        transcript_stats = {}
        for number in numbers:
            transcript_stats[number] = await _sync_transcript_file(conn, number)

    lines = [
        f"Critical recovery report generated at {datetime.now(timezone.utc).isoformat()}",
        f"Window since={since.isoformat() if since else 'unbounded'} until={until.isoformat() if until else 'unbounded'} dry_run={dry_run}",
        f"Phone backup sources: {', '.join(phone_backup_sources) if phone_backup_sources else 'none'}",
        "",
    ]
    for number in numbers:
        db_total = len(db_after.get(number, []))
        backup_total = summaries[number]["backup_total"]
        recovered = summaries[number]["recovered"]
        db_after_keys = {
            _message_key(row["canonical_phone"], row["direction"], row["event_ts"], row["body"])
            for row in db_after.get(number, [])
        }
        source_keys = {
            _message_key(row["phone"], row["direction"], row["timestamp"], row["text"])
            for row in by_source_number.get(number, [])
        }
        missing = len(source_keys - db_after_keys)
        status = "OK" if missing == 0 and backup_total > 0 else "NOT RECOVERABLE" if missing > 0 else _available_sources_note(phone_backup_sources, by_source_number.get(number, []))
        transcript_path, transcript_appended = transcript_stats[number]
        lines.extend([
            f"Number: {number}",
            f"Name: {names.get(number, '') or 'Unknown'}",
            f"DB: {db_total}",
            f"Backup: {backup_total}",
            f"Recovered: {recovered}",
            f"Missing: {missing}",
            f"Status: {status}",
            f"Sources: {_available_sources_note(phone_backup_sources, by_source_number.get(number, []))}",
            f"Transcript: {transcript_path} (appended={transcript_appended})",
            "",
        ])
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")
    return REPORT_PATH


async def _main() -> int:
    args = _parse_args()
    since = _parse_ts(args.since)
    until = _parse_ts(args.until)
    numbers = _critical_numbers(args.numbers)
    await init_db()
    await init_archive_tables()
    try:
        report_path = await _build_report(numbers, since, until, args.dry_run)
        print(report_path)
    finally:
        await close_db()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))