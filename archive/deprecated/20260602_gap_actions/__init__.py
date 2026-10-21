# =============================================================================
# MODULE STATUS: DORMANT
# Date audited: 2026-06-01
# External callers: 0 (grep confirmed — only caller is gap_detector/__init__.py,
#   which is itself dormant with 0 external callers)
# Paired with: modules/gap_detector/ (this module is only ever called from gap_detector)
# Since gap_detector has 0 external callers, this module is also unreachable in production.
# DO NOT DELETE without explicit confirmation from Azim first.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.database import execute, fetch_one


@dataclass(frozen=True)
class GapActionInput:
    phone_number: str
    gap_duration: int
    last_message_direction: str
    role: str
    priority: int
    issue_type: str
    last_message_at: datetime


@dataclass(frozen=True)
class GapActionResult:
    gap_type: str
    cause: str
    risk_level: str
    recommended_actions: list[str]
    message_text: str
    draft_id: int
    urgency_score: int


def _role_group(role: str) -> str:
    value = (role or "").strip().lower()
    if value in {"accountant", "finance", "payment", "vendor"}:
        return "FINANCE"
    if value in {"employee", "supervisor", "candidate", "admin"}:
        return "EMPLOYEE"
    if value == "system":
        return "SYSTEM"
    return "CLIENT"


def _classify_gap(data: GapActionInput) -> str:
    issue = (data.issue_type or "").lower()
    if issue.startswith("system") or data.phone_number == "system":
        return "SYSTEM_DELAY"
    if issue == "reply_gap" or (data.last_message_direction or "").lower() == "outbound":
        return "NO_REPLY"
    if data.priority >= 90 or data.gap_duration >= 12 * 3600:
        return "HIGH_DELAY"
    return "NO_ACTIVITY"


def _urgency_score(data: GapActionInput, gap_type: str) -> int:
    score = min(100, max(10, int(data.gap_duration / 600)))
    if gap_type == "SYSTEM_DELAY":
        score = max(score, 95)
    elif gap_type == "NO_REPLY":
        score = max(score, 80)
    elif gap_type == "HIGH_DELAY":
        score = max(score, 85)
    else:
        score = max(score, 60)
    if data.priority:
        score = max(score, min(100, data.priority))
    return min(score, 100)


def _risk_level(score: int) -> str:
    if score >= 90:
        return "critical"
    if score >= 75:
        return "high"
    if score >= 60:
        return "medium"
    return "low"


def _cause(role_group: str, gap_type: str) -> str:
    if gap_type == "SYSTEM_DELAY":
        return "Bridge or DB ingest appears delayed and needs operator review."
    if role_group == "FINANCE":
        return "Financial follow-up is stalled or awaiting payment/status confirmation."
    if role_group == "EMPLOYEE":
        return "Operational follow-up is delayed and duty/activity status is unclear."
    return "Client-side follow-up is delayed and engagement may go cold."


def _recommended_actions(role_group: str, gap_type: str) -> list[str]:
    if gap_type == "SYSTEM_DELAY":
        return [
            "Check bridge health, recent DB inserts, and gap detector alerts.",
            "Verify the contact conversation in bridge export before replying.",
        ]
    if role_group == "FINANCE":
        return [
            "Ask for payment or ledger status on the last pending item.",
            "Verify whether any amount, slip, or settlement update is waiting.",
        ]
    if role_group == "EMPLOYEE":
        return [
            "Ask for current duty, attendance, or availability status.",
            "Check if a supervisor escalation is needed before closing the gap.",
        ]
    return [
        "Send a light engagement follow-up on the last open topic.",
        "Check whether a service, escort, or delivery update is still needed.",
    ]


def _draft_message(role_group: str, gap_type: str, phone_number: str) -> str:
    if gap_type == "SYSTEM_DELAY":
        return (
            "ভাই,\n\n"
            "আপনার মেসেজ দেরিতে পেয়েছি। বিষয়টি দেখা হচ্ছে।\n"
            "প্রয়োজনে আবার সংক্ষিপ্ত আপডেট দিন।"
        )
    if role_group == "FINANCE":
        return (
            "ভাই,\n\n"
            "আগের হিসাব বা পেমেন্ট বিষয়ে একটু আপডেট দিলে ভালো হয়।\n"
            "বাকিটার বর্তমান অবস্থা জানালে কাজ এগোবে।"
        )
    if role_group == "EMPLOYEE":
        return (
            "ভাই,\n\n"
            "আপনার বর্তমান ডিউটির অবস্থা জানাবেন?\n"
            "শিফট বা লোকেশন থাকলে সেটাও লিখে দিন।"
        )
    return (
        "ভাই, কী অবস্থা?\n\n"
        "আগের বার্তা দেখেছি। কোনো সাহায্য লাগলে জানাবেন।"
    )


async def _existing_draft_id(gap_subject: str) -> int | None:
    row = await fetch_one(
        """
        SELECT id
        FROM fazle_draft_replies
        WHERE draft_type = 'gap_action'
          AND COALESCE(status, 'pending') IN ('pending', 'approved')
          AND meta->>'gap_subject' = $1
        ORDER BY id DESC
        LIMIT 1
        """,
        gap_subject,
    )
    return int(row["id"]) if row else None


async def _pending_draft_for_recipient(recipient: str) -> int | None:
    """Return the ID of an existing pending gap_action draft for `recipient`
    if no new inbound message has arrived from that contact since the draft
    was created.  If a new message arrived, the old draft is stale and we
    should generate a fresh one.
    """
    row = await fetch_one(
        """
        SELECT d.id
        FROM fazle_draft_replies d
        WHERE d.draft_type = 'gap_action'
          AND d.recipient = $1
          AND COALESCE(d.status, 'pending') IN ('pending', 'approved')
          AND NOT EXISTS (
              SELECT 1
              FROM fazle_whatsapp_messages m
              WHERE m.canonical_phone = $1
                AND m.direction = 'inbound'
                AND m.received_at > d.created_at
          )
        ORDER BY d.id DESC
        LIMIT 1
        """,
        recipient,
    )
    return int(row["id"]) if row else None


async def _create_draft(*, recipient: str, message_text: str, gap_subject: str, gap_type: str, urgency_score: int, role: str, issue_type: str) -> int:
    # Guard 1: same gap_subject already has a draft (exact dedup)
    existing = await _existing_draft_id(gap_subject)
    if existing is not None:
        return existing
    # Guard 2: this contact already has a pending draft and sent no new message
    pending = await _pending_draft_for_recipient(recipient)
    if pending is not None:
        return pending
    row = await fetch_one(
        """
        INSERT INTO fazle_draft_replies
            (source, recipient, reply_text, intent, draft_only, reviewed, status, created_at, draft_type, meta)
        VALUES ('bridge2', $1, $2, 'gap_action', true, false, 'pending', NOW(), 'gap_action', $3::jsonb)
        RETURNING id
        """,
        recipient,
        message_text,
        json.dumps(
            {
                "gap_subject": gap_subject,
                "gap_type": gap_type,
                "urgency_score": urgency_score,
                "role": role,
                "issue_type": issue_type,
            },
            ensure_ascii=False,
        ),
    )
    return int(row["id"])


async def _log_gap_action(gap_subject: str, body: str, urgency_score: int) -> None:
    importance = 9 if urgency_score >= 90 else 6 if urgency_score >= 60 else 4
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await execute(
        """
        INSERT INTO agent.memory_notes (kind, subject, body, importance, created_at, expires_at)
        VALUES ('gap_action', $1, $2, $3, NOW(), $4)
        """,
        gap_subject,
        body,
        importance,
        expires_at,
    )


async def prepare_gap_action(data: GapActionInput, *, gap_subject: str) -> GapActionResult:
    role_group = _role_group(data.role)
    gap_type = _classify_gap(data)
    urgency_score = _urgency_score(data, gap_type)
    risk_level = _risk_level(urgency_score)
    cause = _cause(role_group, gap_type)
    recommended_actions = _recommended_actions(role_group, gap_type)
    # SYSTEM_DELAY is a bridge-health alert — no outbound draft should be created
    # (the alert itself is sent to admin via bridge1 by gap_detector._send_alert).
    if gap_type == "SYSTEM_DELAY":
        return GapActionResult(
            gap_type=gap_type,
            cause=cause,
            risk_level=risk_level,
            recommended_actions=recommended_actions,
            message_text="[system health alert — no draft]",
            draft_id=-1,
            urgency_score=urgency_score,
        )
    recipient = data.phone_number
    message_text = _draft_message(role_group, gap_type, recipient)
    draft_id = await _create_draft(
        recipient=recipient,
        message_text=message_text,
        gap_subject=gap_subject,
        gap_type=gap_type,
        urgency_score=urgency_score,
        role=data.role,
        issue_type=data.issue_type,
    )
    await _log_gap_action(
        gap_subject,
        json.dumps(
            {
                "phone_number": data.phone_number,
                "gap_type": gap_type,
                "risk_level": risk_level,
                "recommended_actions": recommended_actions,
                "draft_id": draft_id,
                "urgency_score": urgency_score,
            },
            ensure_ascii=False,
        ),
        urgency_score,
    )
    return GapActionResult(
        gap_type=gap_type,
        cause=cause,
        risk_level=risk_level,
        recommended_actions=recommended_actions,
        message_text=message_text,
        draft_id=draft_id,
        urgency_score=urgency_score,
    )