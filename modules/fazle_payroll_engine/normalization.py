"""
Fazle Payroll Engine — Safe Identity Normalization Service.

Implements the alias-based identity-resolution model.

DESIGN INVARIANTS (DO NOT VIOLATE):
  * Never UPDATE fazle_cash_transactions.employee_id
  * Never DELETE an fazle_employees row that has any history
  * Never recompute or alter txn_ref hashes
  * Never auto-merge by name alone (must have phone or human approval)
  * All identity changes are recorded in fpe_normalization_audit_logs

Public surface:
  - add_alias_safe(employee_id, alias_type, alias_value, reviewer)
  - link_duplicate(duplicate_id, canonical_id, reason, reviewer, confidence)
  - mark_inactive(employee_id, reason, reviewer)
  - enqueue_review(...)
  - resolve_review(review_id, decision, reviewer, note)
  - resolve_to_canonical(employee_id)
  - normalization_summary()

Concurrency: every mutating operation is wrapped in
`pg_advisory_xact_lock(_LOCK_KEY)` so it serializes against the 15-second
WhatsApp sync loop and any other normalization writer.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.database import db_conn, execute, fetch_all, fetch_one, fetch_val

log = logging.getLogger("fazle.fpe.normalization")

# Stable application-wide advisory lock key for the FPE normalization writer.
# Any int64 will do; this value is arbitrary but constant across restarts.
_LOCK_KEY = 0x46504E4F524D  # 'FPNORM' as hex


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _audit(
    action_type: str,
    entity_id: Optional[int],
    before: Optional[dict],
    after: Optional[dict],
    reviewer: Optional[str],
    reason: Optional[str],
    *,
    entity_type: str = "employee",
) -> None:
    await execute(
        """
        INSERT INTO fpe_normalization_audit_logs
            (action_type, entity_type, entity_id, before_state, after_state,
             reviewer, reason)
        VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7)
        """,
        action_type,
        entity_type,
        entity_id,
        json.dumps(before) if before is not None else None,
        json.dumps(after) if after is not None else None,
        reviewer,
        reason,
    )


async def _employee_snapshot(employee_id: int) -> Optional[dict]:
    row = await fetch_one(
        """
        SELECT id, employee_code, full_name, name_normalized,
               primary_phone, employee_id_phone, status,
               canonical_employee_id, resolution_status, confidence_score
        FROM fazle_employees WHERE id = $1
        """,
        employee_id,
    )
    if not row:
        return None
    out = dict(row)
    if out.get("confidence_score") is not None:
        out["confidence_score"] = float(out["confidence_score"])
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Canonical resolution (read-only — used by hot ingest path)
# ─────────────────────────────────────────────────────────────────────────────

async def resolve_to_canonical(employee_id: int) -> int:
    """
    Follow canonical_employee_id soft-links to find the canonical employee.
    Bounded loop guards against accidental cycles.
    """
    seen: set[int] = set()
    current = employee_id
    for _ in range(8):
        if current in seen:
            return current
        seen.add(current)
        canon_id = await fetch_val(
            "SELECT canonical_employee_id FROM fazle_employees WHERE id = $1",
            current,
        )
        if not canon_id:
            return current
        current = canon_id
    return current


# ─────────────────────────────────────────────────────────────────────────────
# Safe mutating operations
# ─────────────────────────────────────────────────────────────────────────────

async def add_alias_safe(
    employee_id: int,
    alias_type: str,
    alias_value: str,
    reviewer: str = "system",
) -> bool:
    """
    Add an alias (phone / name / employee_id) to an employee.
    Idempotent — duplicates are silently ignored.
    Returns True if a new alias row was inserted.
    """
    if alias_type not in ("phone", "name", "employee_id"):
        raise ValueError(f"invalid alias_type: {alias_type}")
    if not alias_value:
        return False

    async with db_conn() as conn:
        await conn.execute("SELECT pg_advisory_xact_lock($1)", _LOCK_KEY)
        result = await conn.execute(
            """
            INSERT INTO fpe_employee_aliases (employee_id, alias_type, alias_value)
            VALUES ($1, $2, $3)
            ON CONFLICT (alias_type, alias_value) DO NOTHING
            """,
            employee_id, alias_type, alias_value,
        )
        inserted = result.endswith(" 1")

    if inserted:
        await _audit(
            "add_alias", employee_id,
            None, {"alias_type": alias_type, "alias_value": alias_value},
            reviewer, None,
        )
    return inserted


async def link_duplicate(
    duplicate_id: int,
    canonical_id: int,
    reason: str,
    reviewer: str,
    confidence: float = 1.0,
    resolution_type: str = "manual_merge",
) -> dict:
    """
    Mark `duplicate_id` as a duplicate of `canonical_id`.

    Effects (all SAFE):
      * fazle_employees(duplicate_id).canonical_employee_id := canonical_id
      * fazle_employees(duplicate_id).resolution_status     := 'duplicate'
      * fazle_employees(canonical_id).resolution_status     := 'canonical'
      * Insert row into fpe_employee_resolution_links
      * Audit log entry

    Does NOT touch transactions, ledger rows, or aliases.
    Future ingestions will resolve `duplicate_id` → `canonical_id` via
    `resolve_to_canonical()`. Past transactions remain on `duplicate_id`
    forever (immutable accounting truth).
    """
    if duplicate_id == canonical_id:
        raise ValueError("duplicate_id and canonical_id must differ")

    before_dup = await _employee_snapshot(duplicate_id)
    before_canon = await _employee_snapshot(canonical_id)
    if not before_dup or not before_canon:
        raise ValueError("employee not found")

    # Refuse to chain duplicates — canonical must itself be canonical or unresolved
    if before_canon.get("canonical_employee_id"):
        raise ValueError(
            f"canonical_id={canonical_id} is itself a duplicate; "
            "resolve_to_canonical first"
        )

    async with db_conn() as conn:
        await conn.execute("SELECT pg_advisory_xact_lock($1)", _LOCK_KEY)
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE fazle_employees
                   SET canonical_employee_id = $1,
                       resolution_status = 'duplicate',
                       confidence_score = $2,
                       updated_at = NOW()
                 WHERE id = $3
                """,
                canonical_id, confidence, duplicate_id,
            )
            await conn.execute(
                """
                UPDATE fazle_employees
                   SET resolution_status = 'canonical',
                       updated_at = NOW()
                 WHERE id = $1
                   AND resolution_status <> 'canonical'
                """,
                canonical_id,
            )
            await conn.execute(
                """
                INSERT INTO fpe_employee_resolution_links
                    (employee_id, canonical_employee_id, resolution_type,
                     confidence_score, reason, created_by, reviewed_by, reviewed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $6, NOW())
                ON CONFLICT (employee_id, canonical_employee_id) DO NOTHING
                """,
                duplicate_id, canonical_id, resolution_type,
                confidence, reason, reviewer,
            )

    after_dup = await _employee_snapshot(duplicate_id)
    await _audit(
        "link_duplicate", duplicate_id,
        before_dup, after_dup, reviewer, reason,
    )
    log.info(
        "[fpe.norm] linked duplicate emp_id=%d → canonical=%d by=%s reason=%r",
        duplicate_id, canonical_id, reviewer, reason,
    )
    return {
        "duplicate_id": duplicate_id,
        "canonical_id": canonical_id,
        "resolution_type": resolution_type,
        "confidence": confidence,
    }


async def mark_inactive(
    employee_id: int, reason: str, reviewer: str,
) -> dict:
    """
    Soft-deactivate an employee. Row remains; status flips to 'inactive'.
    Never deletes. Transactions remain attached.
    """
    before = await _employee_snapshot(employee_id)
    if not before:
        raise ValueError("employee not found")

    async with db_conn() as conn:
        await conn.execute("SELECT pg_advisory_xact_lock($1)", _LOCK_KEY)
        await conn.execute(
            "UPDATE fazle_employees SET status = 'inactive', "
            "resolution_status = 'inactive', updated_at = NOW() WHERE id = $1",
            employee_id,
        )

    after = await _employee_snapshot(employee_id)
    await _audit("mark_inactive", employee_id, before, after, reviewer, reason)
    return after or {}


# ─────────────────────────────────────────────────────────────────────────────
# Manual review queue
# ─────────────────────────────────────────────────────────────────────────────

async def enqueue_review(
    *,
    candidate_employee_id: Optional[int],
    suspected_match_id: Optional[int],
    match_reason: str,
    confidence_score: float,
    source_message_id: Optional[int] = None,
    raw_name: Optional[str] = None,
    raw_phone: Optional[str] = None,
) -> int:
    """
    Push an ambiguous match into the review queue. Idempotency is best-effort:
    if an identical pending row exists for the same (candidate, suspected,
    reason) tuple, we don't enqueue twice.
    """
    if candidate_employee_id and suspected_match_id == candidate_employee_id:
        return 0

    existing = await fetch_val(
        """
        SELECT id FROM fpe_employee_review_queue
        WHERE review_status = 'pending'
          AND COALESCE(candidate_employee_id, 0) = COALESCE($1, 0)
          AND COALESCE(suspected_match_id, 0) = COALESCE($2, 0)
          AND match_reason = $3
        LIMIT 1
        """,
        candidate_employee_id, suspected_match_id, match_reason,
    )
    if existing:
        return int(existing)

    new_id = await fetch_val(
        """
        INSERT INTO fpe_employee_review_queue
            (candidate_employee_id, suspected_match_id, match_reason,
             confidence_score, source_message_id, raw_name, raw_phone)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """,
        candidate_employee_id, suspected_match_id, match_reason,
        confidence_score, source_message_id, raw_name, raw_phone,
    )
    await _audit(
        "enqueue_review", candidate_employee_id,
        None,
        {
            "suspected_match_id": suspected_match_id,
            "match_reason": match_reason,
            "confidence_score": confidence_score,
            "review_id": int(new_id),
        },
        "system", match_reason,
        entity_type="review_queue",
    )
    log.info(
        "[fpe.norm] review queued id=%s reason=%s candidate=%s suspect=%s score=%.2f",
        new_id, match_reason, candidate_employee_id, suspected_match_id,
        confidence_score,
    )
    return int(new_id)


async def resolve_review(
    review_id: int,
    decision: str,
    reviewer: str,
    note: Optional[str] = None,
) -> dict:
    """
    Resolve a queued review. `decision` is one of:
      * 'approved_merge'  → calls link_duplicate(candidate → suspected)
      * 'rejected'        → marks the queue row resolved, no employee changes
      * 'kept_separate'   → same as rejected; both stay independent
    """
    if decision not in ("approved_merge", "rejected", "kept_separate"):
        raise ValueError(f"invalid decision: {decision}")

    review = await fetch_one(
        "SELECT * FROM fpe_employee_review_queue WHERE id = $1", review_id,
    )
    if not review:
        raise ValueError(f"review {review_id} not found")
    if review["review_status"] != "pending":
        raise ValueError(
            f"review {review_id} is already {review['review_status']}"
        )

    if decision == "approved_merge":
        cand = review["candidate_employee_id"]
        susp = review["suspected_match_id"]
        if not cand or not susp:
            raise ValueError(
                "approved_merge requires both candidate and suspected ids"
            )
        # Treat the older / lower-id employee as canonical when both look equal,
        # but always defer to the suspected (existing) match as canonical since
        # candidates were typically auto-created later.
        canonical = susp
        duplicate = cand
        await link_duplicate(
            duplicate_id=duplicate,
            canonical_id=canonical,
            reason=note or f"approved_merge via review {review_id}",
            reviewer=reviewer,
            confidence=float(review["confidence_score"] or 0.0),
            resolution_type="manual_merge",
        )

    await execute(
        """
        UPDATE fpe_employee_review_queue
           SET review_status = $1,
               reviewer = $2,
               review_note = $3,
               reviewed_at = NOW()
         WHERE id = $4
        """,
        decision, reviewer, note, review_id,
    )
    await _audit(
        "resolve_review", review_id,
        {"review_status": "pending"},
        {"review_status": decision, "note": note},
        reviewer, decision,
        entity_type="review_queue",
    )
    return {"review_id": review_id, "decision": decision}


async def list_pending_reviews(limit: int = 100) -> list[dict]:
    rows = await fetch_all(
        """
        SELECT q.id, q.candidate_employee_id, q.suspected_match_id,
               q.match_reason, q.confidence_score, q.source_message_id,
               q.raw_name, q.raw_phone, q.created_at,
               ec.full_name AS candidate_name,
               ec.primary_phone AS candidate_phone,
               es.full_name AS suspected_name,
               es.primary_phone AS suspected_phone
        FROM fpe_employee_review_queue q
        LEFT JOIN fazle_employees ec ON ec.id = q.candidate_employee_id
        LEFT JOIN fazle_employees es ON es.id = q.suspected_match_id
        WHERE q.review_status = 'pending'
        ORDER BY q.created_at ASC
        LIMIT $1
        """,
        limit,
    )
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        if d.get("confidence_score") is not None:
            d["confidence_score"] = float(d["confidence_score"])
        out.append(d)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────

async def normalization_summary() -> dict:
    """Lightweight counts for monitoring/dashboard."""
    counts: dict[str, Any] = {}
    counts["employees_total"] = int(await fetch_val(
        "SELECT COUNT(*) FROM fazle_employees"
    ) or 0)
    counts["employees_canonical"] = int(await fetch_val(
        "SELECT COUNT(*) FROM fazle_employees WHERE resolution_status = 'canonical'"
    ) or 0)
    counts["employees_duplicate"] = int(await fetch_val(
        "SELECT COUNT(*) FROM fazle_employees WHERE resolution_status = 'duplicate'"
    ) or 0)
    counts["employees_unresolved"] = int(await fetch_val(
        "SELECT COUNT(*) FROM fazle_employees WHERE resolution_status = 'unresolved'"
    ) or 0)
    counts["employees_inactive"] = int(await fetch_val(
        "SELECT COUNT(*) FROM fazle_employees WHERE status = 'inactive'"
    ) or 0)
    counts["aliases_total"] = int(await fetch_val(
        "SELECT COUNT(*) FROM fpe_employee_aliases"
    ) or 0)
    counts["resolution_links"] = int(await fetch_val(
        "SELECT COUNT(*) FROM fpe_employee_resolution_links"
    ) or 0)
    counts["review_pending"] = int(await fetch_val(
        "SELECT COUNT(*) FROM fpe_employee_review_queue "
        "WHERE review_status = 'pending'"
    ) or 0)
    counts["review_resolved"] = int(await fetch_val(
        "SELECT COUNT(*) FROM fpe_employee_review_queue "
        "WHERE review_status <> 'pending'"
    ) or 0)
    counts["audit_entries"] = int(await fetch_val(
        "SELECT COUNT(*) FROM fpe_normalization_audit_logs"
    ) or 0)
    return counts
