#!/usr/bin/env python3
"""
Scan the repository's migration SQL for every database object attached to one
of the 7 in-scope tables, so the prefix-unification rename migrations cover
EVERY dependent object — not just the ones that happen to exist in one
particular database.

The live-DB dump (`tools/dump_prefix_db_objects.py`) is authoritative for
what exists, but a migration can be authored against a table that was
created by a different file, and a transaction rollback can leave objects
missing from a live database while the SQL source still creates them.  This
scanner closes that gap.

Usage:
    python tools/scan_sql_objects.py --out objects.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MIGRATION_DIRS = [
    ROOT / "db" / "migrations",
    ROOT / "modules" / "fazle_payroll_engine" / "migrations",
    ROOT / "migrations",
]

RE_INDEX = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_\"]+)\s+ON\s+"
    r"(?:public\.)?([A-Za-z0-9_\"]+)",
    re.IGNORECASE,
)
RE_CONSTRAINT = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:public\.)?([A-Za-z0-9_\"]+)\s+"
    r"ADD\s+CONSTRAINT\s+([A-Za-z0-9_\"]+)",
    re.IGNORECASE,
)
RE_SEQUENCE = re.compile(
    r"CREATE\s+SEQUENCE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?([A-Za-z0-9_\"]+)",
    re.IGNORECASE,
)
RE_TRIGGER = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+([A-Za-z0-9_\"]+)\s+"
    r"(?:BEFORE|AFTER|INSTEAD\s+OF).*?ON\s+(?:public\.)?([A-Za-z0-9_\"]+)",
    re.IGNORECASE | re.DOTALL,
)
RE_FUNCTION = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?([A-Za-z0-9_\"]+)\s*\(",
    re.IGNORECASE,
)
RE_TRIGGER_FN = re.compile(
    r"EXECUTE\s+(?:FUNCTION|PROCEDURE)\s+(?:public\.)?([A-Za-z0-9_\"]+)",
    re.IGNORECASE,
)


def strip_quotes(name: str) -> str:
    return name.replace('"', "")


def scan() -> dict:
    indexes: dict[str, str] = {}
    constraints: dict[str, str] = {}
    sequences: set[str] = set()
    triggers: dict[str, str] = {}
    functions: set[str] = set()
    trigger_fns: dict[str, str] = {}  # trigger name -> function name

    for d in MIGRATION_DIRS:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.sql")):
            text = f.read_text(encoding="utf-8", errors="replace")
            for m in RE_INDEX.finditer(text):
                indexes.setdefault(strip_quotes(m.group(1)), strip_quotes(m.group(2)))
            for m in RE_CONSTRAINT.finditer(text):
                constraints.setdefault(strip_quotes(m.group(2)), strip_quotes(m.group(1)))
            for m in RE_SEQUENCE.finditer(text):
                sequences.add(strip_quotes(m.group(1)))
            for m in RE_TRIGGER.finditer(text):
                trig_name = strip_quotes(m.group(1))
                triggers.setdefault(trig_name, strip_quotes(m.group(2)))
                # The trigger body names the function it executes.
                body = m.group(0)
                fm = RE_TRIGGER_FN.search(body)
                if fm:
                    trigger_fns[trig_name] = strip_quotes(fm.group(1))
            for m in RE_FUNCTION.finditer(text):
                functions.add(strip_quotes(m.group(1)))
            for m in RE_TRIGGER_FN.finditer(text):
                trigger_fns.setdefault(strip_quotes(m.group(1)), "")

    return {
        "indexes": indexes,
        "constraints": constraints,
        "sequences": sorted(sequences),
        "triggers": triggers,
        "functions": sorted(functions),
        "trigger_fns": sorted(trigger_fns),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    data = scan()
    Path(args.out).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    for k, v in data.items():
        print(f"  {k}: {len(v)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
