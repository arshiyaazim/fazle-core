#!/usr/bin/env python3
"""
repair_fpe_transactions.py — Safe repair tool for mis-matched FPE cash transactions.

SAFE OPERATION CONTRACT:
  • NEVER deletes rows.
  • NEVER mutates existing transaction rows.
  • Corrections are expressed as: reverse(wrong txn) + create(new correct txn).
  • Every applied correction writes an audit row to fpe_transaction_repairs.
  • --dry-run executes the full logic inside a rolled-back transaction (zero DB side-effects).
  • --preview never opens a write transaction at all.

Usage examples:
    # See all suspicious transactions (read-only):
    python tools/repair_fpe_transactions.py --preview

    # Preview one specific transaction:
    python tools/repair_fpe_transactions.py --preview --transaction-id 889

    # Rehearse the repair without committing (shows what SQL would run):
    python tools/repair_fpe_transactions.py --apply --dry-run --transaction-id 889

    # Apply the repair for real:
    python tools/repair_fpe_transactions.py --apply --transaction-id 889

Matching priority (strict, phone-first):
    1. fazle_employees.primary_phone       = transaction.payout_phone
    2. fazle_employees.employee_id_phone   = transaction.payout_phone
    3. fpe_employee_aliases.alias_value  = transaction.payout_phone
    4. fazle_employees_legacy.bkash_number       = transaction.payout_phone  (+ fpe link)
    5. fazle_employees_legacy.nagad_number       = transaction.payout_phone  (+ fpe link)
    6. fazle_employees_legacy.employee_mobile    = transaction.payout_phone  (+ fpe link)
    7. Fuzzy name match                  — SUGGESTION ONLY, never auto-applied
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from textwrap import dedent
from typing import Any, Optional

import asyncpg

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("repair_tool")


# ── DB connection ─────────────────────────────────────────────────────────────

def _resolve_db_url() -> str:
    """
    Resolve the database URL.  Tries (in order):
    1. DATABASE_URL environment variable (already-resolved, e.g. set by systemd)
    2. DATABASE_URL_TEMPLATE in core/.env with __HOST__ substituted via
       `docker inspect ai-postgres` container IP.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
    env_file = os.path.normpath(env_file)
    template: Optional[str] = None
    if os.path.exists(env_file):
        with open(env_file) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("DATABASE_URL_TEMPLATE="):
                    template = line.split("=", 1)[1]
                    break

    if template and "__HOST__" in template:
        import subprocess
        try:
            ip = subprocess.check_output(
                ["docker", "inspect", "ai-postgres",
                 "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"],
                text=True,
            ).strip()
            return template.replace("__HOST__", ip)
        except Exception as exc:
            log.warning("docker inspect failed: %s — trying localhost fallback", exc)
            return template.replace("__HOST__", "localhost")

    raise RuntimeError(
        "Cannot resolve DATABASE_URL. "
        "Set DATABASE_URL env var or ensure core/.env has DATABASE_URL_TEMPLATE."
    )


# ── Audit table DDL ───────────────────────────────────────────────────────────

_AUDIT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS fpe_transaction_repairs (
    id                  BIGSERIAL PRIMARY KEY,
    transaction_id      BIGINT      NOT NULL REFERENCES fazle_cash_transactions(id),
    old_employee_id     BIGINT,
    new_employee_id     BIGINT,
    old_employee_name   TEXT,
    new_employee_name   TEXT,
    repair_reason       TEXT,
    match_method        TEXT,
    reversal_txn_id     BIGINT      REFERENCES fazle_cash_transactions(id),
    new_txn_id          BIGINT      REFERENCES fazle_cash_transactions(id),
    review_needed       BOOLEAN     NOT NULL DEFAULT FALSE,
    review_note         TEXT,
    dry_run             BOOLEAN     NOT NULL DEFAULT FALSE,
    repaired_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    repaired_by         TEXT        NOT NULL DEFAULT 'repair_tool'
);
COMMENT ON TABLE fpe_transaction_repairs IS
  'Audit trail for every transaction re-assignment made by repair_fpe_transactions.py';
"""


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class SuspiciousTxn:
    """A transaction that may be incorrectly assigned to an employee."""
    txn_id: int
    txn_ref: str
    current_employee_id: Optional[int]
    current_employee_name: Optional[str]
    current_employee_phone: Optional[str]
    employee_name_raw: Optional[str]
    payout_phone: Optional[str]
    payout_method: Optional[str]
    amount: Decimal
    txn_date: date
    accounting_period: Optional[str]
    fpe_wa_message_id: Optional[int]
    source_message_text: Optional[str]
    parser_confidence: Optional[float]
    suspicion_reasons: list[str] = field(default_factory=list)


@dataclass
class MatchResult:
    """Result of attempting to find the correct employee."""
    employee_id: Optional[int]
    employee_name: Optional[str]
    match_method: Optional[str]     # e.g. "primary_phone", "alias_bkash", etc.
    confidence: str                  # "HIGH" | "MEDIUM" | "LOW"
    review_needed: bool
    review_note: Optional[str] = None


@dataclass
class RepairCandidate:
    """A suspicious transaction paired with a match result."""
    txn: SuspiciousTxn
    match: MatchResult


# ── Suspicion detection ───────────────────────────────────────────────────────

_SUSPICION_QUERY = """
SELECT
    t.id                                AS txn_id,
    t.txn_ref,
    t.employee_id                       AS current_employee_id,
    e.full_name                         AS current_employee_name,
    e.primary_phone                     AS current_employee_phone,
    t.employee_name_raw,
    t.payout_phone,
    t.payout_method,
    t.amount,
    t.txn_date,
    t.accounting_period,
    t.fpe_wa_message_id,
    t.source_message_text,
    pr.confidence                       AS parser_confidence,
    pr.parsed_data
FROM fazle_cash_transactions t
LEFT JOIN fazle_employees e  ON e.id = t.employee_id
LEFT JOIN fpe_wa_messages m ON m.id = t.fpe_wa_message_id
LEFT JOIN fpe_parser_results pr ON pr.fpe_wa_message_id = m.id
WHERE
    t.is_reversal = FALSE
    AND NOT EXISTS (
        SELECT 1 FROM fazle_cash_transactions rev
        WHERE rev.reversed_txn_id = t.id AND rev.is_reversal = TRUE
    )
    AND NOT EXISTS (
        SELECT 1 FROM fpe_transaction_repairs rep
        WHERE rep.transaction_id = t.id AND rep.review_needed = FALSE AND rep.dry_run = FALSE
    )
ORDER BY t.id DESC
"""

_SUSPICION_QUERY_SINGLE = _SUSPICION_QUERY.replace(
    "ORDER BY t.id DESC",
    "AND t.id = $1\nORDER BY t.id DESC",
)


# ── BD phone extraction from free-form text ──────────────────────────────────

_RE_INTERDIGIT_NOISE = re.compile(r"(?<=\d)[\s\-](?=\d)")
_RE_BD_PHONE_LOOSE   = re.compile(r"(?:\+?880)?0[1-9]\d{9}", re.ASCII)


def _extract_phone_from_text(text: Optional[str]) -> Optional[str]:
    """Pull the first BD phone from free-form text (same logic as shared/phone.py)."""
    if not text:
        return None
    cleaned = _RE_INTERDIGIT_NOISE.sub("", text)
    phones = _RE_BD_PHONE_LOOSE.findall(cleaned)
    if not phones:
        return None
    raw = phones[0]
    # Normalise to 11-digit 01XXXXXXXXX form
    digits = re.sub(r"[^\d]", "", raw)
    if digits.startswith("880"):
        digits = "0" + digits[3:]
    return digits if len(digits) == 11 else None


def _score_suspicion(row: dict) -> list[str]:
    """Return a list of suspicion reasons for a transaction row. Empty = not suspicious."""
    reasons: list[str] = []
    payout_phone = row.get("payout_phone")
    emp_phone    = row.get("current_employee_phone")
    emp_name     = row.get("current_employee_name") or ""
    raw_name     = row.get("employee_name_raw") or ""
    conf         = row.get("parser_confidence")
    source_text  = row.get("source_message_text") or ""

    # When payout_phone is null on the transaction row, try to recover from the
    # source message text so downstream re-matching has something to work with.
    recovered_phone: Optional[str] = None
    if not payout_phone and source_text:
        recovered_phone = _extract_phone_from_text(source_text)
        if recovered_phone:
            row["_recovered_phone"] = recovered_phone  # pass forward to matching

    effective_phone = payout_phone or recovered_phone

    # 1. Phone mismatch: effective phone doesn't match the assigned employee
    if effective_phone and emp_phone and effective_phone != emp_phone:
        reasons.append(
            f"phone_mismatch: effective_phone={effective_phone!r} != "
            f"emp.primary_phone={emp_phone!r}"
        )

    # 2. No payout phone (even after recovery attempt)
    if not effective_phone:
        reasons.append(
            "null_payout_phone: payout_phone is NULL and no phone recoverable "
            "from source text — fuzzy-only match likely"
        )
    elif not payout_phone and recovered_phone:
        reasons.append(
            f"payout_phone_was_null: recovered {recovered_phone!r} from source text — "
            "transaction was stored without phone (parser bug, now fixed)"
        )

    # 3. Low parser confidence
    if conf is not None and conf < 0.70:
        reasons.append(f"low_confidence: parser_confidence={conf:.2f}")

    # 4. Name mismatch: raw name is very different from matched employee's name
    if emp_name and raw_name:
        sim = _name_similarity(raw_name, emp_name)
        if sim < 0.40:
            reasons.append(
                f"name_mismatch: '{raw_name}' vs '{emp_name}' (similarity={sim:.2f})"
            )

    # 5. Parser stored employee_id_phone=null while a phone was present — BUT
    #    only flag this if the phone does NOT already match the current employee
    #    (i.e., skip if the assignment is already correct).
    parsed = row.get("parsed_data") or {}
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except Exception:
            parsed = {}
    if (
        parsed.get("employee_id_phone") is None
        and parsed.get("payout_phone")
        and not (effective_phone and emp_phone and effective_phone == emp_phone)
    ):
        reasons.append(
            "null_employee_id_phone_in_parser: parser found no ID phone — "
            "fallback match used and phone does NOT match current employee"
        )

    return reasons


def _name_similarity(a: str, b: str) -> float:
    """Simple token-overlap similarity (0.0–1.0). No external deps needed."""
    def tokens(s: str) -> set:
        return set(re.sub(r"[^a-z0-9]", " ", s.lower()).split())
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    intersection = ta & tb
    return len(intersection) / max(len(ta), len(tb))


# ── Strict re-matching ────────────────────────────────────────────────────────

async def _find_correct_employee(
    conn: asyncpg.Connection,
    payout_phone: Optional[str],
    payout_method: Optional[str],
    name_raw: Optional[str],
) -> MatchResult:
    """
    Re-match using strict phone-first priority.
    Returns a MatchResult with confidence and match_method.
    Fuzzy name is used as LAST resort and marked LOW confidence / review_needed.
    """
    if not payout_phone and not name_raw:
        return MatchResult(None, None, None, "LOW", True,
                           "No phone and no name — cannot re-match")

    # ── Priority 1: fazle_employees.primary_phone ───────────────────────────────
    if payout_phone:
        row = await conn.fetchrow(
            "SELECT id, full_name FROM fazle_employees "
            "WHERE primary_phone = $1 AND status = 'active' LIMIT 1",
            payout_phone,
        )
        if row:
            return MatchResult(row["id"], row["full_name"],
                               "primary_phone", "HIGH", False)

    # ── Priority 2: fazle_employees.employee_id_phone ───────────────────────────
    if payout_phone:
        row = await conn.fetchrow(
            "SELECT id, full_name FROM fazle_employees "
            "WHERE employee_id_phone = $1 AND status = 'active' LIMIT 1",
            payout_phone,
        )
        if row:
            return MatchResult(row["id"], row["full_name"],
                               "employee_id_phone", "HIGH", False)

    # ── Priority 3: fpe_employee_aliases ─────────────────────────────────────
    if payout_phone:
        row = await conn.fetchrow(
            """
            SELECT e.id, e.full_name
            FROM fpe_employee_aliases a
            JOIN fazle_employees e ON e.id = a.employee_id
            WHERE a.alias_value = $1
              AND a.alias_type IN ('mobile', 'bkash', 'nagad', 'phone')
              AND e.status = 'active'
            LIMIT 1
            """,
            payout_phone,
        )
        if row:
            return MatchResult(row["id"], row["full_name"],
                               "alias_phone", "HIGH", False)

    # ── Priority 4–6: WBOM cross-lookup ──────────────────────────────────────
    if payout_phone:
        # Check bkash, nagad, mobile in fazle_employees_legacy then follow to fpe
        for wbom_col, label in [
            ("bkash_number", "wbom_bkash"),
            ("nagad_number", "wbom_nagad"),
            ("employee_mobile", "wbom_mobile"),
        ]:
            wbom_row = await conn.fetchrow(
                f"SELECT employee_id, employee_name FROM fazle_employees_legacy "
                f"WHERE {wbom_col} = $1 AND status != 'inactive' LIMIT 1",
                payout_phone,
            )
            if wbom_row:
                # Try to find FPE employee linked to this WBOM employee
                fpe_row = await conn.fetchrow(
                    "SELECT id, full_name FROM fazle_employees "
                    "WHERE wbom_employee_id = $1 AND status = 'active' LIMIT 1",
                    wbom_row["employee_id"],
                )
                if fpe_row:
                    return MatchResult(fpe_row["id"], fpe_row["full_name"],
                                       label, "HIGH", False)
                # WBOM employee found but no FPE link — medium confidence
                return MatchResult(
                    None, wbom_row["employee_name"], label, "MEDIUM", True,
                    f"WBOM employee found (id={wbom_row['employee_id']}) "
                    "but no linked fazle_employees row — manual link needed",
                )

    # ── Priority 7: Fuzzy name — SUGGESTION ONLY, LOW confidence ─────────────
    if name_raw:
        collapsed = re.sub(r"[^a-z0-9]", "", name_raw.lower())
        rows = await conn.fetch(
            """
            SELECT id, full_name,
                   similarity(lower(full_name), lower($1)) AS sim
            FROM fazle_employees
            WHERE status = 'active'
              AND similarity(lower(full_name), lower($1)) > 0.30
            ORDER BY sim DESC
            LIMIT 3
            """,
            name_raw,
        )
        if rows:
            best = rows[0]
            note = (
                f"Fuzzy name match: '{name_raw}' → '{best['full_name']}' "
                f"(sim={best['sim']:.2f}). "
                f"NEVER auto-applied — human review required."
            )
            return MatchResult(best["id"], best["full_name"],
                               "fuzzy_name", "LOW", True, note)

    return MatchResult(None, None, None, "LOW", True,
                       f"No match found for phone={payout_phone!r} name={name_raw!r}")


# ── Repair core logic ─────────────────────────────────────────────────────────

_MIN_CONFIDENCE_FOR_AUTO_APPLY = "HIGH"   # LOW or MEDIUM → skip, mark review_needed


def _build_txn_ref(
    wa_message_id: Optional[int],
    employee_id: int,
    amount: Decimal,
    suffix: str = "",
) -> str:
    """Build a stable txn_ref for the corrected transaction."""
    raw = f"repair|wamsg={wa_message_id}|emp={employee_id}|amt={amount}{suffix}"
    return "REPAIR-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


async def _apply_repair(
    conn: asyncpg.Connection,
    cand: RepairCandidate,
    dry_run: bool,
    repaired_by: str = "repair_tool",
) -> dict:
    """
    Execute the correction for one candidate inside an existing transaction.
    Returns a summary dict.

    Steps:
      a) Create reversal of the wrong transaction (is_reversal=TRUE, amount=-ve)
      b) Insert new correct transaction (positive amount, new employee_id)
      c) Write fpe_transaction_repairs audit row
      d) Adjust employee ledger (subtract from old, add to new)
    """
    txn = cand.txn
    match = cand.match

    if match.confidence != _MIN_CONFIDENCE_FOR_AUTO_APPLY:
        # Record review_needed row without touching the transaction
        await conn.execute(
            """
            INSERT INTO fpe_transaction_repairs
                (transaction_id, old_employee_id, new_employee_id,
                 old_employee_name, new_employee_name,
                 repair_reason, match_method,
                 review_needed, review_note, dry_run, repaired_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,TRUE,$8,$9,$10)
            ON CONFLICT DO NOTHING
            """,
            txn.txn_id,
            txn.current_employee_id, match.employee_id,
            txn.current_employee_name, match.employee_name,
            "; ".join(txn.suspicion_reasons),
            match.match_method,
            match.review_note,
            dry_run,
            repaired_by,
        )
        return {
            "action": "review_needed",
            "txn_id": txn.txn_id,
            "reason": match.review_note or "low confidence",
        }

    # Safety: do not re-assign to the same employee
    if match.employee_id == txn.current_employee_id:
        return {"action": "already_correct", "txn_id": txn.txn_id}

    # ── a) Reversal of wrong transaction ──────────────────────────────────────
    reversal_ref = f"REV-{txn.txn_ref}"
    existing_rev = await conn.fetchrow(
        "SELECT id FROM fazle_cash_transactions WHERE txn_ref = $1",
        reversal_ref,
    )
    if existing_rev:
        reversal_id = existing_rev["id"]
        log.info("  Reversal already exists (id=%d), reusing.", reversal_id)
    else:
        reversal_id = await conn.fetchval(
            """
            INSERT INTO fazle_cash_transactions
                (txn_ref, fpe_wa_message_id, employee_id, employee_name_raw,
                 amount, payout_phone, payout_method,
                 txn_date, txn_category, source_message_text,
                 accounting_period, is_reversal, reversed_txn_id, created_by)
            SELECT
                $1, fpe_wa_message_id, employee_id, employee_name_raw,
                -amount, payout_phone, payout_method,
                txn_date, txn_category,
                'REPAIR-REVERSAL: wrong employee — ' || COALESCE(source_message_text,''),
                accounting_period, TRUE, id, $2
            FROM fazle_cash_transactions WHERE id = $3
            RETURNING id
            """,
            reversal_ref,
            repaired_by,
            txn.txn_id,
        )
        log.info("  Created reversal id=%d for wrong txn %d", reversal_id, txn.txn_id)

    # ── b) New correct transaction ────────────────────────────────────────────
    new_txn_ref = _build_txn_ref(txn.fpe_wa_message_id, match.employee_id, txn.amount)
    existing_new = await conn.fetchrow(
        "SELECT id FROM fazle_cash_transactions WHERE txn_ref = $1",
        new_txn_ref,
    )
    if existing_new:
        new_txn_id = existing_new["id"]
        log.info("  Correct transaction already exists (id=%d), reusing.", new_txn_id)
    else:
        new_txn_id = await conn.fetchval(
            """
            INSERT INTO fazle_cash_transactions
                (txn_ref, fpe_wa_message_id, employee_id, employee_name_raw,
                 amount, payout_phone, payout_method,
                 txn_date, txn_category, source_message_text,
                 accounting_period, created_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            RETURNING id
            """,
            new_txn_ref,
            txn.fpe_wa_message_id,
            match.employee_id,
            txn.employee_name_raw,
            txn.amount,
            txn.payout_phone,
            txn.payout_method,
            txn.txn_date,
            "salary",
            f"REPAIR: corrected from emp {txn.current_employee_id} → {match.employee_id} | "
            + (txn.source_message_text or ""),
            txn.accounting_period,
            repaired_by,
        )
        log.info("  Created corrected txn id=%d for employee %d", new_txn_id, match.employee_id)

    # ── c) Audit row ──────────────────────────────────────────────────────────
    await conn.execute(
        """
        INSERT INTO fpe_transaction_repairs
            (transaction_id, old_employee_id, new_employee_id,
             old_employee_name, new_employee_name,
             repair_reason, match_method,
             reversal_txn_id, new_txn_id,
             review_needed, dry_run, repaired_by)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,FALSE,$10,$11)
        """,
        txn.txn_id,
        txn.current_employee_id, match.employee_id,
        txn.current_employee_name, match.employee_name,
        "; ".join(txn.suspicion_reasons),
        match.match_method,
        reversal_id, new_txn_id,
        dry_run,
        repaired_by,
    )

    # ── d) Ledger adjustments ─────────────────────────────────────────────────
    # Schema: opening_balance, total_earned, total_paid, total_advance,
    #         closing_balance, txn_count, last_updated
    period = txn.accounting_period
    if period:
        amount = float(txn.amount)
        # Debit old employee (reverse the paid amount)
        if txn.current_employee_id:
            await conn.execute(
                """
                INSERT INTO fazle_employee_ledger
                    (employee_id, accounting_period,
                     opening_balance, total_earned, total_paid, total_advance,
                     closing_balance, txn_count, last_updated)
                VALUES ($1, $2, 0, 0, -$3::numeric, 0, -$3::numeric, -1, now())
                ON CONFLICT (employee_id, accounting_period) DO UPDATE SET
                    total_paid      = fazle_employee_ledger.total_paid      - $3::numeric,
                    closing_balance = fazle_employee_ledger.closing_balance - $3::numeric,
                    txn_count       = fazle_employee_ledger.txn_count       - 1,
                    last_updated    = now()
                """,
                txn.current_employee_id, period, amount,
            )
        # Credit new employee
        await conn.execute(
            """
            INSERT INTO fazle_employee_ledger
                (employee_id, accounting_period,
                 opening_balance, total_earned, total_paid, total_advance,
                 closing_balance, txn_count, last_updated)
            VALUES ($1, $2, 0, 0, $3::numeric, 0, $3::numeric, 1, now())
            ON CONFLICT (employee_id, accounting_period) DO UPDATE SET
                total_paid      = fazle_employee_ledger.total_paid      + $3::numeric,
                closing_balance = fazle_employee_ledger.closing_balance + $3::numeric,
                txn_count       = fazle_employee_ledger.txn_count       + 1,
                last_updated    = now()
            """,
            match.employee_id, period, amount,
        )

    return {
        "action": "repaired",
        "txn_id": txn.txn_id,
        "old_employee": f"{txn.current_employee_id} / {txn.current_employee_name}",
        "new_employee": f"{match.employee_id} / {match.employee_name}",
        "match_method": match.match_method,
        "reversal_id": reversal_id,
        "new_txn_id": new_txn_id,
    }


# ── Output formatting ─────────────────────────────────────────────────────────

_RULE = "─" * 72

def _fmt_txn(txn: SuspiciousTxn, match: MatchResult, idx: int, total: int) -> str:
    lines = [
        _RULE,
        f"  [{idx}/{total}]  TXN #{txn.txn_id}  "
        f"৳{txn.amount}  {txn.payout_method or 'N/A'}  "
        f"period={txn.accounting_period or 'N/A'}",
        f"  Date         : {txn.txn_date}",
        f"  Raw name     : {txn.employee_name_raw or 'N/A'}",
        f"  Payout phone : {txn.payout_phone or 'NULL'}",
        "",
        f"  ▸ CURRENT employee  : id={txn.current_employee_id}  "
        f"name={txn.current_employee_name!r}  phone={txn.current_employee_phone!r}",
    ]

    if match.employee_id and match.employee_id != txn.current_employee_id:
        arrow = "✔" if match.confidence == "HIGH" else "⚠"
        lines.append(
            f"  ▸ SUGGESTED employee: id={match.employee_id}  "
            f"name={match.match_method!r} → {match.employee_name!r}  "
            f"confidence={match.confidence}  {arrow}"
        )
    elif match.confidence == "LOW" or match.review_needed:
        lines.append(f"  ▸ SUGGESTED employee: NONE — review required")
    else:
        lines.append(f"  ▸ SUGGESTED employee: same as current (already correct?)")

    if match.review_note:
        lines.append(f"  ▸ Note           : {match.review_note}")

    lines.append("")
    lines.append(f"  Suspicion flags ({len(txn.suspicion_reasons)}):")
    for r in txn.suspicion_reasons:
        lines.append(f"    • {r}")

    if txn.source_message_text:
        preview = txn.source_message_text[:120].replace("\n", " ")
        lines.append(f"  Message preview: {preview!r}")

    return "\n".join(lines)


def _print_summary(candidates: list[RepairCandidate], mode: str, dry_run: bool) -> None:
    tag = "[DRY-RUN] " if dry_run else ""
    print(f"\n{tag}Repair Report  —  mode={mode}  —  {len(candidates)} candidate(s)\n")
    for i, cand in enumerate(candidates, 1):
        print(_fmt_txn(cand.txn, cand.match, i, len(candidates)))
    print(_RULE)
    print(f"\n{tag}Summary:")
    high = sum(1 for c in candidates if c.match.confidence == "HIGH" and not c.match.review_needed)
    review = sum(1 for c in candidates if c.match.review_needed)
    same = sum(1 for c in candidates if c.match.employee_id == c.txn.current_employee_id)
    print(f"  Auto-repairable (HIGH confidence) : {high}")
    print(f"  Review required (LOW / MEDIUM)    : {review}")
    print(f"  Already correct (same employee)   : {same}")
    if mode == "preview":
        print("\nRun with --apply to execute corrections (HIGH confidence only).")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(args: argparse.Namespace) -> int:
    url = _resolve_db_url()
    conn: asyncpg.Connection = await asyncpg.connect(url)
    try:
        # Ensure audit table exists (idempotent DDL)
        await conn.execute(_AUDIT_TABLE_DDL)

        # Fetch suspicious transactions
        if args.transaction_id:
            rows = await conn.fetch(_SUSPICION_QUERY_SINGLE, args.transaction_id)
            if not rows:
                print(
                    f"Transaction #{args.transaction_id} not found, "
                    "is already reversed, or has already been repaired."
                )
                return 0
        else:
            rows = await conn.fetch(_SUSPICION_QUERY)

        if not rows:
            print("No suspicious transactions found — nothing to do.")
            return 0

        # Score each row
        candidates: list[RepairCandidate] = []
        for row in rows:
            row_dict = dict(row)
            reasons = _score_suspicion(row_dict)
            if not reasons:
                continue  # Not suspicious after all

            txn = SuspiciousTxn(
                txn_id=row_dict["txn_id"],
                txn_ref=row_dict["txn_ref"],
                current_employee_id=row_dict["current_employee_id"],
                current_employee_name=row_dict["current_employee_name"],
                current_employee_phone=row_dict["current_employee_phone"],
                employee_name_raw=row_dict["employee_name_raw"],
                # Use recovered phone (from source text) when stored payout_phone is null
                payout_phone=row_dict["payout_phone"] or row_dict.get("_recovered_phone"),
                payout_method=row_dict["payout_method"],
                amount=Decimal(str(row_dict["amount"])),
                txn_date=row_dict["txn_date"],
                accounting_period=row_dict["accounting_period"],
                fpe_wa_message_id=row_dict["fpe_wa_message_id"],
                source_message_text=row_dict["source_message_text"],
                parser_confidence=row_dict["parser_confidence"],
                suspicion_reasons=reasons,
            )
            match = await _find_correct_employee(
                conn,
                txn.payout_phone,
                txn.payout_method,
                txn.employee_name_raw,
            )
            candidates.append(RepairCandidate(txn=txn, match=match))

        if not candidates:
            print("All fetched transactions passed suspicion checks — nothing to repair.")
            return 0

        # Preview mode: just print, no writes
        if args.preview:
            _print_summary(candidates, mode="preview", dry_run=False)
            return 0

        # Apply mode (with or without --dry-run)
        _print_summary(candidates, mode="apply", dry_run=args.dry_run)

        results: list[dict] = []

        if args.dry_run:
            # Open a transaction, run all logic, then ROLLBACK
            tx = conn.transaction()
            await tx.start()
            try:
                for cand in candidates:
                    r = await _apply_repair(conn, cand, dry_run=True)
                    results.append(r)
            finally:
                await tx.rollback()
                log.info("[DRY-RUN] Transaction rolled back — no DB changes made.")
        else:
            # Real apply: each candidate in its own transaction for isolation
            for cand in candidates:
                if cand.match.confidence != _MIN_CONFIDENCE_FOR_AUTO_APPLY:
                    log.info(
                        "Skipping txn %d — confidence=%s (review required)",
                        cand.txn.txn_id, cand.match.confidence,
                    )
                    r = await _apply_repair(conn, cand, dry_run=False)
                    results.append(r)
                    continue
                if cand.match.employee_id == cand.txn.current_employee_id:
                    log.info("Txn %d already correct — skipping.", cand.txn.txn_id)
                    results.append({"action": "already_correct", "txn_id": cand.txn.txn_id})
                    continue
                tx = conn.transaction()
                await tx.start()
                try:
                    r = await _apply_repair(conn, cand, dry_run=False)
                    await tx.commit()
                    results.append(r)
                    log.info(
                        "✔  TXN %d repaired: emp %s → %s  (method=%s)",
                        cand.txn.txn_id,
                        cand.txn.current_employee_id,
                        cand.match.employee_id,
                        cand.match.match_method,
                    )
                except Exception as exc:
                    await tx.rollback()
                    log.error("✘  TXN %d repair FAILED — rolled back: %s", cand.txn.txn_id, exc)
                    results.append({"action": "failed", "txn_id": cand.txn.txn_id, "error": str(exc)})

        # Final report
        print("\n" + ("─" * 72))
        print(f"{'[DRY-RUN] ' if args.dry_run else ''}Results:")
        for r in results:
            action = r.get("action", "?")
            txn_id = r.get("txn_id", "?")
            if action == "repaired":
                print(f"  ✔  #{txn_id:<6} repaired  {r['old_employee']} → {r['new_employee']}  (rev={r['reversal_id']} new={r['new_txn_id']})")
            elif action == "review_needed":
                print(f"  ⚠  #{txn_id:<6} review_needed  {r.get('reason','')[:60]}")
            elif action == "already_correct":
                print(f"  –  #{txn_id:<6} already_correct (skipped)")
            elif action == "failed":
                print(f"  ✘  #{txn_id:<6} FAILED  {r.get('error','')[:80]}")
        print()

        return 0
    finally:
        await conn.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=dedent(__doc__ or ""),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preview", action="store_true",
        help="Read-only scan: show suspicious transactions and suggested corrections.",
    )
    mode.add_argument(
        "--apply", action="store_true",
        help="Execute corrections for HIGH-confidence matches only.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="With --apply: run all logic inside a single rolled-back transaction (no DB changes).",
    )
    parser.add_argument(
        "--transaction-id", type=int, default=None, metavar="ID",
        help="Limit scope to a single transaction ID.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(asyncio.run(main(args)))
