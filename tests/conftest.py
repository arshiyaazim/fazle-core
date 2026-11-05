"""
Fazle Core — Master Test Fixtures

Provides:
  - test_db:          asyncpg pool connected to isolated test schema
  - client:           httpx AsyncClient wrapping the FastAPI app
  - override_settings: inject test env without touching real .env
  - mock_bridge1/2:   respx mocks for bridge HTTP calls
  - mock_ollama:      respx mock for Ollama AI
  - seed_employee:    creates a real employee row in test DB
  - seed_escort_program: creates a real escort program row
  - sample payloads for every WhatsApp message type
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

# ── Early env var setup — must run BEFORE any app.config import ──────────────
# Module-level imports in test files (e.g. from modules.fazle_payroll_engine.routes)
# trigger get_settings() during collection, before the override_env fixture runs.
# Set safe defaults here so collection never fails with ValidationError.
_early_test_db_pass = os.getenv("TEST_DB_PASSWORD", "changeme-set-TEST_DB_PASSWORD")
os.environ.setdefault("DATABASE_URL", os.getenv("TEST_DATABASE_URL", f"postgresql://postgres:{_early_test_db_pass}@127.0.0.1:5433/fazle_test"))
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-key-fixture-only")
os.environ.setdefault("AUTO_REPLY_ENABLED", "false")
os.environ.setdefault("RECRUITMENT_AUTOREPLY_ENABLED", "false")
os.environ.setdefault("OLLAMA_URL", "http://mock-ollama")
os.environ.setdefault("BRIDGE1_URL", "http://mock-bridge1")
os.environ.setdefault("BRIDGE2_URL", "http://mock-bridge2")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("ADMIN_NUMBERS", "8801700000001,8801700000002")
os.environ.setdefault("META_VERIFY_TOKEN", "test_verify_token")
os.environ.setdefault("META_APP_SECRET", "test_app_secret")
os.environ.setdefault("ACCOUNTANT_PHONE", "")
os.environ.setdefault("ESCORT_CLIENT_PHONES", "")
os.environ.setdefault("SOCIAL_AUTO_REPLY_SINGLE_ENGINE", "false")

# app.main calls app.logging_setup.setup_logging() at MODULE level on import
# (line ~68) — it attaches a RotatingFileHandler to the ROOT logger pointed
# at logs/fazle-core.log by default. Since most test files import app.main
# (directly or transitively) during collection, that handler stays attached
# for the entire pytest process and EVERY log.info() call anywhere in the
# app — including these tests' own fixture data ("db down", "write failed",
# recipient=8801711111111, etc.) — was landing in the SAME file the live
# fazle-core.service writes to (confirmed live, 2026-08-27: a pytest run
# produced [META_EVENT] lines in logs/fazle-core.log seconds after running).
# setup_logging() already reads FAZLE_LOG_DIR as its override point for
# exactly this kind of redirection — point it at a throwaway temp directory
# before any import can trigger setup_logging(), so tests physically cannot
# write into the production log file. Owner directive (2026-08-27, Meta
# Messenger/Instagram integration, Section 1): "Ensure tests do not write
# fixture noise into the production log file."
if "FAZLE_LOG_DIR" not in os.environ:
    import tempfile
    os.environ["FAZLE_LOG_DIR"] = tempfile.mkdtemp(prefix="fazle-test-logs-")

import asyncpg
import pytest
import pytest_asyncio
import respx
from httpx import AsyncClient, ASGITransport

# ── One-time test schema setup (sync, no event loop conflicts) ───────────────
# autouse=False: only runs for tests that explicitly request this fixture
# (or DB-dependent fixtures that chain to it). Pure unit tests are unaffected.
# ── Schema setup via pytest_configure hook ───────────────────────────────────
# Runs before any event loop or fixture is created, so asyncio.run() is safe.

_schema_setup_done = False


def pytest_configure(config):
    """Run schema setup before any tests or event loops start."""
    import sys

    global _schema_setup_done

    # ── HARD SAFETY GUARD: verify DB name before any DROP SCHEMA ──────────
    db_name = _extract_db_name(TEST_DB_URL)
    if db_name.lower() not in _SAFE_TEST_DB_NAMES:
        print(f"\n{'='*60}")
        print(f"FATAL: Refusing to DROP SCHEMA on database '{db_name}'.")
        print(f"  Only these databases are safe: {', '.join(sorted(_SAFE_TEST_DB_NAMES))}")
        print(f"  URL: {TEST_DB_URL}")
        print(f"{'='*60}\n")
        sys.exit(1)

    async def _run():
        pool = await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=2)
        async with pool.acquire() as conn:
            await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            await conn.execute(_BASE_SCHEMA_SQL)
            applied = await _run_all_migrations(conn)
            await conn.execute(_RUNTIME_SCHEMA_SQL)
            await conn.execute(_SEED_SQL)
            print(f"\n[test-schema] {len(applied)} migration files applied")
        await pool.close()

    try:
        asyncio.run(_run())
        _schema_setup_done = True
    except Exception as e:
        print(f"\n[test-schema] FATAL: schema setup failed: {e}")
        # Don't exit — let tests that don't need DB still run


def pytest_collection_modifyitems(config, items):
    """Fail fast (before any test runs, not just eventually) if tests/e2e/
    (Playwright) tests are collected together with anything else in the
    same pytest invocation.

    Found 2026-07-09: e2e tests corrupt the shared asyncio event loop for
    every async DB test that runs after them in the same process, cascading
    into ~350 false failures in unrelated tests/unit and tests/workflows
    tests. e2e must always run as its own separate `pytest tests/e2e/`
    invocation.

    This is a collection-time guard rather than relying on tests/pytest.ini
    or CI config alone, because neither is bulletproof on its own: a bare
    `pytest` invoked from the repo root doesn't find tests/pytest.ini at
    all (ini-file discovery only searches upward from the given args/cwd,
    never downward into tests/), and `pytest tests/` (whole directory,
    explicit args) finds it but testpaths is only consulted when NO args
    are given, so it doesn't help either. This hook lives in conftest.py,
    which pytest always loads for anything under tests/ regardless of
    which ini file (if any) was found — the one guard that can't be
    bypassed by invocation style.
    """
    def _is_e2e(item) -> bool:
        return "/e2e/" in item.nodeid or item.nodeid.startswith("e2e/")

    has_e2e = any(_is_e2e(item) for item in items)
    has_non_e2e = any(not _is_e2e(item) for item in items)
    if has_e2e and has_non_e2e:
        raise pytest.UsageError(
            "\n\nRefusing to run: tests/e2e/ (Playwright) tests were collected "
            "together with other tests in the same pytest invocation.\n"
            "e2e tests corrupt the shared asyncio event loop for every async "
            "test that runs after them in the same process, causing hundreds "
            "of unrelated false failures. See docs/DEVELOPER_GUIDE.md.\n\n"
            "Run them separately:\n"
            "  pytest tests/unit tests/integration tests/db tests/workflows tests/resilience\n"
            "  pytest tests/e2e\n"
        )


@pytest.fixture(scope="session", autouse=False)
def _setup_test_schema(override_env):
    """Marker fixture — schema is already set up by pytest_configure.
    Chaining this fixture ensures override_env has run."""
    assert _schema_setup_done, "Schema setup failed in pytest_configure"
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 1c. Base schema — pre-migration tables that NO migration creates
# ─────────────────────────────────────────────────────────────────────────────

_BASE_SCHEMA_SQL = (Path(__file__).resolve().parent.parent / "db/schema/000_foundation.sql").read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# 1d. Migration runner — discovers and applies all production migration SQL files
# ─────────────────────────────────────────────────────────────────────────────

def _discover_migration_files() -> list[tuple[str, str]]:
    """Return sorted list of (label, filepath) for all migration SQL files."""
    from pathlib import Path
    base = Path(__file__).resolve().parent.parent  # core/
    dirs = [
        base / "db" / "migrations",
        base / "modules" / "fazle_payroll_engine" / "migrations",
    ]
    files: list[tuple[str, str]] = []
    for d in dirs:
        if d.is_dir():
            for f in sorted(d.glob("*.sql")):
                files.append((f.name, str(f)))
    files.sort(key=lambda x: x[0])  # deterministic sorted order by filename
    return files


async def _run_all_migrations(conn: asyncpg.Connection) -> list[str]:
    """Execute all migration SQL files in sorted order.

    Files containing BEGIN/COMMIT are executed directly (PostgreSQL handles
    the inner transaction). Files without BEGIN/COMMIT are wrapped in a
    transaction that rolls back on failure so one bad file doesn't poison
    the connection for subsequent ones.
    """
    import logging
    import re
    log = logging.getLogger("fazle.test_schema")
    applied: list[str] = []
    files = _discover_migration_files()

    for label, filepath in files:
        with open(filepath, "r") as f:
            sql_text = f.read()
        # Strip BEGIN/COMMIT so statements run independently
        sql_text = re.sub(r"^\s*BEGIN\s*;", "", sql_text, flags=re.IGNORECASE | re.MULTILINE)
        sql_text = re.sub(r"^\s*COMMIT\s*;", "", sql_text, flags=re.IGNORECASE | re.MULTILINE)
        # Split into individual statements with proper handling of:
        # - dollar-quoted strings ($$ ... $$ or $tag$ ... $tag$)
        # - single-quoted strings ('...;...')
        # - parenthesis depth (semicolons inside CREATE TABLE)
        # - line comments (-- ...)
        statements = _split_sql_safe(sql_text)
        errors = 0
        for stmt in statements:
            s = stmt.strip()
            if not s:
                continue
            # Skip purely comment-only statements (every line starts with --)
            lines = [l.strip() for l in s.split("\n") if l.strip()]
            if all(l.startswith("--") for l in lines):
                continue
            try:
                async with conn.transaction():
                    await conn.execute(stmt)
            except Exception as e:
                err_msg = str(e)[:150]
                if any(kw in err_msg.lower() for kw in (
                    "already exists", "does not exist", "duplicate",
                    "multiple primary key", "transaction is aborted",
                )):
                    pass  # idempotent — already applied
                else:
                    errors += 1
                    log.warning("[migration:%s] stmt failed: %s", label, err_msg)
        applied.append(label)
        if errors:
            log.warning("[migration:%s] %d errors (tolerated)", label, errors)
    return applied


# ─────────────────────────────────────────────────────────────────────────────
# 1e. Runtime schema — tables created by app code at startup, not in migrations
# ─────────────────────────────────────────────────────────────────────────────

_RUNTIME_SCHEMA_SQL = (Path(__file__).resolve().parent.parent / "db/schema/900_runtime_support.sql").read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# 1f. Minimal seed data
# ─────────────────────────────────────────────────────────────────────────────

_SEED_SQL = """
INSERT INTO fazle_roles (name, level, description) VALUES
  ('viewer',     1, 'Read-only'),
  ('operator',   2, 'Approve drafts, process payments'),
  ('accountant', 3, 'Payroll and payment operations'),
  ('admin',      4, 'System management'),
  ('superadmin', 5, 'Full access')
ON CONFLICT (name) DO NOTHING;
"""


# ─────────────────────────────────────────────────────────────────────────────
# 1. Environment / Settings override
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# 1b. Hard safety guard — prevent accidental production DB destruction
# ─────────────────────────────────────────────────────────────────────────────

_FORBIDDEN_DB_NAMES = frozenset({
    "postgres", "fazle_core", "fazle", "core", "live", "production", "prod",
    "fazle_live", "fazle_prod", "whatsapp", "fazle_whatsapp",
})

_SAFE_TEST_DB_NAMES = frozenset({
    "fazle_test", "test", "fazle_test_db",
})


def _extract_db_name(url: str) -> str:
    """Extract the database name from a PostgreSQL URL."""
    if not url:
        return ""
    # Handle postgresql://user:pass@host:port/dbname?params
    import re
    m = re.search(r"/([^/?]+)(?:\?|$)", url)
    if m:
        return m.group(1)
    return ""


def _validate_test_db_url(url: str) -> str:
    """Validate that the DB URL points only to a safe test database.
    Fatal exit if it points to production."""
    import sys

    db_name = _extract_db_name(url)
    if not db_name:
        print(f"\n{'='*60}")
        print("FATAL: Could not extract database name from TEST_DB_URL.")
        print(f"  URL: {url}")
        print("Tests aborted to prevent potential data loss.")
        print(f"{'='*60}\n")
        sys.exit(1)

    if db_name.lower() in _FORBIDDEN_DB_NAMES:
        print(f"\n{'='*60}")
        print(f"FATAL: TEST_DB_URL points to '{db_name}' — a production database!")
        print(f"  URL: {url}")
        print("DROP SCHEMA would destroy production data.")
        print("Set TEST_DATABASE_URL to a fazle_test database.")
        print(f"{'='*60}\n")
        sys.exit(1)

    if db_name.lower() not in _SAFE_TEST_DB_NAMES:
        print(f"\n{'='*60}")
        print(f"WARNING: TEST_DB_URL database '{db_name}' is not in the known safe list.")
        print(f"  Allowed: {', '.join(sorted(_SAFE_TEST_DB_NAMES))}")
        print(f"  URL: {url}")
        print(f"{'='*60}\n")

    return url


# TEST_DB_URL: must be set explicitly via TEST_DATABASE_URL env var.
# If not set, construct from safe components: Docker host + fazle_test DB.
# The password may be provided via TEST_DB_PASSWORD env var (CI-friendly).
# NEVER read the full production DATABASE_URL from .env files.
_TEST_DB_HOST = os.getenv("TEST_DB_HOST", "127.0.0.1")
_TEST_DB_PORT = os.getenv("TEST_DB_PORT", "5433")
_TEST_DB_USER = os.getenv("TEST_DB_USER", "postgres")
_TEST_DB_PASS = os.getenv("TEST_DB_PASSWORD", "changeme-set-TEST_DB_PASSWORD")
_TEST_DB_NAME = "fazle_test"  # hardcoded — never overridable
TEST_DB_URL = os.getenv("TEST_DATABASE_URL") or f"postgresql://{_TEST_DB_USER}:{_TEST_DB_PASS}@{_TEST_DB_HOST}:{_TEST_DB_PORT}/{_TEST_DB_NAME}"
_validate_test_db_url(TEST_DB_URL)
TEST_API_KEY = "test-internal-key-fixture-only"


@pytest.fixture(scope="session", autouse=True)
def override_env(tmp_path_factory):
    """Patch environment before anything imports app.config."""
    env_overrides = {
        "DATABASE_URL": TEST_DB_URL,
        "INTERNAL_API_KEY": TEST_API_KEY,
        "AUTO_REPLY_ENABLED": "false",
        "RECRUITMENT_AUTOREPLY_ENABLED": "false",
        "BRIDGE1_URL": "http://mock-bridge1",
        "BRIDGE2_URL": "http://mock-bridge2",
        "OLLAMA_URL": "http://mock-ollama",
        "REDIS_URL": "redis://localhost:6379/15",   # isolated DB 15 for tests
        "ADMIN_NUMBERS": "8801700000001,8801700000002",
        "META_VERIFY_TOKEN": "test_verify_token",
        "META_APP_SECRET": "test_app_secret",
        "ACCOUNTANT_PHONE": "",
        "ESCORT_CLIENT_PHONES": "",
        "SOCIAL_AUTO_REPLY_SINGLE_ENGINE": "false",
    }
    with patch.dict(os.environ, env_overrides):
        yield


# ─────────────────────────────────────────────────────────────────────────────
# 2. Database fixtures
# ─────────────────────────────────────────────────────────────────────────────

# (Schema is now built from production migrations — see _setup_test_schema above.)

# ── Dynamic TRUNCATE list ─────────────────────────────────────────────────────
# Instead of a hardcoded table list, we discover all tables at teardown time
# so we never miss a table created by a new migration.

async def _truncate_all_tables(conn: asyncpg.Connection) -> None:
    """Truncate all tables in the public schema, RESTART IDENTITY CASCADE.
    Skips fazle_roles (seed data must survive between tests)."""
    rows = await conn.fetch("""
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename != 'fazle_roles'
        ORDER BY tablename
    """)
    if not rows:
        return
    table_names = [r["tablename"] for r in rows]
    # Build a single TRUNCATE statement for all tables
    safe_names = ", ".join(f'"{t}"' for t in table_names)
    try:
        await conn.execute(f"TRUNCATE TABLE {safe_names} RESTART IDENTITY CASCADE")
    except Exception:
        pass  # non-fatal — some tables may have FK cycles
    # TRUNCATE ... CASCADE can clear referenced seed tables indirectly, even
    # when fazle_roles itself is excluded from the generated table list.
    # Restore the small immutable RBAC role catalog before the next test.
    await conn.execute(_SEED_SQL)


@pytest_asyncio.fixture
async def test_db_pool(_setup_test_schema) -> AsyncGenerator[asyncpg.Pool, None]:
    """Per-test asyncpg pool. Chains _setup_test_schema so the schema is
    created/wiped once per session before any DB test runs. Truncates all
    data tables in teardown so each test starts with clean state. Pure
    (no-DB) unit tests never request test_db_pool so they are unaffected."""
    pool = await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=3)
    yield pool
    try:
        async with pool.acquire() as conn:
            await _truncate_all_tables(conn)
    finally:
        await pool.close()
        # Many tests point the shared app.database._pool singleton at this
        # fixture's pool directly (`db_module._pool = test_db_pool`), bypassing
        # dependency injection. If we don't clear that reference here, the next
        # test in the session that relies on app.database's global pool (e.g.
        # any ASGI call through app.main.app that never re-assigns it) inherits
        # a closed-pool reference and fails with "pool is closed" — regardless
        # of whether *this* test passed, failed, or errored. Only clear it if
        # it's still pointing at the pool we just closed, so we never stomp on
        # a different pool some other fixture may have set up in the meantime.
        import app.database as db_module
        if db_module._pool is pool:
            db_module._pool = None


@pytest_asyncio.fixture
async def clean_tables(test_db_pool):
    """Truncate data tables before each test. Keeps schema and seed data."""
    yield
    async with test_db_pool.acquire() as conn:
        await _truncate_all_tables(conn)


# ─────────────────────────────────────────────────────────────────────────────
# 3. FastAPI test client
# ─────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(test_db_pool) -> AsyncGenerator[AsyncClient, None]:
    """
    httpx AsyncClient backed by the real FastAPI app.
    DB pool is injected by patching app.database._pool.
    """
    import app.database as db_module
    db_module._pool = test_db_pool

    # Reset ollama_daemon's persistent client so RESPX mocks can intercept.
    try:
        from app import ollama_daemon as _od
        await _od.stop()
    except Exception:
        pass

    from app.main import app as fastapi_app

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app),
        base_url="http://testserver",
        headers={"X-Internal-Key": TEST_API_KEY},
    ) as ac:
        yield ac

    # Clean up ollama_daemon client after test.
    try:
        from app import ollama_daemon as _od
        await _od.stop()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _disable_shadow_logger_real_writes(request):
    """Restart-gate/test-infrastructure investigation (2026-08-27, Owner
    directive): modules.hermes_kernel.shadow_logger.log_decision()/
    log_event() are fired via bare asyncio.create_task() from modules.
    message_router's _hk_fire() closure -- true fire-and-forget,
    uncaptured, unawaited by the caller -- at dozens of call sites inside
    process_message(). With HERMES_DECISION_AUDIT_ENABLED=true /
    HERMES_EVENT_LOG_ENABLED=true in .env (the real, unchanged production
    setting), ANY test that exercises process_message() -- even one that
    mocks everything else and has nothing to do with shadow logging --
    silently schedules a REAL, unawaited DB write against the test
    database as an uncontrolled side effect. If the test function returns
    (and pytest-asyncio's function-scoped event loop starts tearing down)
    before that task gets a scheduling turn to finish, it is abandoned
    mid-flight. Under momentary CPU/event-loop contention on this shared
    VPS (real production traffic — fazle-core.service, hermes-runner,
    ollama — runs on the same machine and was confirmed actively
    processing real customer messages during reproduction), the abandoned
    task's turn can be delayed past pytest's fixed 30s test timeout,
    which pytest then attributes to whichever test happened to be running
    at that moment. This reproduces the observed pattern exactly:
    intermittent, only in longer/bundled gate runs (never in a fast
    isolated rerun of the same suite), a DIFFERENT specific test each
    time, always the same "Task-was-destroyed... _sock_write_done"
    signature. Confirmed via live pg_stat_activity monitoring (before,
    during, and after both an isolated run and a full check4+check4b
    run) that this is NOT a Postgres connection leak, pool exhaustion, or
    lock/transaction contention — connection count never exceeded 2 the
    entire time.

    Fix: make these fire-and-forget calls true no-ops for every test
    EXCEPT tests/unit/test_hermes_kernel_shadow_logger.py itself (which
    explicitly exercises their real enable/resolve/write behavior with
    its own mocks/invalidate_flag_cache() calls) -- closing off this
    entire class of flakiness at its actual source. Zero change to
    modules/hermes_kernel/shadow_logger.py, modules/message_router/
    __init__.py, or any real .env flag -- this is a pure test-isolation
    fix, same category as _reset_admin_command_dedup_cache below."""
    if request.module.__name__.endswith("test_hermes_kernel_shadow_logger"):
        yield
        return
    with patch("modules.hermes_kernel.shadow_logger.log_decision", new=AsyncMock()), \
         patch("modules.hermes_kernel.shadow_logger.log_event", new=AsyncMock()):
        yield


@pytest.fixture(autouse=True)
def _default_bridge3_pairing_state_released(request):
    """BRIDGE3_FIRST_REPAIR_INCIDENT_2026-09-02: modules.fazle_bridge_poller now
    FAIL-CLOSES bridge3 whenever `bridge3.pairing_state` is not exactly
    `OUTBOUND_OWNER_APPROVED` — an unset key holds all bridge3 routing and
    refuses every bridge3 outbound enqueue/dispatch. The isolated test DB's
    `fazle_runtime_settings` starts empty, so without this fixture every
    pre-existing test that enqueues or routes via bridge3 (idempotency,
    lifecycle, recruitment, admin-isolation ...) would suddenly see a held
    bridge. Default the lookup to `OUTBOUND_OWNER_APPROVED` for
    `*.pairing_state` keys so those tests keep exercising normal behaviour;
    everything else passes through to the real get_runtime_setting.

    Opt-out: the two suites that assert the real fail-closed / state-machine
    logic patch get_runtime_setting themselves and must not be wrapped."""
    mod = request.module.__name__
    if mod.endswith(("test_bridge_poller_history_sync_quarantine",
                     "test_outbound_pairing_hold")):
        yield
        return
    import modules.wa_chat_frontend as _wf
    _real = _wf.get_runtime_setting

    async def _patched(key, default="false"):
        if isinstance(key, str) and key.endswith(".pairing_state"):
            return "OUTBOUND_OWNER_APPROVED"
        return await _real(key, default)

    with patch.object(_wf, "get_runtime_setting", new=_patched):
        yield


@pytest.fixture(autouse=True)
def _reset_admin_command_dedup_cache():
    """Clear modules.fazle_admin_commands' in-process dedup LRU before each test.

    That cache is a module-level OrderedDict keyed by sha1(admin_phone+text)
    with a 30s TTL — correct for production (single-worker duplicate-send
    suppression) but not test-isolated: two tests in the same pytest process
    that send the same admin command text within 30s of each other collide
    and the second is silently treated as a duplicate.
    """
    from modules.fazle_admin_commands import _dedup_cache
    _dedup_cache.clear()
    yield
    _dedup_cache.clear()


@pytest.fixture
def auth_headers() -> dict:
    return {"X-Internal-Key": TEST_API_KEY}


@pytest.fixture
def no_auth_headers() -> dict:
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# 4. Mock external services (respx)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_bridge1():
    """Mock Bridge1 HTTP calls."""
    with respx.mock(base_url="http://mock-bridge1", assert_all_called=False) as mock:
        mock.post("/send").mock(return_value=_bridge_send_ok())
        mock.get("/health").mock(return_value=_bridge_health_ok("bridge1"))
        mock.get("/messages").mock(return_value=_bridge_messages_empty())
        yield mock


@pytest.fixture
def mock_bridge2():
    """Mock Bridge2 HTTP calls."""
    with respx.mock(base_url="http://mock-bridge2", assert_all_called=False) as mock:
        mock.post("/send").mock(return_value=_bridge_send_ok())
        mock.get("/health").mock(return_value=_bridge_health_ok("bridge2"))
        mock.get("/messages").mock(return_value=_bridge_messages_empty())
        yield mock


@pytest.fixture
def mock_ollama():
    """Mock Ollama LLM call by patching ollama_daemon.post_generate directly.

    RESPX transport interception doesn't work reliably with ollama_daemon's
    persistent httpx.AsyncClient, so we patch at the function level instead.
    Classify calls return a valid category; generate calls return a Bengali reply.
    """
    from app import ollama_daemon
    original = ollama_daemon.post_generate

    async def _mock_post_generate(payload, timeout=120.0):
        import httpx
        prompt = (payload or {}).get("prompt", "")
        # Classify calls expect a category name; generate calls expect a reply.
        if "Categories:" in prompt and "Category:" in prompt:
            return httpx.Response(200, json={"response": "greeting", "done": True})
        return _ollama_response("ধন্যবাদ।")

    ollama_daemon.post_generate = _mock_post_generate
    try:
        yield _mock_post_generate
    finally:
        ollama_daemon.post_generate = original


@pytest.fixture
def mock_all_services(mock_bridge1, mock_bridge2, mock_ollama):
    """Convenience: all external mocks active."""
    yield {"bridge1": mock_bridge1, "bridge2": mock_bridge2, "ollama": mock_ollama}


# ── Helper response builders ───────────────────────────────────────────────────

def _bridge_send_ok():
    from httpx import Response
    return Response(200, json={"status": "ok", "message_id": "test-msg-001"})


def _bridge_health_ok(name: str):
    from httpx import Response
    return Response(200, json={"status": "ok", "bridge": name, "connected": True})


def _bridge_messages_empty():
    from httpx import Response
    return Response(200, json={"messages": []})


def _bridge_send_fail():
    from httpx import Response
    return Response(503, json={"error": "bridge unavailable"})


def _ollama_response(text: str):
    from httpx import Response
    return Response(200, json={"response": text, "done": True})


# ─────────────────────────────────────────────────────────────────────────────
# 5. DB seed fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def seed_employee(test_db_pool) -> dict:
    """Insert one employee row and return it."""
    async with test_db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO fazle_employees_legacy
                (employee_mobile, employee_name, designation, status,
                 basic_salary, bkash_number, nagad_number)
            VALUES
                ('8801811111111', 'Test Guard Karim', 'Security Guard', 'Active',
                 9000.00, '01811111111', '01811111111')
            RETURNING *
        """)
    return dict(row)


@pytest_asyncio.fixture
async def seed_employee2(test_db_pool) -> dict:
    """A second employee for multi-employee tests."""
    async with test_db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO fazle_employees_legacy
                (employee_mobile, employee_name, designation, status,
                 basic_salary, bkash_number)
            VALUES
                ('8801822222222', 'Test Guard Rahim', 'Escort', 'Active',
                 10000.00, '01822222222')
            RETURNING *
        """)
    return dict(row)


@pytest_asyncio.fixture
async def seed_escort_program(test_db_pool, seed_employee) -> dict:
    """Insert one escort program row and return it."""
    async with test_db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO wbom_escort_programs
                (mother_vessel, lighter_vessel, master_mobile,
                 escort_employee_id, escort_mobile,
                 program_date, shift, status, start_date)
            VALUES
                ('MV TEST VESSEL', 'LT TEST LIGHTER', '8801933333333',
                 $1, $2,
                 '2026-05-01', 'D', 'running', '2026-05-01')
            RETURNING *
        """, seed_employee["employee_id"], seed_employee["employee_mobile"])
    return dict(row)


@pytest_asyncio.fixture
async def seed_admin(test_db_pool) -> dict:
    """Insert a superadmin in fazle_admins."""
    async with test_db_pool.acquire() as conn:
        admin_row = await conn.fetchrow("""
            INSERT INTO fazle_admins (phone, name, username, status)
            VALUES ('8801700000001', 'Test Admin', 'testadmin', 'active')
            RETURNING *
        """)
        role = await conn.fetchrow(
            "SELECT id FROM fazle_roles WHERE name='superadmin'"
        )
        await conn.execute("""
            INSERT INTO fazle_admin_roles (admin_id, role_name, granted_by)
            VALUES ($1, 'superadmin', 'system') ON CONFLICT DO NOTHING
        """, admin_row["id"])
    return dict(admin_row)


@pytest_asyncio.fixture
async def seed_accountant(test_db_pool) -> dict:
    """Seed an accountant contact role entry."""
    async with test_db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO fazle_contact_roles (phone, role, name, source)
            VALUES ('8801944444444', 'accountant', 'Test Accountant', 'seed')
            RETURNING *
        """)
    return dict(row)


@pytest_asyncio.fixture
async def seed_payment_draft(test_db_pool, seed_employee, seed_escort_program) -> dict:
    """A pending payment draft for use in payment workflow tests."""
    async with test_db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO fazle_payment_drafts
                (draft_type, employee_id, employee_name, employee_mobile,
                 escort_program_id, duty_days, expected_amount,
                 payment_method, payout_mobile, status, source,
                 draft_text)
            VALUES
                ('escort_payment', $1, $2, $3,
                 $4, 5.0, 1500.00,
                 'bkash', '01811111111', 'pending', 'bridge1',
                 '💼 Test payment draft')
            RETURNING *
        """, seed_employee["employee_id"], seed_employee["employee_name"],
            seed_employee["employee_mobile"],
            seed_escort_program["program_id"])
    return dict(row)


@pytest_asyncio.fixture
async def seed_fpe_employee(test_db_pool, seed_employee) -> dict:
    """Insert an fazle_employees row matching the seeded fazle_employees_legacy row."""
    async with test_db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO fazle_employees
                (employee_code, full_name, name_normalized, primary_phone,
                 employee_id_phone, status, canonical_employee_id)
            VALUES
                ($1, $2, $3, $4, $5, 'active', $6)
            RETURNING *
        """, f"EMP{seed_employee['employee_id']}",
           seed_employee['employee_name'],
           seed_employee['employee_name'].lower().strip(),
           '01811111111',
           '01811111111',
           seed_employee['employee_id'])
    return dict(row)


@pytest_asyncio.fixture
async def seed_fpe_karim_supervisor(test_db_pool) -> dict:
    """A standalone fazle_employees row (no fazle_employees_legacy link needed) with
    a designation, for modules.fazle_identity_brain.claim_verification tests.
    Named distinctly from the pre-existing seed_fpe_employee fixture above
    (which is wbom-linked and has no designation) to avoid collision."""
    async with test_db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO fazle_employees
                (full_name, name_normalized, primary_phone, designation, status)
            VALUES
                ('Karim Uddin', 'karim uddin', '01811111199', 'Ghat Supervisor', 'active')
            RETURNING *
        """)
    return dict(row)


@pytest_asyncio.fixture
async def seed_fpe_karim_duplicate(test_db_pool) -> dict:
    """A second, distinct employee sharing the same normalized name as
    seed_fpe_karim_supervisor -- for the ambiguous-claim regression test."""
    async with test_db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO fazle_employees
                (full_name, name_normalized, primary_phone, designation, status)
            VALUES
                ('Karim Uddin', 'karim uddin', '01822222299', 'Security Guard', 'active')
            RETURNING *
        """)
    return dict(row)


@pytest_asyncio.fixture
async def seed_sprint3b_draft(test_db_pool, seed_employee) -> dict:
    """A pending Sprint-3B payment draft (from Sprint-3A employee conversation)."""
    async with test_db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO fazle_payment_drafts
                (draft_type, employee_id, employee_name, employee_mobile,
                 payout_mobile, purpose, expected_amount, payment_method,
                 status, source, draft_text, source_message,
                 draft_created_by, conversation_id, expires_at)
            VALUES
                ('advance', $1, $2, $3,
                 $3, 'advance', 2000.00, 'bkash',
                 'pending', 'bridge1', 'Test advance draft',
                 'ভাই অগ্রিম টাকা দরকার ২০০০ টাকা',
                 'ai_conversation', 'conv-test-001',
                 NOW() + INTERVAL '24 hours')
            RETURNING *
        """, seed_employee['employee_id'], seed_employee['employee_name'],
           seed_employee['employee_mobile'])
    return dict(row)


# ─────────────────────────────────────────────────────────────────────────────
# 6. WhatsApp payload builders
# ─────────────────────────────────────────────────────────────────────────────

def make_bridge_payload(sender: str, text: str, source: str = "bridge1") -> dict:
    """Minimal bridge webhook payload."""
    return {
        "sender": sender,
        "message": text,
        "timestamp": "2026-05-06T10:00:00Z",
        "message_id": f"test-{hash(text) % 100000}",
        "source": source,
    }


def make_meta_payload(sender: str, text: str) -> dict:
    """Meta WhatsApp Cloud API webhook payload."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "TEST_ENTRY_ID",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": "TEST_PHONE_ID"},
                    "contacts": [{"wa_id": sender, "profile": {"name": "Test User"}}],
                    "messages": [{
                        "id": "wamid.test001",
                        "from": sender,
                        "timestamp": "1746518400",
                        "type": "text",
                        "text": {"body": text},
                    }],
                },
                "field": "messages",
            }],
        }],
    }


# ── Pre-built payload constants ────────────────────────────────────────────────

GUARD_PHONE = "8801811111111"
ADMIN_PHONE = "8801700000001"
ACCOUNTANT_PHONE = "8801944444444"
CLIENT_PHONE = "8801955555555"
CANDIDATE_PHONE = "8801966666666"
UNKNOWN_PHONE = "8801977777777"

PAYLOAD_ESCORT_ORDER = make_bridge_payload(
    CLIENT_PHONE,
    "MV GOLDEN STAR lighter vessel NAJMA-3 master mobile 01933333333 "
    "wheat 5000MT escort lagbe 06/05/2026 Day shift",
)

PAYLOAD_GUARD_RELEASE = make_bridge_payload(
    GUARD_PHONE,
    "ডিউটি শেষ রিলিজ হয়েছি",
)

PAYLOAD_GUARD_ATTENDANCE = make_bridge_payload(
    GUARD_PHONE,
    "হাজির আছি MV GOLDEN STAR এ",
)

PAYLOAD_ADVANCE_REQUEST = make_bridge_payload(
    GUARD_PHONE,
    "ভাই অগ্রিম টাকা দরকার ২০০০ টাকা",
)

PAYLOAD_CANDIDATE_INQUIRY = make_bridge_payload(
    CANDIDATE_PHONE,
    "চাকরি করতে চাই নিরাপত্তা প্রহরী পদে",
)

PAYLOAD_ADMIN_APPROVE = make_bridge_payload(
    ADMIN_PHONE,
    "APPROVE 1",
    source="bridge2",
)

PAYLOAD_ADMIN_REJECT = make_bridge_payload(
    ADMIN_PHONE,
    "REJECT 1",
    source="bridge2",
)

def _split_sql_safe(sql_text: str) -> list[str]:
    """Split SQL into individual statements, properly handling:
    - Dollar-quoted strings ($$ ... $$ or $tag$ ... $tag$)
    - Single-quoted strings ('...;...')
    - Parenthesis depth (semicolons inside CREATE TABLE)
    - Line comments (-- ...)
    """
    statements: list[str] = []
    current: list[str] = []
    paren_depth = 0
    i = 0
    n = len(sql_text)
    in_single_quote = False
    in_dollar_quote = False
    dollar_tag = ""
    
    while i < n:
        ch = sql_text[i]

        # Check for line comment (-- ...) — consume verbatim through end of
        # line so semicolons inside human-readable comment text (extremely
        # common in pg_dump output, e.g. "-- Name: x; Type: TABLE; ...") never
        # get treated as statement boundaries.
        if not in_single_quote and not in_dollar_quote and ch == "-" and i + 1 < n and sql_text[i + 1] == "-":
            eol = sql_text.find("\n", i)
            eol = n if eol == -1 else eol + 1
            current.append(sql_text[i:eol])
            i = eol
            continue

        # Check for dollar-quoted string start/end
        if not in_single_quote and ch == "$":
            # Try to match a dollar quote tag
            j = i + 1
            while j < n and (sql_text[j].isalnum() or sql_text[j] == "_"):
                j += 1
            if j < n and sql_text[j] == "$":
                tag = sql_text[i:j+1]  # $tag$ or $$
                if in_dollar_quote and tag == dollar_tag:
                    in_dollar_quote = False
                    dollar_tag = ""
                    current.append(sql_text[i:j+1])
                    i = j + 1
                    continue
                elif not in_dollar_quote:
                    in_dollar_quote = True
                    dollar_tag = tag
                    current.append(sql_text[i:j+1])
                    i = j + 1
                    continue
        
        if in_dollar_quote:
            current.append(ch)
            i += 1
            continue
        
        # Check for single-quoted string
        if ch == "'" and not in_dollar_quote:
            if in_single_quote:
                # Check for escaped quote ('')
                if i + 1 < n and sql_text[i+1] == "'":
                    current.append("''")
                    i += 2
                    continue
                else:
                    in_single_quote = False
            else:
                in_single_quote = True
            current.append(ch)
            i += 1
            continue
        
        if in_single_quote:
            current.append(ch)
            i += 1
            continue
        
        # Track parenthesis depth
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        
        # Check for statement end (semicolon at paren_depth 0)
        if ch == ";" and paren_depth == 0:
            current.append(ch)
            statements.append("".join(current))
            current = []
            i += 1
            continue
        
        current.append(ch)
        i += 1
    
    if current:
        statements.append("".join(current))
    return statements
