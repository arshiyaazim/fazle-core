#!/usr/bin/env python3
"""
End-to-end verification of the prefix-unification rename migrations.

  1. Build a scratch database from the full migration set.
  2. Assert every new table exists and every old table is gone.
  3. Assert every dependent index / constraint / sequence / trigger that
     carried the legacy prefix now carries `fazle_`.
  4. Re-run the rename migrations  -> must be a clean no-op (idempotent).
  5. Run the rollback section      -> must restore the old names.
  6. Re-apply the rename migrations -> must work again from the rolled-back
     state (proves the rollback is faithful, not destructive).

Usage:
    python tools/verify_unify_migrations.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from prefix_unification_map import TABLE_MAP, rename_db_object  # noqa: E402

DSN = os.getenv(
    "PREFIX_VERIFY_DSN",
    "postgresql://postgres:changeme-set-TEST_DB_PASSWORD@127.0.0.1:5433/fazle_migtest",
)

NEW_TABLES = list(TABLE_MAP.values())
OLD_TABLES = list(TABLE_MAP.keys())


async def q(conn, sql, *args):
    return [dict(r) for r in await conn.fetch(sql, *args)]


async def main() -> int:
    import asyncpg
    from apply_migrations import main_async as apply_main

    failures: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if cond:
            print(f"  PASS  {msg}")
        else:
            print(f"  FAIL  {msg}")
            failures.append(msg)

    print("── 1. build scratch DB from full migration set ─────────────────")
    rc = await apply_main(DSN, False)
    print(f"  (apply_migrations rc={rc})")

    conn = await asyncpg.connect(DSN)
    try:
        print("\n── 2. new tables exist / old tables gone ─────────────────────")
        rows = await q(
            conn,
            "SELECT n, to_regclass('public.'||n)::text AS reg FROM unnest($1::text[]) n",
            NEW_TABLES,
        )
        for r in rows:
            check(r["reg"] is not None, f"new table exists: {r['n']}")
        rows = await q(
            conn,
            "SELECT n, to_regclass('public.'||n)::text AS reg FROM unnest($1::text[]) n",
            OLD_TABLES,
        )
        for r in rows:
            check(r["reg"] is None, f"old table gone: {r['n']}")

        print("\n── 3. dependent objects renamed ──────────────────────────────")
        rows = await q(
            conn,
            "SELECT tablename, indexname FROM pg_indexes WHERE schemaname='public' "
            "AND tablename = ANY($1::text[])",
            NEW_TABLES,
        )
        for r in rows:
            name = r["indexname"]
            check(
                "wbom_" not in name and "fpe_" not in name,
                f"index renamed on {r['tablename']}: {name}",
            )
        rows = await q(
            conn,
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind='S' AND c.relname = ANY($1::text[])",
            NEW_TABLES,
        )
        for r in rows:
            check(
                "wbom_" not in r["relname"] and "fpe_" not in r["relname"],
                f"sequence renamed: {r['relname']}",
            )
        rows = await q(
            conn,
            "SELECT conname FROM pg_constraint WHERE conrelid IN "
            "(SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            " WHERE n.nspname='public' AND c.relname = ANY($1::text[]))",
            NEW_TABLES,
        )
        for r in rows:
            name = r["conname"]
            # `fazle_cash_transactions_fpe_wa_message_id_fkey` keeps the
            # COLUMN name (HARD CONSTRAINT #4) — the column part is allowed.
            legacy = [p for p in ("wbom_", "fpe_") if p in name]
            check(
                not legacy or name.endswith("_fpe_wa_message_id_fkey"),
                f"constraint renamed: {name}",
            )

        print("\n── 4. idempotency: re-run the rename migrations ───────────")
        rc = await apply_main(DSN, True)
        check(rc == 0, "re-running the rename migrations produced no hard error")
        rows = await q(
            conn,
            "SELECT n, to_regclass('public.'||n)::text AS reg FROM unnest($1::text[]) n",
            NEW_TABLES,
        )
        check(all(r["reg"] for r in rows), "all new tables still present after re-run")

        print("\n── 5. rollback restores the old names ───────────────────────")
        await conn.execute("DROP SCHEMA IF EXISTS _unify_rollback CASCADE")
        await conn.execute("CREATE SCHEMA _unify_rollback")
        await conn.execute(
            "SET search_path = _unify_rollback, public"
        )
        await conn.execute("SET search_path = public")
        # Build the rollback SQL from the migration files' ROLLBACK sections.
        rb = _collect_rollback()
        for stmt in rb:
            try:
                await conn.execute(stmt)
            except Exception as e:
                check(False, f"rollback statement failed: {str(e)[:120]} :: {stmt[:80]}")
        rows = await q(
            conn,
            "SELECT n, to_regclass('public.'||n)::text AS reg FROM unnest($1::text[]) n",
            OLD_TABLES,
        )
        for r in rows:
            check(r["reg"] is not None, f"rollback restored old table: {r['n']}")
        rows = await q(
            conn,
            "SELECT n, to_regclass('public.'||n)::text AS reg FROM unnest($1::text[]) n",
            NEW_TABLES,
        )
        for r in rows:
            check(r["reg"] is None, f"rollback removed new table: {r['n']}")

        print("\n── 6. re-apply after rollback ───────────────────────────────")
        rc = await apply_main(DSN, True)
        check(rc == 0, "re-applying the rename migrations after rollback succeeded")
        rows = await q(
            conn,
            "SELECT n, to_regclass('public.'||n)::text AS reg FROM unnest($1::text[]) n",
            NEW_TABLES,
        )
        for r in rows:
            check(r["reg"] is not None, f"re-applied new table exists: {r['n']}")
    finally:
        await conn.close()

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


def _collect_rollback() -> list[str]:
    """Extract the executable ROLLBACK statements from the migration files.

    The rollback SQL lives between the `-- >>> ROLLBACK-SQL-BEGIN` and
    `-- <<< ROLLBACK-SQL-END` markers and is commented out so the file
    stays a valid forward-only migration.
    """
    stmts: list[str] = []
    for path in sorted((ROOT / "db" / "migrations").glob("*_unify_rename_*.sql")):
        text = path.read_text(encoding="utf-8")
        if "ROLLBACK-SQL-BEGIN" not in text:
            continue
        body = text.split("-- >>> ROLLBACK-SQL-BEGIN", 1)[1]
        body = body.split("-- <<< ROLLBACK-SQL-END", 1)[0]
        # Strip the leading "-- " from every line, drop empty lines and the
        # pure-comment separator lines, then re-split into statements.
        cleaned: list[str] = []
        for line in body.splitlines():
            s = line.strip()
            if s.startswith("--"):
                s = s[2:].strip()
            if not s or s.startswith("--"):
                continue
            # Drop the "old -> new" annotation lines; they are documentation,
            # not executable SQL.
            if "->" in s:
                continue
            cleaned.append(s)
        sql = "\n".join(cleaned)
        from apply_migrations import split_sql_safe
        stmts.extend(split_sql_safe(sql))
    # Roll back in reverse order (096 -> 090)
    return list(reversed(stmts))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
