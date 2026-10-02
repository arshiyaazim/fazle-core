"""Read-only operational context for the Vessel Register integration.

This module deliberately reads Fazle Core's canonical PostgreSQL records. It
does not call the Site, write a database row, create a draft, enqueue a
message, or post to a ledger. The Site's `/api/core` proxy consumes the same
canonical read contract through the scoped FPE routes.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

log = logging.getLogger("fazle.vessel_register_context")

_OPERATIONAL_HINTS = (
    "vessel", "mv ", "m.v", "lighter", "জাহাজ", "লাইটার", "escort",
    "ডিউটি", "দায়িত্ব", "দায়িত্ব", "destination", "গন্তব্য", "release",
    "রিলিজ", "shift", "শিফট",
)
_SAFE_TEMPLATE_FIELDS = frozenset({
    "vessel", "lighter", "destination", "shift", "start_date", "end_date",
    "status", "employee", "reference", "missing_fields",
})


def is_operational_message(text: str) -> bool:
    value = (text or "").strip().lower()
    return bool(value) and any(hint in value for hint in _OPERATIONAL_HINTS)


def _search_terms(text: str) -> list[str]:
    """Return bounded, non-secret search fragments for parameterized SQL."""
    raw = re.findall(r"[\w\u0980-\u09ff][\w\u0980-\u09ff._/-]{1,63}", text or "", re.UNICODE)
    stopwords = {
        "vessel", "lighter", "destination", "escort", "release", "shift",
        "জাহাজ", "লাইটার", "গন্তব্য", "ডিউটি", "দায়িত্ব", "দায়িত্ব",
        "রিলিজ", "শিফট",
    }
    terms: list[str] = []
    for item in raw:
        item = item.strip(" ._/-")
        if len(item) >= 3 and item.lower() not in stopwords and item.lower() not in {t.lower() for t in terms}:
            terms.append(item[:64])
    return terms[:5]


async def build_operational_context(*, text: str, sender_phone: str = "") -> str:
    """Build a small, safe context package from Core's canonical records.

    Ambiguous matches are omitted rather than guessed. Phone matching is used
    only for the sender's own employee/escort row; it is never treated as a
    payout or employee-merge instruction.
    """
    from app.config import get_settings
    from app.database import fetch_all
    settings = get_settings()
    if not settings.vessel_register_context_enabled or not is_operational_message(text):
        return ""

    terms = _search_terms(text)
    rows: list[dict[str, Any]] = []
    try:
        # Search only canonical operational fields. Do not select phone,
        # salary, payout, or raw message columns into an AI context.
        for term in terms:
            rows.extend(await asyncio.wait_for(
                fetch_all(
                    """SELECT program_id, mother_vessel, lighter_vessel,
                              destination, program_date AS start_date,
                              end_date, shift AS start_shift, end_shift, status
                         FROM wbom_escort_programs
                        WHERE LOWER(COALESCE(mother_vessel, '')) LIKE LOWER($1)
                           OR LOWER(COALESCE(lighter_vessel, '')) LIKE LOWER($1)
                           OR LOWER(COALESCE(destination, '')) LIKE LOWER($1)
                        ORDER BY start_date DESC NULLS LAST, program_id DESC
                        LIMIT 6""",
                    f"%{term}%",
                ),
                timeout=settings.vessel_register_context_timeout_seconds,
            ))
            if len(rows) >= 6:
                break
    except Exception as exc:  # schema/runtime failure must not block messaging
        log.debug("operational context unavailable: %s", exc)
        return ""

    # Deduplicate and suppress ambiguous multi-record matches. A context with
    # several unrelated programs is less safe than asking for clarification.
    unique: dict[Any, dict[str, Any]] = {row.get("program_id"): row for row in rows if row.get("program_id") is not None}
    if not unique:
        return (
            "Operational context review_required=true; "
            "reason=unresolved_vessel_or_voyage; no assignment selected."
        )
    if len(unique) > 3:
        return (
            "Operational context review_required=true; "
            "reason=ambiguous_vessel_or_voyage_match; no assignment selected."
        )

    lines = ["Operational context (Core canonical records; read-only):"]
    if len(unique) > 1:
        lines.append(
            "- review_required=true; reason=multiple_voyage_matches; "
            "no assignment selected."
        )
    for row in unique.values():
        missing_schedule = [
            field for field in ("start_date", "end_date", "start_shift", "end_shift")
            if not row.get(field)
        ]
        if missing_schedule:
            lines.append(
                "- review_required=true; reason=missing_schedule_fields; "
                f"fields={','.join(missing_schedule)}; no assignment selected."
            )
        lines.append(
            "- program_id={program_id}; mother_vessel={mother_vessel}; "
            "lighter_vessel={lighter_vessel}; destination={destination}; "
            "start_date={start_date}; end_date={end_date}; start_shift={start_shift}; "
            "end_shift={end_shift}; status={status}".format(
                program_id=row.get("program_id"),
                mother_vessel=row.get("mother_vessel") or "",
                lighter_vessel=row.get("lighter_vessel") or "",
                destination=row.get("destination") or "",
                start_date=row.get("start_date") or "",
                end_date=row.get("end_date") or "",
                start_shift=row.get("start_shift") or "",
                end_shift=row.get("end_shift") or "",
                status=row.get("status") or "",
            )
        )
    return "\n".join(lines)


def render_draft_preview(template_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Render a non-sending preview; no database or outbound side effect."""
    safe = {key: str(value).strip() for key, value in fields.items() if key in _SAFE_TEMPLATE_FIELDS and value is not None}
    missing = [field for field in ("vessel", "destination", "shift") if not safe.get(field)]
    if template_id == "escort_assignment_confirmation":
        body = (
            "Escort assignment draft\n"
            f"Vessel: {safe.get('vessel', '—')}\n"
            f"Destination: {safe.get('destination', '—')}\n"
            f"Shift: {safe.get('shift', '—')}\n"
            f"Status: {safe.get('status', 'pending review')}"
        )
    elif template_id == "missing_operational_information":
        body = "অনুগ্রহ করে নিশ্চিত করুন: " + ", ".join(missing or ["প্রয়োজনীয় তথ্য"])
    else:
        raise ValueError("unsupported template")
    return {
        "template_id": template_id,
        "draft_only": True,
        "approved": False,
        "sent": False,
        "posted": False,
        "missing_fields": missing,
        "body": body,
    }


__all__ = ["build_operational_context", "is_operational_message", "render_draft_preview"]
