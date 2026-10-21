#!/usr/bin/env python3
"""
Dump the live Postgres object inventory for the 7 in-scope tables so the
STEP 1 inventory can record exactly which dependent objects a RENAME will
touch.

Usage:
    python tools/dump_prefix_db_objects.py [--dsn postgresql://...] [--out f.json]

Tables/indexes/constraints/sequences/triggers/FKs are queried from
information_schema + pg_catalog.  The dump is JSON so it can be embedded
in the inventory document.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

IN_SCOPE_TABLES = [
    "wbom_whatsapp_messages",
    "wbom_contacts",
    "wbom_cash_transactions",
    "wbom_employees",
    "fpe_cash_transactions",
    "fpe_employee_ledger",
    "fpe_employees",
]

QUERIES = {
    "tables": """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='public' AND table_name = ANY($1::text[])
        ORDER BY table_name
    """,
    "sequences": """
        SELECT c.relname AS sequence_name, n.nspname AS schema
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE c.relkind='S' AND n.nspname='public'
          AND (c.relname = ANY($1::text[])
               OR EXISTS (SELECT 1 FROM unnest($1::text[]) t
                          WHERE c.relname LIKE t || '\\_%' ESCAPE '\\'))
        ORDER BY 1
    """,
    "indexes": """
        SELECT indexname AS index_name, tablename AS on_table
        FROM pg_indexes WHERE schemaname='public' AND tablename = ANY($1::text[])
        ORDER BY tablename, indexname
    """,
    "constraints": """
        SELECT con.conname AS constraint_name,
               src.relname AS on_table,
               con.contype::text AS contype,
               tgt.relname AS references_table
        FROM pg_constraint con
        JOIN pg_class src ON src.oid=con.conrelid
        JOIN pg_namespace n ON n.oid=src.relnamespace
        LEFT JOIN pg_class tgt ON tgt.oid=con.confrelid
        WHERE n.nspname='public' AND src.relname = ANY($1::text[])
        ORDER BY src.relname, con.conname
    """,
    "foreign_keys_referencing": """
        SELECT con.conname AS fk_name,
               src.relname AS referencing_table,
               tgt.relname AS referenced_table
        FROM pg_constraint con
        JOIN pg_class src ON src.oid=con.conrelid
        JOIN pg_class tgt ON tgt.oid=con.confrelid
        JOIN pg_namespace n ON n.oid=src.relnamespace
        WHERE con.contype='f' AND n.nspname='public'
          AND tgt.relname = ANY($1::text[])
        ORDER BY tgt.relname, con.conname
    """,
    "triggers": """
        SELECT tg.tgname AS trigger_name, c.relname AS on_table,
               p.proname AS function_name
        FROM pg_trigger tg
        JOIN pg_class c ON c.oid=tg.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_proc p ON p.oid=tg.tgfoid
        WHERE n.nspname='public' AND NOT tg.tgisinternal
          AND c.relname = ANY($1::text[])
        ORDER BY c.relname, tg.tgname
    """,
    "views": """
        SELECT c.relname AS view_name FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE c.relkind IN ('v','m') AND n.nspname='public'
          AND c.relname = ANY($1::text[])
        ORDER BY 1
    """,
    "legacy_prefixed_tables": """
        SELECT c.relname AS table_name
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE c.relkind='r' AND n.nspname='public'
          AND (c.relname LIKE 'wbom\\_%' OR c.relname LIKE 'fpe\\_%')
        ORDER BY 1
    """,
}


async def main_async(dsn: str) -> dict:
    import asyncpg
    conn = await asyncpg.connect(dsn)
    out: dict = {}
    try:
        for key, q in QUERIES.items():
            rows = await conn.fetch(q, *([] if "$1" not in q else [IN_SCOPE_TABLES]))
            out[key] = [dict(r) for r in rows]
    finally:
        await conn.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=os.getenv(
        "PREFIX_DUMP_DSN",
        "postgresql://postgres:changeme-set-TEST_DB_PASSWORD@127.0.0.1:5433/fazle_test",
    ))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    data = asyncio.run(main_async(args.dsn))
    Path(args.out).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    for k, v in data.items():
        print(f"  {k}: {len(v)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
