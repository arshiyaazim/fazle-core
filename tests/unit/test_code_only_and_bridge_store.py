from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from shared.bridge_store import (
    BridgeStoreSpec,
    inspect_bridge_store,
    message_projection,
    resolve_message_schema,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_database_disabled_mode_is_explicit_and_never_accepts_writes(monkeypatch):
    monkeypatch.setenv("DATABASE_MODE", "disabled")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from app.config import get_settings
    from app import database

    get_settings.cache_clear()
    try:
        assert get_settings().resolved_database_mode == "disabled"
        assert await database.init_db() is False
        assert database.database_status() == {
            "mode": "disabled",
            "enabled": False,
            "connected": False,
            "persistent": False,
        }
        with pytest.raises(database.DatabaseUnavailable, match="DATABASE_MODE=disabled"):
            await database.execute("INSERT INTO anything(value) VALUES($1)", "not-persisted")
    finally:
        await database.close_db()
        get_settings.cache_clear()


def _create_messages(path, *, aliases: bool = False):
    con = sqlite3.connect(path)
    if aliases:
        con.execute(
            """
            CREATE TABLE whatsapp_messages (
                message_id TEXT PRIMARY KEY,
                remote_jid TEXT NOT NULL,
                sender_jid TEXT NOT NULL,
                body TEXT,
                created_at TEXT NOT NULL,
                from_me INTEGER NOT NULL,
                message_type TEXT,
                media_url TEXT
            )
            """
        )
    else:
        con.execute(
            """
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                chat_jid TEXT NOT NULL,
                sender TEXT NOT NULL,
                content TEXT,
                timestamp TEXT NOT NULL,
                is_from_me INTEGER NOT NULL,
                media_type TEXT,
                filename TEXT,
                url TEXT,
                from_history_sync INTEGER DEFAULT 0
            )
            """
        )
    con.commit()
    con.close()


@pytest.mark.unit
def test_bridge_store_preflight_accepts_stock_schema_read_only(tmp_path):
    messages = tmp_path / "messages.db"
    whatsapp = tmp_path / "whatsapp.db"
    _create_messages(messages)
    con = sqlite3.connect(whatsapp)
    con.execute("CREATE TABLE whatsmeow_lid_map (lid TEXT, pn TEXT)")
    con.commit()
    con.close()

    report = inspect_bridge_store(BridgeStoreSpec("bridge1", str(messages), str(whatsapp)))

    assert report.compatible is True
    assert report.status == "compatible"
    assert report.message_table == "messages"
    assert report.columns["chat_jid"] == "chat_jid"
    assert report.schema_fingerprint
    assert report.warnings == []


@pytest.mark.unit
def test_bridge_store_aliases_project_to_canonical_row_shape(tmp_path):
    messages = tmp_path / "mcp-bridge.db"
    _create_messages(messages, aliases=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(messages)
    con.execute(
        "INSERT INTO whatsapp_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "m-1",
            "8801700000000@s.whatsapp.net",
            "8801700000000@s.whatsapp.net",
            "hello",
            timestamp,
            0,
            None,
            None,
        ),
    )
    con.commit()
    con.close()

    report = inspect_bridge_store(BridgeStoreSpec("mcp", f"sqlite:///{messages}"))
    assert report.compatible is True
    assert report.columns["id"] == "message_id"
    assert report.columns["content"] == "body"

    con = sqlite3.connect(f"file:{messages}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    table, columns = resolve_message_schema(con)
    row = con.execute(
        f'SELECT {message_projection(columns)} FROM "{table}"'
    ).fetchone()
    con.close()

    assert dict(row)["id"] == "m-1"
    assert dict(row)["chat_jid"].endswith("@s.whatsapp.net")
    assert dict(row)["content"] == "hello"
    assert dict(row)["processed_text"] is None

    # The real live-inbound reader consumes the same adapter and must retain
    # its historical canonical output contract.
    whatsapp = tmp_path / "whatsapp.db"
    con = sqlite3.connect(whatsapp)
    con.execute("CREATE TABLE whatsmeow_lid_map (lid TEXT, pn TEXT)")
    con.commit()
    con.close()
    from modules.fazle_bridge_poller import _fetch_new_messages

    rows, max_seen = _fetch_new_messages(
        str(messages),
        str(whatsapp),
        datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    assert rows[0]["id"] == "m-1"
    assert rows[0]["text"] == "hello"
    assert rows[0]["phone"] == "8801700000000"
    assert max_seen > datetime(2000, 1, 1, tzinfo=timezone.utc)


@pytest.mark.unit
def test_bridge_store_reports_incompatible_schema(tmp_path):
    messages = tmp_path / "broken.db"
    con = sqlite3.connect(messages)
    con.execute("CREATE TABLE messages (id TEXT, content TEXT)")
    con.commit()
    con.close()

    report = inspect_bridge_store(BridgeStoreSpec("broken", str(messages)))

    assert report.compatible is False
    assert report.status == "incompatible"
    assert {"chat_jid", "sender", "timestamp", "is_from_me"} <= set(
        report.missing_required
    )
