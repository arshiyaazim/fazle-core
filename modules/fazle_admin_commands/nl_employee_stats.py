"""
Fazle Core — Admin NL: employee stats handler

Queries fazle_employees_legacy for headcount, list, and breakdown.
No writes. No LLM.

Public:
    is_employee_stats_query(text) -> bool
    intent_employee_stats(text, admin_phone) -> str

Triggers:
    how many employees / কতজন কর্মী আছে
    মোট কর্মী সংখ্যা / employee count / total staff
    active employees / কর্মীর তালিকা / employee list
    designation breakdown / কোন পদে কতজন
"""
from __future__ import annotations

import logging
import re

from app.database import fetch_all, fetch_val

log = logging.getLogger("fazle.admin_nl_empstats")

# ── Trigger patterns ──────────────────────────────────────────────────────────
_STATS_RE = re.compile(
    r"\b(how many|how much|কতজন|কত\s*জন|মোট\s*কর্মী|কর্মী\s*সংখ্যা"
    r"|employee\s*count|staff\s*count|total\s*staff|total\s*employee"
    r"|employee\s*list|কর্মীর\s*তালিকা|কর্মী\s*তালিকা"
    r"|designation\s*breakdown|পদ\s*অনুযায়ী|কোন\s*পদে)\b",
    re.IGNORECASE | re.UNICODE,
)

_SUBJECT_RE = re.compile(
    r"\b(employee|employees|staff|কর্মী|কর্মীরা|সদস্য|লোক)\b",
    re.IGNORECASE | re.UNICODE,
)

_LIST_RE = re.compile(
    r"\b(list|তালিকা|নাম|names?|show all|সব\s*কর্মী|সকল\s*কর্মী)\b",
    re.IGNORECASE | re.UNICODE,
)

_DESIGNATION_RE = re.compile(
    r"\b(designation|পদ|পদবি|post|role|breakdown)\b",
    re.IGNORECASE | re.UNICODE,
)

# Standalone Bengali headcount phrases (no \b needed — full Bengali phrases)
_BN_HEADCOUNT_RE = re.compile(
    r"মোট\s*কর্মী|কর্মী\s*সংখ্যা|কর্মীর\s*তালিকা|কর্মী\s*তালিকা"
    r"|কোন\s*পদে|পদ\s*অনুযায়ী",
    re.UNICODE,
)

_ACTIVE_ONLY_RE = re.compile(r"\bactive\b|\bসক্রিয়\b", re.IGNORECASE | re.UNICODE)
_INACTIVE_ONLY_RE = re.compile(r"\binactive\b|\bনিষ্ক্রিয়\b", re.IGNORECASE | re.UNICODE)


def is_employee_stats_query(text: str) -> bool:
    # Standalone Bengali headcount phrases (no subject word needed)
    if _BN_HEADCOUNT_RE.search(text):
        return True
    # Standalone "designation breakdown" / "designation" without payment context
    if _DESIGNATION_RE.search(text) and not re.search(
        r"\b(payment|salary|advance|cash|transaction)\b", text, re.IGNORECASE
    ):
        return True
    if _STATS_RE.search(text):
        if _SUBJECT_RE.search(text) or re.search(r"কর্মী|employee|staff", text, re.IGNORECASE | re.UNICODE):
            return True
    # "active employees" / "inactive employees" — adjective + subject word
    if re.search(r"\b(active|inactive)\b", text, re.IGNORECASE) and re.search(
        r"\b(employees?|staff|কর্মী)\b", text, re.IGNORECASE | re.UNICODE
    ):
        return True
    # "employee list" / "কর্মীর তালিকা" standalone
    if _LIST_RE.search(text) and _SUBJECT_RE.search(text):
        return True
    return False


async def intent_employee_stats(text: str, admin_phone: str) -> str:
    want_list = bool(_LIST_RE.search(text))
    want_desig = bool(_DESIGNATION_RE.search(text))
    active_filter = (
        "Active" if _ACTIVE_ONLY_RE.search(text) else
        "Inactive" if _INACTIVE_ONLY_RE.search(text) else
        None
    )

    # ── Headcount by status ───────────────────────────────────────────────────
    status_rows = await fetch_all(
        "SELECT COALESCE(status, 'Active') AS status, COUNT(*) AS cnt "
        "FROM fazle_employees_legacy GROUP BY COALESCE(status, 'Active') ORDER BY cnt DESC"
    )
    total = sum(int(r["cnt"]) for r in status_rows)
    status_summary = " · ".join(f"{r['status']}: {r['cnt']}" for r in status_rows)

    header = f"👥 মোট কর্মী: {total}\n   {status_summary}"

    # ── Designation breakdown ─────────────────────────────────────────────────
    if want_desig or (not want_list and not _STATS_RE.search(text)):
        desig_rows = await fetch_all(
            "SELECT COALESCE(designation, 'N/A') AS designation, "
            "COUNT(*) AS cnt "
            "FROM fazle_employees_legacy "
            + (f"WHERE LOWER(status) = LOWER('{active_filter}') " if active_filter else "")
            + "GROUP BY COALESCE(designation, 'N/A') ORDER BY cnt DESC LIMIT 20"
        )
        if desig_rows:
            lines = [f"  • {r['designation']}: {r['cnt']}" for r in desig_rows]
            header += "\n\n📋 পদ অনুযায়ী:\n" + "\n".join(lines)

    # ── Employee list ─────────────────────────────────────────────────────────
    if want_list:
        where = ""
        if active_filter:
            where = f"WHERE LOWER(status) = LOWER('{active_filter}') "
        emp_rows = await fetch_all(
            f"SELECT employee_name, employee_mobile, designation "
            f"FROM fazle_employees_legacy {where}"
            f"ORDER BY employee_name ASC LIMIT 50"
        )
        if not emp_rows:
            return header + "\n\n📭 কোনো কর্মী পাওয়া যায়নি।"

        lines = []
        for i, r in enumerate(emp_rows, 1):
            desig = f" [{r['designation']}]" if r.get("designation") else ""
            lines.append(f"{i:>3}. {r['employee_name']} — {r['employee_mobile']}{desig}")

        overflow = f"\n  … আরো {total - 50}জন" if total > 50 else ""
        header += "\n\n" + "\n".join(lines) + overflow

    return header
