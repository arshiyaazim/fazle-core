#!/usr/bin/env python3
"""Validate WhatsApp MCP/whatsmeow SQLite stores without PostgreSQL.

Examples:
    python scripts/check_bridge_db.py --messages /srv/bridge/store/messages.db \
        --whatsapp /srv/bridge/store/whatsapp.db
    python scripts/check_bridge_db.py --configured --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Permit direct execution from any working directory.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.bridge_store import (  # noqa: E402
    BridgeStoreSpec,
    configured_bridge_specs,
    inspect_bridge_store,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only compatibility check for WhatsApp bridge databases"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--configured",
        action="store_true",
        help="check BRIDGE1/2/3 paths from .env/app settings",
    )
    group.add_argument("--messages", help="path or sqlite:/// DSN for messages DB")
    parser.add_argument("--whatsapp", default="", help="optional whatsapp.db path")
    parser.add_argument("--name", default="bridge", help="report label")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def _render(report: dict) -> str:
    mark = "OK" if report["compatible"] else "FAIL"
    lines = [
        f"[{mark}] {report['name']}: {report['status']}",
        f"  messages: {report['messages_path']}",
        f"  table: {report.get('message_table') or '-'}",
        f"  schema fingerprint: {report.get('schema_fingerprint') or '-'}",
    ]
    if report.get("columns"):
        mapping = ", ".join(
            f"{canonical}={physical}"
            for canonical, physical in sorted(report["columns"].items())
        )
        lines.append(f"  mapping: {mapping}")
    if report.get("error"):
        lines.append(f"  error: {report['error']}")
    for warning in report.get("warnings", []):
        lines.append(f"  warning: {warning}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.configured:
        try:
            from app.config import get_settings

            specs = configured_bridge_specs(get_settings())
        except Exception as exc:
            print(f"configuration error: {exc}", file=sys.stderr)
            return 2
    else:
        specs = [BridgeStoreSpec(args.name, args.messages, args.whatsapp)]

    reports = [inspect_bridge_store(spec).to_dict() for spec in specs]
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        print("\n".join(_render(report) for report in reports))
    return 0 if all(report["compatible"] for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
