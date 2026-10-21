# =============================================================================
# MODULE STATUS: DORMANT
# Date audited: 2026-06-01
# External callers: 0 (grep confirmed — no import in app/, modules/, or service_runner.py)
# Paired with: modules/gap_actions/ (internally imported by this module only)
# GAP_SCAN_ENABLED: set to "true" in .env but no scheduler ever calls this module —
#   the env var is wired only inside this file itself; it has no effect in production.
# NOTE: fazle_payroll_engine/gap_scan.py is a SEPARATE gap scanner (FPE attendance).
# DO NOT DELETE without explicit confirmation from Azim first.
# =============================================================================
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from app.critical_numbers import CRITICAL_NUMBERS
from app.database import execute, fetch_all, fetch_one, fetch_val

log = logging.getLogger("fazle.gap_detector")

ALERT_TO = "8801880446111"
DAILY_REPORT_PATH = Path("/home/azim/core/reports/daily_gap_report.txt")


@dataclass(frozen=True)
class GapAlert:
    phone: str
    issue_type: str
    gap_seconds: int
    last_ts: datetime
    severity: str
    details: str = ""
    role: str = "unknown"
    last_message_direction: str = ""
    priority: int = 0
    last_message_text: str = ""  # last inbound message from the contact


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _gap_threshold_seconds(full_scan: bool) -> int:
    env_name = "GAP_DAILY_THRESHOLD_MINUTES" if full_scan else "GAP_HOURLY_THRESHOLD_MINUTES"
    default_minutes = "180" if full_scan else "120"
    return int(os.getenv(env_name, default_minutes)) * 60


def _reply_threshold_seconds(full_scan: bool) -> int:
    env_name = "GAP_REPLY_DAILY_THRESHOLD_MINUTES" if full_scan else "GAP_REPLY_THRESHOLD_MINUTES"
    default_minutes = "120" if full_scan else "60"
    return int(os.getenv(env_name, default_minutes)) * 60


def _lookback(full_scan: bool) -> timedelta:
    hours = int(os.getenv("GAP_DAILY_LOOKBACK_HOURS", "168") if full_scan else os.getenv("GAP_HOURLY_LOOKBACK_HOURS", "48"))
    return timedelta(hours=hours)


def _format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs and not parts:
        parts.append(f"{secs}s")
    return " ".join(parts) or "0s"


def _alert_importance(severity: str) -> int:
    return 9 if severity == "critical" else 6


def _alert_subject(alert: GapAlert) -> str:
    ts = alert.last_ts.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
    return f"gap_alert:{alert.issue_type}:{alert.phone}:{ts}"


def _alert_message(alert: GapAlert) -> str:
    base = (
        "🚨 GAP ALERT\n\n"
        f"Number: {alert.phone}\n"
        f"Gap: {_format_duration(alert.gap_seconds)}\n"
        f"Last Msg: {alert.last_ts.astimezone(timezone.utc).isoformat()}\n"
        f"Issue: {alert.issue_type}"
    )
    if alert.details:
        return f"{base}\nNote: {alert.details}"
    return base


def _action_required_message(alert: GapAlert, action: "GapActionResult") -> str:
    last_msg_section = ""
    if alert.last_message_text:
        last_msg_section = f'\nলাস্ট মেসেজ (তাদের):\n"{alert.last_message_text[:200]}"\n'

    # SYSTEM_DELAY: no draft created, no YES/CANCEL options
    if action.draft_id == -1:
        return (
            "⚠️ SYSTEM HEALTH ALERT\n\n"
            f"Type: {action.gap_type}\n"
            f"Cause: {action.cause}\n"
            f"Risk: {action.risk_level}\n"
            f"Number: {alert.phone}\n"
            f"Gap: {_format_duration(alert.gap_seconds)}\n"
            f"Note: {alert.details}"
        )

    # Existing pending draft — no new message since it was created
    if alert.last_message_text and action.draft_id > 0:
        pending_note = ""
    else:
        pending_note = ""

    return (
        "🚨 ACTION REQUIRED\n\n"
        f"Number: {alert.phone}\n"
        f"Gap: {_format_duration(alert.gap_seconds)}\n"
        f"Type: {action.gap_type}\n"
        f"Cause: {action.cause}\n"
        f"Risk: {action.risk_level}\n"
        f"Urgency: {action.urgency_score}"
        f"{last_msg_section}\n"
        f"Draft ID: {action.draft_id}\n"
        f"Draft reply:\n{action.message_text[:200]}\n\n"
        f"YES {action.draft_id}\n"
        f"EDIT {action.draft_id} <নতুন টেক্সট>\n"
        f"CANCEL {action.draft_id}"
    )


def _write_daily_report(*, summary: str, alerts: list[GapAlert], system_status: str) -> str:
    DAILY_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"Generated: {_now().astimezone(timezone.utc).isoformat()}",
        f"System status: {system_status}",
        "",
        summary,
        "",
        "Alerts:",
    ]
    if alerts:
        for alert in alerts:
            lines.extend([
                f"- Number: {alert.phone}",
                f"  Issue: {alert.issue_type}",
                f"  Gap: {_format_duration(alert.gap_seconds)}",
                f"  Last Msg: {alert.last_ts.astimezone(timezone.utc).isoformat()}",
                f"  Severity: {alert.severity}",
                f"  Note: {alert.details or '-'}",
            ])
    else:
        lines.append("- No gaps detected.")
    DAILY_REPORT_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return str(DAILY_REPORT_PATH)


async def _was_alerted_recently(subject: str, within_hours: int = 2) -> bool:
    row = await fetch_val(
        """
        SELECT 1
        FROM agent.memory_notes
        WHERE kind = 'gap_alert'
          AND subject = $1
          AND created_at >= NOW() - make_interval(hours => $2)
        LIMIT 1
        """,
        subject,
        within_hours,
    )
    return row is not None


async def _log_alert(subject: str, body: str, severity: str) -> None:
    expires_at = _now() + timedelta(hours=48)
    await execute(
        """
        INSERT INTO agent.memory_notes (kind, subject, body, importance, created_at, expires_at)
        VALUES ('gap_alert', $1, $2, $3, NOW(), $4)
        """,
        subject,
        body,
        _alert_importance(severity),
        expires_at,
    )


async def _send_via_mcp1(text: str) -> bool:
    """Send admin alert via bridge1 (8801958122300 → admin 8801880446111).

    Using bridge1 ensures the admin's WhatsApp reply arrives as is_from_me=0
    in bridge1's SQLite and gets picked up by the bridge1 poller for command
    processing.  Sending via bridge2 (the admin's own device) creates a
    self-chat where replies have is_from_me=1 and are silently skipped.
    """
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            "http://127.0.0.1:8200/send/mcp1",
            headers={"X-Internal-Key": settings.internal_api_key},
            json={"to": ALERT_TO, "text": text},
        )
        response.raise_for_status()
        data = response.json()
        return bool(data.get("sent"))


async def _send_via_mcp2(text: str) -> bool:
    """Send via bridge2 — kept for delivery to bridge2 contacts (not admin alerts)."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            "http://127.0.0.1:8200/send/mcp2",
            headers={"X-Internal-Key": settings.internal_api_key},
            json={"to": ALERT_TO, "text": text},
        )
        response.raise_for_status()
        data = response.json()
        return bool(data.get("sent"))


async def _is_contact_snoozed(phone: str) -> bool:
    """Return True if this phone has an active snooze or permanent ignore."""
    row = await fetch_val(
        """
        SELECT 1
        FROM agent.memory_notes
        WHERE kind = 'snooze_contact'
          AND subject = $1
          AND (expires_at IS NULL OR expires_at > NOW())
        LIMIT 1
        """,
        phone,
    )
    return row is not None


async def _send_alert(alert: GapAlert) -> bool:
    subject = _alert_subject(alert)
    if await _was_alerted_recently(subject):
        return False
    # Check if admin has snoozed/ignored this contact
    if await _is_contact_snoozed(alert.phone):
        log.info(f"[gap_detector] {alert.phone} is snoozed — skipping alert")
        return False
    from modules.gap_actions import GapActionInput, prepare_gap_action
    action = await prepare_gap_action(
        GapActionInput(
            phone_number=alert.phone,
            gap_duration=alert.gap_seconds,
            last_message_direction=alert.last_message_direction,
            role=alert.role,
            priority=alert.priority,
            issue_type=alert.issue_type,
            last_message_at=alert.last_ts,
        ),
        gap_subject=subject,
    )
    text = _action_required_message(alert, action)
    sent = False
    error_text = ""
    try:
        sent = await _send_via_mcp1(text)
    except Exception as exc:
        error_text = str(exc)
        log.warning(f"[gap_detector] alert send failed {subject}: {exc}")
    body = text if sent else f"{text}\nSendError: {error_text or 'bridge send returned false'}"
    await _log_alert(subject, body, alert.severity)
    return sent


async def _fetch_recent_messages(full_scan: bool) -> list[dict[str, Any]]:
    since = _now() - _lookback(full_scan)
    return await fetch_all(
        """
        SELECT canonical_phone,
               COALESCE(source_timestamp, received_at) AS event_ts,
               direction,
               COALESCE(message_body, '') AS body,
               platform,
               identity_role
        FROM fazle_whatsapp_messages
        WHERE canonical_phone = ANY($1::text[])
          AND COALESCE(source_timestamp, received_at) >= $2
        ORDER BY canonical_phone ASC, COALESCE(source_timestamp, received_at) ASC, message_id ASC
        """,
        list(CRITICAL_NUMBERS),
        since,
    )


async def _bridge_health_alert() -> GapAlert | None:
    # Only count INBOUND messages — outbound alerts written by this system should
    # not reset the "bridge is alive" clock.  Also exclude the system-alert text
    # itself in case it was accidentally stored as inbound.
    last_insert = await fetch_one(
        """
        SELECT MAX(received_at) AS last_insert
        FROM fazle_whatsapp_messages
        WHERE direction = 'inbound'
          AND message_body NOT LIKE '%SYSTEM HEALTH ALERT%'
        """
    )
    ts = last_insert.get("last_insert") if last_insert else None
    if not ts:
        return GapAlert(
            phone="system",
            issue_type="system_no_db_inserts",
            gap_seconds=999999,
            last_ts=_now(),
            severity="critical",
            details="No message rows found in fazle_whatsapp_messages.",
            role="system",
            last_message_direction="system",
            priority=100,
        )
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = _now() - ts
    # 60 minutes: a genuine gap worth alerting on (15 min was too sensitive for
    # quiet evenings / low-traffic periods).
    if delta > timedelta(minutes=60):
        return GapAlert(
            phone="system",
            issue_type="system_db_insert_stalled",
            gap_seconds=int(delta.total_seconds()),
            last_ts=ts,
            severity="critical",
            details=f"No inbound message for more than {int(delta.total_seconds()//60)} minutes.",
            role="system",
            last_message_direction="system",
            priority=100,
        )
    return None


def _group_by_phone(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {phone: [] for phone in CRITICAL_NUMBERS}
    for row in rows:
        phone = row.get("canonical_phone")
        if phone in grouped:
            grouped[phone].append(row)
    return grouped


def _scan_phone(rows: list[dict[str, Any]], full_scan: bool) -> list[GapAlert]:
    alerts: list[GapAlert] = []
    if not rows:
        return alerts
    gap_threshold = _gap_threshold_seconds(full_scan)
    reply_threshold = _reply_threshold_seconds(full_scan)
    latest_time_gap: GapAlert | None = None
    phone_role = next((str(r.get("identity_role") or "").strip() for r in reversed(rows) if r.get("identity_role")), "unknown")
    # Last inbound message text from the contact (for admin context in alerts)
    last_inbound_text = next(
        (str(r.get("body") or "").strip()[:200] for r in reversed(rows) if r.get("direction") == "inbound"),
        "",
    )

    for previous, current in zip(rows, rows[1:]):
        prev_ts = previous["event_ts"]
        curr_ts = current["event_ts"]
        if prev_ts.tzinfo is None:
            prev_ts = prev_ts.replace(tzinfo=timezone.utc)
        if curr_ts.tzinfo is None:
            curr_ts = curr_ts.replace(tzinfo=timezone.utc)
        delta = int((curr_ts - prev_ts).total_seconds())
        if delta > gap_threshold:
            severity = "critical" if delta > gap_threshold * 2 else "warning"
            latest_time_gap = GapAlert(
                phone=current["canonical_phone"],
                issue_type="time_gap",
                gap_seconds=delta,
                last_ts=curr_ts,
                severity=severity,
                details=f"Previous message at {prev_ts.astimezone(timezone.utc).isoformat()} via {previous.get('platform') or 'unknown'}.",
                role=phone_role,
                last_message_direction=current.get("direction") or "",
                priority=90 if severity == "critical" else 70,
                last_message_text=last_inbound_text,
            )

    if latest_time_gap is not None:
        alerts.append(latest_time_gap)

    last_row = rows[-1]
    last_ts = last_row["event_ts"]
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=timezone.utc)
    age = int((_now() - last_ts).total_seconds())
    if last_row.get("direction") == "outbound" and age > reply_threshold:
        severity = "critical" if age > reply_threshold * 2 else "warning"
        alerts.append(
            GapAlert(
                phone=last_row["canonical_phone"],
                issue_type="reply_gap",
                gap_seconds=age,
                last_ts=last_ts,
                severity=severity,
                details="Last message is outbound and no newer inbound has been recorded.",
                role=phone_role,
                last_message_direction=last_row.get("direction") or "",
                priority=95 if severity == "critical" else 75,
                last_message_text=last_inbound_text,
            )
        )
    return alerts


async def run_gap_scan(*, full_scan: bool = False, send_summary: bool = False) -> dict[str, Any]:
    # Kill-switch: GAP_SCAN_ENABLED=false disables all gap alerts and reports
    if os.getenv("GAP_SCAN_ENABLED", "true").strip().lower() in ("false", "0", "no"):
        log.info("[gap_detector] GAP_SCAN_ENABLED=false — scan skipped")
        return {"status": "disabled", "checked": 0, "alerts_found": 0,
                "warnings": 0, "critical_gaps": 0, "alerts_sent": 0,
                "system_status": "disabled", "report_path": None}
    rows = await _fetch_recent_messages(full_scan)
    grouped = _group_by_phone(rows)
    alerts: list[GapAlert] = []
    for phone, phone_rows in grouped.items():
        alerts.extend(_scan_phone(phone_rows, full_scan))

    system_alert = await _bridge_health_alert()
    if system_alert:
        alerts.append(system_alert)

    sent = 0
    warnings = 0
    criticals = 0
    for alert in alerts:
        if alert.severity == "critical":
            criticals += 1
        else:
            warnings += 1
        if await _send_alert(alert):
            sent += 1

    system_status = "critical" if system_alert else "ok"
    report_path = None
    if send_summary:
        summary = (
            "📊 DAILY GAP REPORT\n\n"
            f"Total checked: {len(CRITICAL_NUMBERS)}\n"
            f"Warnings: {warnings}\n"
            f"Critical gaps: {criticals}\n"
            f"System status: {system_status}"
        )
        report_path = _write_daily_report(summary=summary, alerts=alerts, system_status=system_status)
        subject = f"gap_alert:daily_summary:{_now().strftime('%Y%m%d')}"
        if not await _was_alerted_recently(subject, within_hours=20):
            ok = False
            error_text = ""
            try:
                ok = await _send_via_mcp1(summary)
            except Exception as exc:
                error_text = str(exc)
                log.warning(f"[gap_detector] daily summary send failed: {exc}")
            await _log_alert(subject, summary if ok else f"{summary}\nSendError: {error_text or 'bridge send returned false'}", "warning")
            if ok:
                sent += 1

    return {
        "status": "ok",
        "checked": len(CRITICAL_NUMBERS),
        "alerts_found": len(alerts),
        "warnings": warnings,
        "critical_gaps": criticals,
        "alerts_sent": sent,
        "system_status": system_status,
        "report_path": report_path,
    }


async def job_gap_scan_hourly() -> dict[str, Any]:
    return await run_gap_scan(full_scan=False, send_summary=False)


async def job_gap_scan_daily() -> dict[str, Any]:
    return await run_gap_scan(full_scan=True, send_summary=True)