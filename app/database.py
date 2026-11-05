"""Fazle Core persistence boundary.

PostgreSQL remains the authoritative production backend.  A deliberately
non-persistent ``disabled`` mode lets the code, static UI, docs, health and
integration preflight tools run before a database is provisioned.  Disabled
mode never acknowledges a business write as successful: database-dependent
calls raise :class:`DatabaseUnavailable` with a stable error contract.

All application SQL continues to pass through this module, which is the seam
for adding another backend adapter later without changing route imports.
"""
import logging
import re
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Optional, Any
import asyncpg
from app.config import get_settings

log = logging.getLogger("fazle.db")
_pool: Optional[asyncpg.Pool] = None


class DatabaseUnavailable(RuntimeError):
    """Raised when a persistence operation is requested in code-only mode."""

    code = "database_disabled"


def database_mode() -> str:
    """Effective backend name (``postgres`` or ``disabled``)."""
    return get_settings().resolved_database_mode


def database_enabled() -> bool:
    return database_mode() == "postgres"


def database_status() -> dict[str, Any]:
    """Side-effect-free runtime status suitable for health/capability APIs."""
    mode = database_mode()
    return {
        "mode": mode,
        "enabled": mode == "postgres",
        "connected": _pool is not None,
        "persistent": mode == "postgres",
    }


def _require_database() -> None:
    if not database_enabled():
        raise DatabaseUnavailable(
            "Database-backed capability is unavailable because Fazle Core is "
            "running with DATABASE_MODE=disabled. Configure DATABASE_URL and "
            "set DATABASE_MODE=postgres (or auto) to enable persistence."
        )


# ── Shadow-mode write guard (Phase B Stage 4, Section 2) ────────────────────
# Hard runtime assertion, not just an architectural convention: while
# shadow_mode_scope() is active, any write statement (INSERT/UPDATE/DELETE/
# TRUNCATE/ALTER/DROP/CREATE) targeting a table outside the conversation-
# memory engine's own tables raises immediately, instead of silently
# succeeding. Applied at this module's single choke point (every SQL
# statement in the app goes through fetch_one/fetch_all/execute/fetch_val)
# so it can't be bypassed by a future caller forgetting to check a flag.
_shadow_mode_active: ContextVar[bool] = ContextVar("_shadow_mode_active", default=False)

SHADOW_MODE_ALLOWED_WRITE_TABLES = frozenset({
    "fazle_conversation_threads",
    "processed_conversation_messages",
    "fazle_conversation_shadow_comparisons",
})

_WRITE_STMT_RE = re.compile(
    r"^\s*(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?|ALTER\s+TABLE|DROP\s+TABLE|CREATE\s+TABLE)"
    r"\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?\"?([A-Za-z_][A-Za-z0-9_]*)\"?",
    re.IGNORECASE,
)


class ShadowModeWriteViolation(RuntimeError):
    """Raised when code running inside shadow_mode_scope() attempts to
    write to a table outside SHADOW_MODE_ALLOWED_WRITE_TABLES. Caught by
    the same broad exception handler every shadow-mode call site already
    wraps itself in (Part 13's fail-open contract) -- this is a hard
    safety net, not a new failure mode callers need to handle specially."""


def _check_shadow_write_guard(sql: str) -> None:
    if not _shadow_mode_active.get():
        return
    match = _WRITE_STMT_RE.match(sql)
    if not match:
        return
    table = match.group(1).lower()
    if table not in SHADOW_MODE_ALLOWED_WRITE_TABLES:
        raise ShadowModeWriteViolation(
            f"shadow-mode code attempted to write to business table {table!r} "
            f"(sql: {sql[:160]!r})"
        )


@asynccontextmanager
async def shadow_mode_scope():
    """Wrap any observational/shadow code path in this. Every fetch_one/
    fetch_all/execute/fetch_val call made anywhere in the call tree while
    this is active is checked against SHADOW_MODE_ALLOWED_WRITE_TABLES."""
    token = _shadow_mode_active.set(True)
    try:
        yield
    finally:
        _shadow_mode_active.reset(token)


async def init_db() -> bool:
    """Initialize the configured backend.

    Returns ``True`` when PostgreSQL is ready and ``False`` in explicit or
    auto-selected code-only mode. Connection failures in PostgreSQL mode still
    raise, preserving the production fail-fast contract.
    """
    global _pool
    settings = get_settings()
    if not settings.database_enabled:
        _pool = None
        log.warning(
            "Database disabled; starting in code-only mode (no business data "
            "will be read or written)"
        )
        return False
    if not settings.database_url.strip():
        raise ValueError("DATABASE_URL is required when DATABASE_MODE=postgres")
    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    log.info("Database pool ready")
    return True


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
    _pool = None


def get_pool() -> asyncpg.Pool:
    _require_database()
    if _pool is None:
        raise RuntimeError("DB pool not initialized")
    return _pool


@asynccontextmanager
async def db_conn():
    _require_database()
    if _pool is not None:
        async with _pool.acquire() as conn:
            yield conn
        return

    settings = get_settings()
    conn = await asyncpg.connect(settings.database_url)
    try:
        yield conn
    finally:
        await conn.close()


async def fetch_one(sql: str, *args, conn: Optional[asyncpg.Connection] = None) -> Optional[dict]:
    _check_shadow_write_guard(sql)
    if conn is not None:
        row = await conn.fetchrow(sql, *args)
        _observe_inbound_write(sql, dict(row) if row else None)
        return dict(row) if row else None
    async with db_conn() as conn:
        row = await conn.fetchrow(sql, *args)
        _observe_inbound_write(sql, dict(row) if row else None)
        return dict(row) if row else None


async def fetch_all(sql: str, *args, conn: Optional[asyncpg.Connection] = None) -> list[dict]:
    _check_shadow_write_guard(sql)
    if conn is not None:
        rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]
    async with db_conn() as conn:
        rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]


async def execute(sql: str, *args, conn: Optional[asyncpg.Connection] = None) -> str:
    _check_shadow_write_guard(sql)
    if conn is not None:
        result = await conn.execute(sql, *args)
        _observe_inbound_write(sql, result)
        return result
    async with db_conn() as conn:
        result = await conn.execute(sql, *args)
        _observe_inbound_write(sql, result)
        return result


async def fetch_val(sql: str, *args, conn: Optional[asyncpg.Connection] = None) -> Any:
    _check_shadow_write_guard(sql)
    if conn is not None:
        result = await conn.fetchval(sql, *args)
        _observe_inbound_write(sql, result)
        return result
    async with db_conn() as conn:
        result = await conn.fetchval(sql, *args)
        _observe_inbound_write(sql, result)
        return result


def _observe_inbound_write(sql: str, result) -> None:
    """Attach existing domain write results to the active inbound audit.

    No SQL or argument values are stored. IDs are only recorded when the
    statement actually returns them; affected-row counts are not IDs.
    This observer does not execute queries or affect transaction semantics.
    """
    import sys
    router = sys.modules.get("modules.message_router")
    if router is None or not getattr(router, "inbound_reference", lambda: {})():
        return
    match = _WRITE_STMT_RE.match(sql)
    if not match:
        return
    table = match.group(1).lower()
    if table in {"fazle_whatsapp_messages", "fazle_outbound_queue", "fazle_draft_replies"}:
        return  # these have explicit, durable relationships
    fields = {}
    if isinstance(result, dict):
        fields["returned_identifiers"] = {
            k: str(v) for k, v in result.items()
            if (k == "id" or k.endswith("_id")) and v is not None
        }
    elif re.search(r"\bRETURNING\s+[\w\"]+", sql, re.I) and result is not None:
        fields["returned_identifier"] = str(result)
    else:
        fields["result"] = str(result)
    router.record_inbound_action("business_write", table=table, evidence="statement_result",
                                operation=sql.lstrip().split()[0].upper(), **fields)
