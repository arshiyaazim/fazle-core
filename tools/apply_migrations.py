#!/usr/bin/env python3
"""
Apply the full migration set to a scratch database and verify the
prefix-unification rename migrations.

This mirrors what `tests/conftest.py::_run_all_migrations` does, but
against a throwaway database so the rename migrations can be exercised
without touching the test database.

Usage:
    python tools/apply_migrations.py --dsn postgresql://... [--only-prefix]
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def discover() -> list[tuple[str, str]]:
    files = []
    for d in (ROOT / "db" / "migrations", ROOT / "modules" / "fazle_payroll_engine" / "migrations"):
        if d.is_dir():
            for f in sorted(d.glob("*.sql")):
                files.append((f.name, str(f)))
    files.sort(key=lambda x: x[0])
    return files


def split_sql_safe(sql_text: str) -> list[str]:
    """Split a SQL file into statements.

    Delegates to the EXACT splitter the test harness uses
    (`tests/conftest.py::_split_sql_safe`) so this tool and the test suite
    parse the migration files identically.
    """
    import importlib.util
    conftest_path = ROOT / "tests" / "conftest.py"
    spec = importlib.util.spec_from_file_location("_fazle_conftest", conftest_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._split_sql_safe(sql_text)


async def main_async(dsn: str, only_prefix: bool) -> int:
    import asyncpg
    conn = await asyncpg.connect(dsn)
    files = discover()
    if only_prefix:
        files = [f for f in files if "_unify_rename_" in f[0]]
    errors = 0
    for label, path in files:
        text = Path(path).read_text(encoding="utf-8")
        text = re.sub(r"^\s*BEGIN\s*;", "", text, flags=re.IGNORECASE | re.MULTILINE)
        text = re.sub(r"^\s*COMMIT\s*;", "", text, flags=re.IGNORECASE | re.MULTILINE)
        for stmt in split_sql_safe(text):
            s = stmt.strip()
            if not s:
                continue
            lines = [l.strip() for l in s.split("\n") if l.strip()]
            if all(l.startswith("--") for l in lines):
                continue
            try:
                await conn.execute(s)
            except Exception as e:
                msg = str(e)[:160]
                if any(k in msg.lower() for k in (
                    "already exists", "does not exist", "duplicate",
                    "multiple primary key", "transaction is aborted",
                )):
                    continue
                errors += 1
                print(f"  [ERROR] {label}: {msg}")
    await conn.close()
    print(f"applied {len(files)} migration file(s), {errors} hard error(s)")
    return 1 if errors else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default="postgresql://postgres:changeme-set-TEST_DB_PASSWORD@127.0.0.1:5433/fazle_test")
    ap.add_argument("--only-prefix", action="store_true")
    args = ap.parse_args()
    return asyncio.run(main_async(args.dsn, args.only_prefix))


if __name__ == "__main__":
    sys.exit(main())
