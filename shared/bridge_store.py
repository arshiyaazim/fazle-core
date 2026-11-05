"""Read-only compatibility layer for WhatsApp MCP/whatsmeow SQLite stores.

The bridge database is owned by the bridge process, not Fazle Core.  This
module therefore opens it with SQLite ``mode=ro``, introspects the schema and
returns a portable report; it never creates or migrates bridge tables.

Stock bridge column names are canonical. A small alias set is accepted so a
new MCP bridge build can be checked before Core is pointed at it. Runtime
polling still receives the canonical field names through ``message_projection``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse
import hashlib
import sqlite3


MESSAGE_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("id", "message_id", "msg_id"),
    "chat_jid": ("chat_jid", "chat_id", "remote_jid"),
    "sender": ("sender", "sender_jid", "participant"),
    "content": ("content", "text", "body", "message"),
    "timestamp": ("timestamp", "created_at", "message_timestamp"),
    "is_from_me": ("is_from_me", "from_me", "is_outgoing"),
    "media_type": ("media_type", "type", "message_type"),
    "filename": ("filename", "file_name"),
    "url": ("url", "media_url"),
    "processed_text": ("processed_text", "ocr_text", "transcript"),
    "from_history_sync": ("from_history_sync", "history_sync"),
}

REQUIRED_MESSAGE_COLUMNS = frozenset(
    {"id", "chat_jid", "sender", "content", "timestamp", "is_from_me"}
)
MESSAGE_TABLE_ALIASES = ("messages", "message", "whatsapp_messages")


class BridgeStoreError(RuntimeError):
    """A bridge store cannot be opened safely or does not meet the contract."""


@dataclass(frozen=True)
class BridgeStoreSpec:
    name: str
    messages: str
    whatsapp: str = ""


@dataclass
class BridgeStoreReport:
    name: str
    messages_path: str
    whatsapp_path: str
    status: str
    compatible: bool
    message_table: str | None = None
    columns: dict[str, str] = field(default_factory=dict)
    missing_required: list[str] = field(default_factory=list)
    optional_missing: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    whatsapp_tables: list[str] = field(default_factory=list)
    schema_fingerprint: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def sqlite_path(value: str) -> Path:
    """Convert a plain path or sqlite URI/DSN to an absolute filesystem path."""
    raw = str(value or "").strip()
    if not raw:
        raise BridgeStoreError("bridge messages database path is empty")
    if raw.startswith("file:"):
        # file:/x, file:///x and file:/x?mode=ro are all accepted.
        raw = raw[5:].split("?", 1)[0]
    elif "://" in raw:
        parsed = urlparse(raw)
        if parsed.scheme not in {"sqlite", "sqlite3"}:
            raise BridgeStoreError(
                f"unsupported bridge store scheme {parsed.scheme!r}; expected sqlite"
            )
        raw = unquote(parsed.path)
        if parsed.netloc and parsed.netloc not in {"", "localhost"}:
            raise BridgeStoreError("remote SQLite hosts are not supported")
        # ``sqlite:////absolute/path`` parses with a double-leading slash;
        # SQLite interprets ``file://host`` as an authority, so normalize it.
        if raw.startswith("//"):
            raw = "/" + raw.lstrip("/")
    path = Path(raw).expanduser()
    return path if path.is_absolute() else path.resolve()


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise BridgeStoreError(f"file not found: {path}")
    # immutable=1 can return stale data for a live WAL database, so use mode=ro.
    con = sqlite3.connect(
        f"file:{path}?mode=ro", uri=True, check_same_thread=False, timeout=5.0
    )
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    return con


def _tables(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    rows = con.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()
    return [str(row[1]) for row in rows]


def resolve_message_table(con: sqlite3.Connection) -> str | None:
    """Return the first supported physical message table name."""
    available = set(_tables(con))
    return next((name for name in MESSAGE_TABLE_ALIASES if name in available), None)


def resolve_message_columns(
    available: Iterable[str],
) -> tuple[dict[str, str], list[str]]:
    """Resolve physical bridge columns to Core's canonical message fields."""
    lookup = {str(name).lower(): str(name) for name in available}
    resolved: dict[str, str] = {}
    for canonical, aliases in MESSAGE_COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower() in lookup:
                resolved[canonical] = lookup[alias.lower()]
                break
    missing = sorted(REQUIRED_MESSAGE_COLUMNS - resolved.keys())
    return resolved, missing


def resolve_message_schema(
    con: sqlite3.Connection,
) -> tuple[str, dict[str, str]]:
    """Resolve and validate the message table on an open read-only connection."""
    table = resolve_message_table(con)
    if not table:
        raise BridgeStoreError(
            "message table missing; expected one of " + ", ".join(MESSAGE_TABLE_ALIASES)
        )
    columns, missing = resolve_message_columns(_columns(con, table))
    if missing:
        raise BridgeStoreError("missing required message fields: " + ", ".join(missing))
    return table, columns


def quote_identifier(value: str) -> str:
    """Quote an identifier resolved from SQLite metadata."""
    return _quote_identifier(value)


def message_projection(columns: dict[str, str]) -> str:
    """Return a safe SELECT projection with stable canonical aliases.

    Required fields must already have been validated. Optional fields become
    ``NULL`` so downstream row shape remains stable across bridge versions.
    """
    fields: list[str] = []
    for canonical in MESSAGE_COLUMN_ALIASES:
        physical = columns.get(canonical)
        if physical:
            fields.append(
                f"{_quote_identifier(physical)} AS {_quote_identifier(canonical)}"
            )
        else:
            fields.append(f"NULL AS {_quote_identifier(canonical)}")
    return ", ".join(fields)


def inspect_bridge_store(spec: BridgeStoreSpec) -> BridgeStoreReport:
    """Inspect one bridge pair and return a serializable compatibility report."""
    try:
        messages_path = sqlite_path(spec.messages)
    except BridgeStoreError as exc:
        return BridgeStoreReport(
            name=spec.name,
            messages_path=str(spec.messages),
            whatsapp_path=str(spec.whatsapp),
            status="error",
            compatible=False,
            error=str(exc),
        )

    report = BridgeStoreReport(
        name=spec.name,
        messages_path=str(messages_path),
        whatsapp_path=str(spec.whatsapp or ""),
        status="error",
        compatible=False,
    )
    try:
        with _connect_readonly(messages_path) as con:
            report.tables = _tables(con)
            report.message_table = next(
                (name for name in MESSAGE_TABLE_ALIASES if name in report.tables), None
            )
            if not report.message_table:
                raise BridgeStoreError(
                    "message table missing; expected one of "
                    + ", ".join(MESSAGE_TABLE_ALIASES)
                )
            physical_columns = _columns(con, report.message_table)
            report.columns, report.missing_required = resolve_message_columns(
                physical_columns
            )
            non_stock = report.message_table != "messages" or any(
                report.columns.get(name) != name
                for name in REQUIRED_MESSAGE_COLUMNS
                if name in report.columns
            )
            if non_stock:
                report.warnings.append(
                    "schema aliases are compatible with live inbound polling; "
                    "historical payroll sync and outgoing escort scanners still "
                    "require the stock messages table/columns"
                )
            report.optional_missing = sorted(
                set(MESSAGE_COLUMN_ALIASES) - set(report.columns)
                - set(report.missing_required)
            )
            fingerprint_source = (
                report.message_table + "\0" + "\0".join(sorted(physical_columns))
            )
            report.schema_fingerprint = hashlib.sha256(
                fingerprint_source.encode("utf-8")
            ).hexdigest()[:16]

        if spec.whatsapp:
            try:
                whatsapp_path = sqlite_path(spec.whatsapp)
                report.whatsapp_path = str(whatsapp_path)
                with _connect_readonly(whatsapp_path) as con:
                    report.whatsapp_tables = _tables(con)
                if not ({"whatsmeow_contacts", "whatsmeow_lid_map"} & set(report.whatsapp_tables)):
                    report.warnings.append(
                        "whatsapp store has no known contacts/LID-map table; direct JIDs "
                        "still work, but unresolved LIDs may need bridge-side mapping"
                    )
            except BridgeStoreError as exc:
                report.warnings.append(f"optional whatsapp store unavailable: {exc}")

        report.compatible = not report.missing_required
        report.status = "compatible" if report.compatible else "incompatible"
        if report.missing_required:
            report.error = "missing required message fields: " + ", ".join(
                report.missing_required
            )
        return report
    except (BridgeStoreError, sqlite3.Error) as exc:
        report.error = str(exc)
        return report


def configured_bridge_specs(settings) -> list[BridgeStoreSpec]:
    """Build specs from Settings without importing app.config in this module."""
    return [
        BridgeStoreSpec("bridge1", settings.bridge1_db_path, settings.bridge1_whatsapp_db_path),
        BridgeStoreSpec("bridge2", settings.bridge2_db_path, settings.bridge2_whatsapp_db_path),
        BridgeStoreSpec("bridge3", settings.bridge3_db_path, settings.bridge3_whatsapp_db_path),
    ]
