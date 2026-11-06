"""
Unit test for whatsapp_mcp history sync — uses temp SQLite DBs (no prod DB needed).
"""
import os
import sqlite3
import tempfile
import pytest

def _make_mock_bridge_db(path: str, n: int = 5):
    con = sqlite3.connect(path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, chat_jid TEXT, sender TEXT, content TEXT,
            timestamp TEXT, media_type TEXT, filename TEXT, url TEXT, is_from_me INTEGER
        )
    """)
    for i in range(n):
        con.execute(
            "INSERT INTO messages (id, chat_jid, sender, content, timestamp, media_type, is_from_me) VALUES (?,?,?,?,?,?,?)",
            (f"msg_{i:03d}", "8801710000001@s.whatsapp.net", "8801710000001:1@s.whatsapp.net", f"hello {i}", f"2026-11-06 10:0{i}:00+06:00", "text", 0),
        )
    # one group, one media
    con.execute(
        "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)",
        ("grp_001", "1203630000000@g.us", "8801710000002:1@s.whatsapp.net", "group hi", "2026-11-06 10:10:00+06:00", "text", None, None, 0),
    )
    con.execute(
        "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)",
        ("med_001", "8801710000003@s.whatsapp.net", "8801710000003:1@s.whatsapp.net", "[media:image]", "2026-11-06 10:11:00+06:00", "image", "photo.jpg", None, 0),
    )
    con.commit()
    con.close()
    # whatsapp.db with lid_map
    wpath = path.replace("messages.db", "whatsapp.db")
    con2 = sqlite3.connect(wpath)
    con2.execute("CREATE TABLE IF NOT EXISTS whatsmeow_lid_map (lid TEXT PRIMARY KEY, pn TEXT)")
    con2.execute("INSERT INTO whatsmeow_lid_map VALUES (?,?)", ("8801710000001:1", "8801710000001"))
    con2.commit()
    con2.close()
    return path, wpath

def test_fetch_history_chunk():
    from modules.whatsapp_mcp.sync import _fetch_history_chunk_sync
    with tempfile.TemporaryDirectory() as tmp:
        mdb = os.path.join(tmp, "messages.db")
        _make_mock_bridge_db(mdb)
        wdb = mdb.replace("messages.db", "whatsapp.db")
        rows, has_more = _fetch_history_chunk_sync(mdb, wdb, offset=0, chunk_size=10)
        assert len(rows) >= 7  # 5 + group + media
        # check fields
        first = rows[0]
        assert first["phone"]
        assert "direction" in first
        assert first["text"]
        # group detection
        grp = [r for r in rows if r["chat_jid"].endswith("@g.us")]
        assert len(grp) == 1

def test_identifier_via_sync_rows():
    from modules.whatsapp_mcp.identifier import parse_identifier
    with tempfile.TemporaryDirectory() as tmp:
        mdb = os.path.join(tmp, "messages.db")
        _make_mock_bridge_db(mdb)
        wdb = mdb.replace("messages.db", "whatsapp.db")
        from modules.whatsapp_mcp.sync import _fetch_history_chunk_sync
        rows, _ = _fetch_history_chunk_sync(mdb, wdb, offset=0, chunk_size=10)
        for r in rows:
            ident = parse_identifier(r, bridge_id="test-bridge")
            assert ident.phone_880 or ident.wa_jid
            assert ident.media_type
            # wa_jid should be set
            assert ident.wa_jid
