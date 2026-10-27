"""
Fazle Core — Payroll & Payment Logic (Phase 4G)

Answers employee questions about salary, payments, duty count.
Uses: fazle_cash_transactions, fazle_employees_legacy, wbom_escort_programs, wbom_salary_records

NEVER fabricates amounts. If data is missing → returns under_review=True.
"""

import logging
from datetime import date, timedelta
from typing import TypedDict, Optional
from decimal import Decimal

from app.database import fetch_one, fetch_all, fetch_val

log = logging.getLogger("fazle.payroll")


class PayrollSummary(TypedDict):
    employee_id: int
    employee_name: str
    basic_salary: Optional[float]
    designation: Optional[str]

    # Payments this month
    paid_this_month: float
    payment_count_this_month: int

    # Last payment
    last_payment_amount: Optional[float]
    last_payment_date: Optional[str]
    last_payment_method: Optional[str]

    # Duty/program stats (last 30 days)
    duty_count_30d: int
    active_duties: int

    # Totals (all time)
    total_paid_ever: float

    # Status
    under_review: bool
    notes: str


async def get_payroll_summary(employee_id: int) -> PayrollSummary:
    """
    Fetch full payroll picture for an employee.
    Used by reply engine to answer 'টাকা কত?' / 'কবে পাবো?' questions.
    """
    today = date.today()
    month_start = today.replace(day=1)

    # Employee base info
    emp = await fetch_one(
        """SELECT employee_id, employee_name, designation, basic_salary, status
           FROM fazle_employees_legacy WHERE employee_id = $1""",
        employee_id,
    )
    if not emp:
        return _empty_summary(employee_id)

    # C1B: Payments this month from canonical fazle_cash_transactions.
    # fazle_cash_transactions.employee_id FKs to fazle_employees(id), not the
    # WBOM employee_id used everywhere else in this function -- same
    # cross-system ID bug fixed in compute_run() (2026-07-18). Resolve the
    # linked, active fazle_employees row first; no link -> no payment history
    # (matches this function's existing "missing data -> under_review=True"
    # contract, not an error).
    fpe_link = await fetch_one(
        "SELECT id FROM fazle_employees WHERE wbom_employee_id=$1 AND status='active'",
        employee_id,
    )
    fpe_id = fpe_link["id"] if fpe_link else None

    if fpe_id is not None:
        month_txns = await fetch_all(
            """SELECT amount, payout_method, txn_date, transaction_status
               FROM fazle_cash_transactions
               WHERE employee_id = $1
                 AND txn_date >= $2
                 AND transaction_status = 'final'
               ORDER BY txn_date DESC""",
            fpe_id, month_start,
        )
        last_txn = await fetch_one(
            """SELECT amount, payout_method, txn_date
               FROM fazle_cash_transactions
               WHERE employee_id = $1
                 AND transaction_status = 'final'
               ORDER BY txn_date DESC
               LIMIT 1""",
            fpe_id,
        )
        total_paid = await fetch_val(
            "SELECT COALESCE(SUM(amount), 0) FROM fazle_cash_transactions "
            "WHERE employee_id = $1 AND transaction_status = 'final'",
            fpe_id,
        )
    else:
        month_txns = []
        last_txn = None
        total_paid = 0

    paid_this_month = sum(
        float(r["amount"]) for r in month_txns if r["amount"]
    )

    # Duty count last 30 days
    thirty_ago = today - timedelta(days=30)
    duty_count = await fetch_val(
        """SELECT COUNT(*) FROM wbom_escort_programs
           WHERE escort_employee_id = $1
             AND program_date >= $2""",
        employee_id, thirty_ago,
    )

    # Active (ongoing) duties
    active_duties = await fetch_val(
        """SELECT COUNT(*) FROM wbom_escort_programs
           WHERE escort_employee_id = $1
             AND status NOT IN ('completed', 'cancelled', 'escort_changed')""",
        employee_id,
    )

    # Check salary_records for current month.
    #
    # These column names must match production `wbom_salary_records` as captured
    # by migration 029 (a pg_dump of the live database) — the authoritative
    # definition for this table. Two things differ from what this query used to
    # assume:
    #   * the period is stored as TWO integer columns, `month` + `year`
    #     (UNIQUE (employee_id, month, year)), NOT a single `salary_month`
    #     'YYYY-MM' text column;
    #   * the money/status columns are `net_salary` / `payment_status`,
    #     not `amount` / `status`.
    # The previous query selected `amount`, `status` and `salary_month`, none of
    # which exist in production, so it raised UndefinedColumnError on every
    # call. The error was swallowed upstream, so this lookup always returned
    # nothing and every payroll summary silently degraded to
    # "under_review / পর্যালোচনাধীন" instead of reporting the real salary state.
    salary_rec = await fetch_one(
        """SELECT salary_id, net_salary, payment_status, payment_date
           FROM wbom_salary_records
          WHERE employee_id = $1 AND month = $2 AND year = $3""",
        employee_id, month_start.month, month_start.year,
    )

    # Determine if under review
    has_data = (paid_this_month > 0 or total_paid > 0 or
                (emp.get("basic_salary") and float(emp["basic_salary"]) > 0))
    under_review = not has_data

    notes_parts = []
    if salary_rec:
        # Production's column default is 'Pending' (capitalised) and nothing
        # normalises it on write, so compare case-insensitively instead of
        # assuming a lower-case convention the data does not follow.
        status = (salary_rec.get("payment_status") or "").strip().lower()
        if status == "paid":
            notes_parts.append(f"এই মাসের বেতন পরিশোধিত হয়েছে {salary_rec['payment_date']}")
        elif status == "pending":
            notes_parts.append("এই মাসের বেতন প্রক্রিয়াধীন")
    if active_duties:
        notes_parts.append(f"বর্তমানে {active_duties}টি ডিউটি চলছে")

    return PayrollSummary(
        employee_id=employee_id,
        employee_name=emp["employee_name"],
        basic_salary=float(emp["basic_salary"]) if emp.get("basic_salary") else None,
        designation=emp.get("designation"),
        paid_this_month=paid_this_month,
        payment_count_this_month=len(month_txns),
        last_payment_amount=float(last_txn["amount"]) if last_txn and last_txn["amount"] else None,
        last_payment_date=str(last_txn["txn_date"]) if last_txn else None,
        last_payment_method=last_txn.get("payout_method") if last_txn else None,
        duty_count_30d=int(duty_count or 0),
        active_duties=int(active_duties or 0),
        total_paid_ever=float(total_paid or 0),
        under_review=under_review,
        notes=" | ".join(notes_parts),
    )


def format_payroll_context(s: PayrollSummary) -> str:
    """
    Format payroll summary as readable context for Ollama prompt injection.
    """
    lines = []
    lines.append(f"কর্মীর নাম: {s['employee_name']}")
    if s.get("designation"):
        lines.append(f"পদ: {s['designation']}")
    if s.get("basic_salary") and s["basic_salary"] > 0:
        lines.append(f"মূল বেতন: ৳{s['basic_salary']:,.0f}")

    if s["paid_this_month"] > 0:
        lines.append(f"এই মাসে পেমেন্ট: ৳{s['paid_this_month']:,.0f} ({s['payment_count_this_month']}বার)")
    else:
        lines.append("এই মাসে পেমেন্টের তথ্য নেই")

    if s.get("last_payment_amount") and s["last_payment_amount"] > 0:
        method = s.get("last_payment_method") or ""
        lines.append(f"সর্বশেষ পেমেন্ট: ৳{s['last_payment_amount']:,.0f} ({s['last_payment_date']}){' — '+method if method else ''}")

    if s["duty_count_30d"]:
        lines.append(f"গত ৩০ দিনে ডিউটি: {s['duty_count_30d']}টি")
    if s["active_duties"]:
        lines.append(f"চলমান ডিউটি: {s['active_duties']}টি")

    if s["under_review"]:
        lines.append("⚠️ পেমেন্ট বিস্তারিত পর্যালোচনাধীন")
    if s.get("notes"):
        lines.append(s["notes"])

    return "\n".join(lines)


def _empty_summary(employee_id: int) -> PayrollSummary:
    return PayrollSummary(
        employee_id=employee_id,
        employee_name="?",
        basic_salary=None,
        designation=None,
        paid_this_month=0.0,
        payment_count_this_month=0,
        last_payment_amount=None,
        last_payment_date=None,
        last_payment_method=None,
        duty_count_30d=0,
        active_duties=0,
        total_paid_ever=0.0,
        under_review=True,
        notes="",
    )
