#!/usr/bin/env python3
"""Provision a NEW PostgreSQL database for Fazle Core.

This is intentionally separate from ``db/migrate.py``:

* bootstrap.py = empty/new database, foundation + every migration + runtime DDL
* migrate.py   = an existing deployment, canonical incremental migrations only

Usage:
    python db/bootstrap.py --plan
    python db/bootstrap.py --database-url postgresql://... --check
    python db/bootstrap.py --database-url postgresql://... --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:  # Keep --plan dependency-free, but honor the repo-local .env when available.
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

FOUNDATION = ROOT / "db" / "schema" / "000_foundation.sql"
RUNTIME_SUPPORT = ROOT / "db" / "schema" / "900_runtime_support.sql"
MIGRATION_DIRS = (
    ("core", ROOT / "db" / "migrations"),
    ("fpe", ROOT / "modules" / "fazle_payroll_engine" / "migrations"),
)
# Production-data reconciliation, not schema. It deliberately asserts that a
# fixed set of legacy row IDs already exists and therefore must not run on an
# empty/new database (its own header also says owner activation is pending).
NEW_DATABASE_EXCLUSIONS = frozenset({"086_k32_recruitment_reconciliation.sql"})
REQUIRED_TABLES = frozenset(
    {
        "fazle_whatsapp_messages",
        "fazle_contacts",
        "fazle_employees",
        "fazle_cash_transactions",
        "fazle_draft_replies",
        "fazle_outbound_queue",
        "wbom_candidates",
        "wbom_escort_programs",
    }
)


@dataclass(frozen=True)
class Step:
    source: str
    path: Path

    @property
    def key(self) -> str:
        return f"{self.source}/{self.path.name}"


def migration_steps() -> list[Step]:
    migrations: list[Step] = []
    for source, directory in MIGRATION_DIRS:
        migrations.extend(
            Step(source, path)
            for path in sorted(directory.glob("*.sql"))
            if path.name not in NEW_DATABASE_EXCLUSIONS
        )
    # Preserve the test-certified historical ordering. The source is the
    # deterministic tie-breaker for duplicate numeric filenames.
    migrations.sort(key=lambda item: (item.path.name, item.source))
    return [Step("schema", FOUNDATION), *migrations, Step("schema", RUNTIME_SUPPORT)]


def _strip_transaction_wrappers(sql: str) -> str:
    # Each whole file is wrapped by asyncpg below. Historical files that carry
    # their own top-level BEGIN/COMMIT must not create a nested transaction.
    sql = re.sub(r"^\s*BEGIN\s*;", "", sql, flags=re.IGNORECASE | re.MULTILINE)
    sql = re.sub(r"^\s*COMMIT\s*;", "", sql, flags=re.IGNORECASE | re.MULTILINE)
    return sql


def _database_name(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).path.lstrip("/").split("?", 1)[0]


async def _connect(url: str):
    try:
        import asyncpg
    except ImportError as exc:  # pragma: no cover - operator environment
        raise RuntimeError("asyncpg is required; install requirements.txt first") from exc
    return await asyncpg.connect(url, command_timeout=120)


async def check(url: str) -> int:
    conn = await _connect(url)
    try:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public'"
        )
        found = {str(row["tablename"]) for row in rows}
        missing = sorted(REQUIRED_TABLES - found)
        versions = 0
        if "fazle_schema_versions" in found:
            versions = int(await conn.fetchval("SELECT COUNT(*) FROM fazle_schema_versions"))
        print(f"database={_database_name(url)} tables={len(found)} versions={versions}")
        if missing:
            print("missing required tables: " + ", ".join(missing), file=sys.stderr)
            return 1
        print("schema check: OK")
        return 0
    finally:
        await conn.close()


async def apply(url: str, allow_nonempty: bool = False) -> int:
    conn = await _connect(url)
    try:
        existing_count = int(
            await conn.fetchval(
                "SELECT COUNT(*) FROM pg_catalog.pg_tables "
                "WHERE schemaname='public' AND tablename <> 'fazle_schema_versions'"
            )
        )
        if existing_count and not allow_nonempty:
            raise RuntimeError(
                f"refusing bootstrap: public schema already has {existing_count} table(s); "
                "use db/migrate.py for an existing database or pass --allow-nonempty "
                "only after reviewing the plan"
            )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fazle_schema_versions (
                migration_key TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        import hashlib

        for step in migration_steps():
            raw = step.path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            previous = await conn.fetchrow(
                "SELECT checksum FROM fazle_schema_versions WHERE migration_key=$1",
                step.key,
            )
            if previous:
                if previous["checksum"] != checksum:
                    raise RuntimeError(
                        f"applied schema step changed on disk: {step.key}; "
                        "never edit an applied migration"
                    )
                print(f"  skip    {step.key}")
                continue
            sql = _strip_transaction_wrappers(raw)
            try:
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO fazle_schema_versions(migration_key, checksum) "
                        "VALUES($1, $2)",
                        step.key,
                        checksum,
                    )
            except Exception as exc:
                raise RuntimeError(f"bootstrap failed at {step.key}: {exc}") from exc
            print(f"  applied {step.key}")
    finally:
        await conn.close()
    return await check(url)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Bootstrap a new Fazle Core PostgreSQL schema")
    action = result.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", action="store_true", help="print ordered SQL steps; no DB needed")
    action.add_argument("--check", action="store_true", help="validate required schema objects")
    action.add_argument("--apply", action="store_true", help="apply the complete schema to a new DB")
    result.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    result.add_argument("--allow-nonempty", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.plan:
        for number, step in enumerate(migration_steps(), start=1):
            print(f"{number:03d} {step.key}")
        return 0
    if not args.database_url:
        print("DATABASE_URL or --database-url is required", file=sys.stderr)
        return 2
    if not _database_name(args.database_url):
        print("database URL must include an explicit database name", file=sys.stderr)
        return 2
    try:
        if args.check:
            return asyncio.run(check(args.database_url))
        return asyncio.run(apply(args.database_url, args.allow_nonempty))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
