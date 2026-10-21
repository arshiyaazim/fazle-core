#!/usr/bin/env python3
"""
review_repairs.py — Interactive review console for `review_needed` repair items.

After running repair_fpe_transactions.py --apply, any transaction that could not be
auto-repaired (fuzzy-name-only, WBOM-found-but-no-FPE-link, no-phone, no-name) is
recorded in fpe_transaction_repairs with review_needed=TRUE.

This tool presents each pending item to the admin and applies the correction only after
explicit confirmation.

Usage:
    # List all pending review items (no prompts):
    python tools/review_repairs.py --list

    # Interactive review — go through each item and approve/override/skip:
    python tools/review_repairs.py --interactive

    # Preview what the resolved state would look like for one transaction:
    python tools/review_repairs.py --list --transaction-id 294

    # Apply a specific repair with a confirmed employee:
    python tools/review_repairs.py --apply --transaction-id 294 --employee-id 35

    # Auto-approve all sim=1.00 exact fuzzy name matches (CAREFUL — names may be ambiguous):
    python tools/review_repairs.py --approve-exact

Safety contract:
    NEVER deletes rows. NEVER mutates existing transactions.
    All corrections are expressed as reverse(wrong) + insert(correct).
    Applying a repair resolves the review_needed flag in the audit table.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

import asyncpg

# ── Import shared helpers from repair_fpe_transactions ─────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from repair_fpe_transactions import (  # noqa: E402
    _resolve_db_url,
    _apply_repair,
    _AUDIT_TABLE_DDL,
    _RULE,
    SuspiciousTxn,
    MatchResult,
    RepairCandidate,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("review_repairs")

# ── Review item query ──────────────────────────────────────────────────────────

_PENDING_QUERY = """
SELECT
    r.id                    AS repair_id,
    r.transaction_id,
    r.old_employee_id,
    r.old_employee_name,
    r.new_employee_id,
    r.new_employee_name,
    r.repair_reason,
    r.match_method,
    r.review_note,
    r.repaired_at,
    t.txn_ref,
    t.amount,
    t.payout_phone,
    t.payout_method,
    t.txn_date,
    t.accounting_period,
    t.employee_name_raw,
    t.source_message_text,
    t.fpe_wa_message_id,
    e.primary_phone         AS current_employee_phone
FROM fpe_transaction_repairs r
JOIN fazle_cash_transactions t ON t.id = r.transaction_id
LEFT JOIN fazle_employees e    ON e.id = r.old_employee_id
WHERE r.review_needed = TRUE
  AND r.dry_run       = FALSE
  AND NOT EXISTS (
      SELECT 1 FROM fpe_transaction_repairs r2
      WHERE r2.transaction_id = r.transaction_id
        AND r2.review_needed  = FALSE
        AND r2.dry_run        = FALSE
  )
ORDER BY r.transaction_id DESC
"""

_PENDING_QUERY_SINGLE = _PENDING_QUERY.replace(
    "ORDER BY r.transaction_id DESC",
    "AND r.transaction_id = $1\nORDER BY r.transaction_id DESC",
)

_EMPLOYEE_SEARCH = """
SELECT id, full_name, primary_phone, status
FROM fazle_employees
WHERE status = 'active'
  AND (
      lower(full_name) LIKE lower($1)
      OR primary_phone LIKE $1
  )
ORDER BY full_name
LIMIT 20
"""

_EMPLOYEE_BY_ID = """
SELECT id, full_name, primary_phone, status
FROM fazle_employees
WHERE id = $1
"""


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class ReviewItem:
    repair_id: int
    transaction_id: int
    old_employee_id: Optional[int]
    old_employee_name: Optional[str]
    suggested_employee_id: Optional[int]
    suggested_employee_name: Optional[str]
    match_method: Optional[str]
    review_note: Optional[str]
    # full transaction fields
    txn_ref: str
    amount: Decimal
    payout_phone: Optional[str]
    payout_method: Optional[str]
    txn_date: Any
    accounting_period: Optional[str]
    employee_name_raw: Optional[str]
    source_message_text: Optional[str]
    fpe_wa_message_id: Optional[int]
    current_employee_phone: Optional[str]


# ── Fetch helpers ──────────────────────────────────────────────────────────────

async def _fetch_pending(
    conn: asyncpg.Connection,
    txn_id: Optional[int] = None,
) -> list[ReviewItem]:
    if txn_id is not None:
        rows = await conn.fetch(_PENDING_QUERY_SINGLE, txn_id)
    else:
        rows = await conn.fetch(_PENDING_QUERY)

    items: list[ReviewItem] = []
    for r in rows:
        items.append(ReviewItem(
            repair_id=r["repair_id"],
            transaction_id=r["transaction_id"],
            old_employee_id=r["old_employee_id"],
            old_employee_name=r["old_employee_name"],
            suggested_employee_id=r["new_employee_id"],
            suggested_employee_name=r["new_employee_name"],
            match_method=r["match_method"],
            review_note=r["review_note"],
            txn_ref=r["txn_ref"],
            amount=Decimal(str(r["amount"])),
            payout_phone=r["payout_phone"],
            payout_method=r["payout_method"],
            txn_date=r["txn_date"],
            accounting_period=r["accounting_period"],
            employee_name_raw=r["employee_name_raw"],
            source_message_text=r["source_message_text"],
            fpe_wa_message_id=r["fpe_wa_message_id"],
            current_employee_phone=r["current_employee_phone"],
        ))
    return items


def _fmt_item(item: ReviewItem, idx: int, total: int) -> str:
    lines = [
        _RULE,
        f"  [{idx}/{total}]  TXN #{item.transaction_id}  "
        f"৳{item.amount}  {item.payout_method or 'N/A'}  "
        f"period={item.accounting_period or 'N/A'}",
        f"  Date         : {item.txn_date}",
        f"  Raw name     : {item.employee_name_raw or 'N/A'}",
        f"  Payout phone : {item.payout_phone or 'NULL'}",
        "",
        f"  ▸ CURRENT employee  : id={item.old_employee_id}  "
        f"name={item.old_employee_name!r}  phone={item.current_employee_phone!r}",
    ]

    if item.suggested_employee_id and item.suggested_employee_id != item.old_employee_id:
        lines.append(
            f"  ▸ SUGGESTED employee: id={item.suggested_employee_id}  "
            f"name={item.suggested_employee_name!r}  method={item.match_method!r}"
        )
    else:
        lines.append(f"  ▸ SUGGESTED employee: NONE — see note below")

    if item.review_note:
        lines.append(f"  ▸ Note           : {item.review_note}")

    if item.source_message_text:
        preview = item.source_message_text[:140].replace("\n", " ")
        lines.append(f"  Message preview: {preview!r}")

    return "\n".join(lines)


# ── Apply a confirmed correction ───────────────────────────────────────────────

async def _apply_confirmed(
    conn: asyncpg.Connection,
    item: ReviewItem,
    confirmed_employee_id: int,
    repaired_by: str = "review_repairs",
) -> dict:
    """Apply a repair that the admin has explicitly confirmed."""

    # Fetch the confirmed employee details
    emp_row = await conn.fetchrow(_EMPLOYEE_BY_ID, confirmed_employee_id)
    if not emp_row:
        return {"action": "failed", "txn_id": item.transaction_id,
                "error": f"Employee id={confirmed_employee_id} not found in fazle_employees"}

    # Build a SuspiciousTxn from the review item
    txn = SuspiciousTxn(
        txn_id=item.transaction_id,
        txn_ref=item.txn_ref,
        current_employee_id=item.old_employee_id,
        current_employee_name=item.old_employee_name,
        current_employee_phone=item.current_employee_phone,
        employee_name_raw=item.employee_name_raw,
        payout_phone=item.payout_phone,
        payout_method=item.payout_method,
        amount=item.amount,
        txn_date=item.txn_date,
        accounting_period=item.accounting_period,
        fpe_wa_message_id=item.fpe_wa_message_id,
        source_message_text=item.source_message_text,
        parser_confidence=None,
        suspicion_reasons=["manually_reviewed"],
    )

    # Build a HIGH-confidence MatchResult with the confirmed employee
    match = MatchResult(
        employee_id=confirmed_employee_id,
        employee_name=emp_row["full_name"],
        match_method=f"manual_review (was: {item.match_method or 'unknown'})",
        confidence="HIGH",
        review_needed=False,
        review_note=None,
    )

    cand = RepairCandidate(txn=txn, match=match)

    tx = conn.transaction()
    await tx.start()
    try:
        result = await _apply_repair(conn, cand, dry_run=False, repaired_by=repaired_by)

        # Mark the original review_needed row as resolved
        await conn.execute(
            """
            UPDATE fpe_transaction_repairs
               SET review_needed = FALSE,
                   review_note   = review_note || ' [resolved by review_repairs]'
             WHERE id = $1
            """,
            item.repair_id,
        )

        await tx.commit()
        return result
    except Exception as exc:
        await tx.rollback()
        return {"action": "failed", "txn_id": item.transaction_id, "error": str(exc)}


# ── List mode ──────────────────────────────────────────────────────────────────

def _print_list(items: list[ReviewItem]) -> None:
    if not items:
        print("No pending review items.")
        return

    print(f"\n{'─'*72}")
    print(f"  Pending review items: {len(items)}\n")

    for i, item in enumerate(items, 1):
        sugg = (
            f"emp_id={item.suggested_employee_id} ({item.suggested_employee_name!r})"
            if item.suggested_employee_id
            else "NO SUGGESTION"
        )
        note = (item.review_note or "")[:80]
        print(
            f"  {i:>3}. TXN #{item.transaction_id:<6}  ৳{item.amount}  "
            f"phone={item.payout_phone or 'NULL':<15}  suggestion={sugg}"
        )
        if note:
            print(f"       ⚠  {note}")

    print(f"\n{'─'*72}")
    print(f"  Total: {len(items)} item(s) awaiting review")
    print(f"  Run with --interactive to resolve them.\n")


# ── Interactive mode ───────────────────────────────────────────────────────────

async def _interactive(
    conn: asyncpg.Connection,
    items: list[ReviewItem],
) -> None:
    if not items:
        print("No pending review items — nothing to do.")
        return

    total = len(items)
    resolved = 0
    skipped = 0

    print(f"\n  {total} item(s) to review. Commands at each prompt:")
    print("    a          → Accept suggested employee (if any)")
    print("    c <id>     → Choose specific employee by ID")
    print("    s <name>   → Search active employees by name/phone fragment")
    print("    skip       → Skip this item (leave as review_needed)")
    print("    q / quit   → Quit review (remaining items stay pending)")
    print()

    for i, item in enumerate(items, 1):
        print(_fmt_item(item, i, total))
        print()

        while True:
            try:
                raw = input("  Action [a / c <id> / s <fragment> / skip / q]: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Interrupted — remaining items stay pending.")
                break

            if not raw:
                continue

            # Quit
            if raw.lower() in ("q", "quit"):
                print("  Quitting review.")
                print(f"\n  Session: {resolved} resolved, {skipped} skipped, "
                      f"{total - i} remaining.\n")
                return

            # Skip
            if raw.lower() == "skip":
                skipped += 1
                print(f"  Skipped #{item.transaction_id}.")
                break

            # Accept suggestion
            if raw.lower() == "a":
                if not item.suggested_employee_id:
                    print("  ✘ No suggestion available for this item. Use 'c <id>' to specify.")
                    continue
                result = await _apply_confirmed(conn, item, item.suggested_employee_id)
                _print_result(result)
                if result.get("action") in ("repaired", "already_correct"):
                    resolved += 1
                break

            # Choose specific employee ID
            if raw.lower().startswith("c "):
                parts = raw.split(None, 1)
                if len(parts) < 2 or not parts[1].strip().isdigit():
                    print("  Usage: c <employee_id>  (e.g. 'c 35')")
                    continue
                emp_id = int(parts[1].strip())
                # Confirm before applying
                emp_row = await conn.fetchrow(_EMPLOYEE_BY_ID, emp_id)
                if not emp_row:
                    print(f"  ✘ Employee id={emp_id} not found.")
                    continue
                print(f"  → Will assign to: id={emp_row['id']}  "
                      f"name={emp_row['full_name']!r}  phone={emp_row['primary_phone']!r}")
                confirm = input("  Confirm? [y/N]: ").strip().lower()
                if confirm != "y":
                    print("  Cancelled.")
                    continue
                result = await _apply_confirmed(conn, item, emp_id)
                _print_result(result)
                if result.get("action") in ("repaired", "already_correct"):
                    resolved += 1
                break

            # Search employees
            if raw.lower().startswith("s "):
                fragment = raw[2:].strip()
                if not fragment:
                    print("  Usage: s <name or phone fragment>  (e.g. 's Hasan')")
                    continue
                rows = await conn.fetch(_EMPLOYEE_SEARCH, f"%{fragment}%")
                if not rows:
                    print(f"  No active employees matching '{fragment}'")
                else:
                    print(f"\n  Matching employees for '{fragment}':")
                    for row in rows:
                        print(f"    id={row['id']:<6} {row['full_name']:<30} "
                              f"phone={row['primary_phone'] or 'N/A'}")
                    print()
                continue

            print("  Unknown command. Try: a / c <id> / s <name> / skip / q")

    print(f"\n  Done. {resolved} resolved, {skipped} skipped.\n")


def _print_result(result: dict) -> None:
    action = result.get("action", "?")
    txn_id = result.get("txn_id", "?")
    if action == "repaired":
        print(f"  ✔ #{txn_id} repaired: {result['old_employee']} → {result['new_employee']}")
    elif action == "already_correct":
        print(f"  – #{txn_id} already correct (no change needed).")
    elif action == "failed":
        print(f"  ✘ #{txn_id} FAILED: {result.get('error', 'unknown error')}")
    else:
        print(f"  ? #{txn_id} action={action}")


# ── Approve-exact mode ─────────────────────────────────────────────────────────

async def _approve_exact(
    conn: asyncpg.Connection,
    items: list[ReviewItem],
) -> None:
    """
    Auto-approve items where match_method='fuzzy_name' AND the note shows sim=1.00
    AND a suggested employee_id is present.

    CAUTION: Only use this when you are confident that common names (e.g. 'Hasan')
    have been disambiguated by the fuzzy matcher. Review the list first.
    """
    exact = [
        item for item in items
        if item.match_method == "fuzzy_name"
        and item.suggested_employee_id is not None
        and item.review_note is not None
        and "sim=1.00" in item.review_note
    ]

    if not exact:
        print("No sim=1.00 exact fuzzy matches found in pending items.")
        return

    print(f"\n  Found {len(exact)} exact-match (sim=1.00) items:")
    for item in exact:
        print(f"    TXN #{item.transaction_id}  "
              f"'{item.employee_name_raw}' → id={item.suggested_employee_id} "
              f"'{item.suggested_employee_name}'")

    confirm = input(f"\n  Apply all {len(exact)} corrections? [y/N]: ").strip().lower()
    if confirm != "y":
        print("  Cancelled.")
        return

    resolved = 0
    for item in exact:
        result = await _apply_confirmed(conn, item, item.suggested_employee_id,
                                        repaired_by="review_repairs:approve_exact")
        _print_result(result)
        if result.get("action") in ("repaired", "already_correct"):
            resolved += 1

    print(f"\n  {resolved}/{len(exact)} exact matches resolved.\n")


# ── Apply single ───────────────────────────────────────────────────────────────

async def _apply_single(
    conn: asyncpg.Connection,
    txn_id: int,
    employee_id: int,
) -> None:
    items = await _fetch_pending(conn, txn_id)
    if not items:
        print(f"  No pending review item found for TXN #{txn_id}.")
        return
    item = items[0]
    print(_fmt_item(item, 1, 1))
    emp_row = await conn.fetchrow(_EMPLOYEE_BY_ID, employee_id)
    if not emp_row:
        print(f"  ✘ Employee id={employee_id} not found.")
        return
    print(f"\n  → Assigning to: id={emp_row['id']}  name={emp_row['full_name']!r}  "
          f"phone={emp_row['primary_phone']!r}")
    result = await _apply_confirmed(conn, item, employee_id)
    _print_result(result)


# ── Main ────────────────────────────────────────────────────────────────────────

async def main(args: argparse.Namespace) -> int:
    url = _resolve_db_url()
    conn: asyncpg.Connection = await asyncpg.connect(url)
    try:
        await conn.execute(_AUDIT_TABLE_DDL)

        if args.apply and args.transaction_id and args.employee_id:
            await _apply_single(conn, args.transaction_id, args.employee_id)
            return 0

        items = await _fetch_pending(conn, args.transaction_id)

        if args.list or not sys.stdin.isatty():
            _print_list(items)
            return 0

        if args.approve_exact:
            await _approve_exact(conn, items)
            return 0

        # Default / --interactive
        await _interactive(conn, items)
        return 0

    finally:
        await conn.close()


def _parse_args() -> argparse.Namespace:
    from textwrap import dedent
    parser = argparse.ArgumentParser(
        description=dedent(__doc__ or ""),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--list", action="store_true",
        help="Print all pending review items without prompting.",
    )
    parser.add_argument(
        "--interactive", action="store_true",
        help="Step through each review item and approve/override/skip. (Default if TTY.)",
    )
    parser.add_argument(
        "--approve-exact", action="store_true",
        help=(
            "Auto-approve all sim=1.00 fuzzy-name matches that have a suggested employee. "
            "CAUTION: verify list first."
        ),
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply a single repair. Requires --transaction-id and --employee-id.",
    )
    parser.add_argument(
        "--transaction-id", type=int, metavar="N",
        help="Restrict to a single transaction ID.",
    )
    parser.add_argument(
        "--employee-id", type=int, metavar="N",
        help="Employee ID to assign when using --apply.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(asyncio.run(main(args)))
