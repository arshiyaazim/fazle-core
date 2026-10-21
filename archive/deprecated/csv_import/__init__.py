"""
CSV Import — Batch 21
=====================
Bulk-insert employees, cash transactions, and attendance records
from uploaded CSV files.

Supported tables:
  - employees          → fazle_employees_legacy (upsert on employee_mobile)
  - cash_transactions  → fazle_cash_transactions_archive (append-only)
  - attendance         → wbom_attendance (upsert on employee_id + attendance_date)
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

from app.database import execute, fetch_val

log = logging.getLogger("fazle.csv_import")

# ── Required column sets per table ──────────────────────────────────────────

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "employees": {"employee_mobile", "employee_name", "designation"},
    "cash_transactions": {"employee_mobile", "transaction_type", "amount"},
    "attendance": {"employee_mobile", "attendance_date", "status"},
}

VALID_DESIGNATIONS = {"Escort", "Seal-man", "Security Guard", "Supervisor", "Labor"}
VALID_EMP_STATUSES = {"Active", "Inactive", "On Leave", "Terminated"}
VALID_TX_TYPES = {"Advance", "Food", "Conveyance", "Salary", "Deduction", "Other"}
VALID_PAYMENT_METHODS = {"Cash", "Bkash", "Nagad", "Rocket", "Bank"}
VALID_ATT_STATUSES = {"Present", "Absent", "Leave", "Half-day"}


# ── CSV parsing ──────────────────────────────────────────────────────────────

def parse_csv_bytes(data: bytes, table: str) -> tuple[list[dict], list[str]]:
    """Return (rows, errors). Validates headers and per-row required fields."""
    required = REQUIRED_COLUMNS.get(table)
    if required is None:
        return [], [f"Unknown table '{table}'. Supported: {sorted(REQUIRED_COLUMNS)}"]

    try:
        text = data.decode("utf-8-sig")  # handle BOM from Excel
    except UnicodeDecodeError:
        text = data.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return [], ["CSV file is empty or has no header row"]

    headers = {h.strip().lower() for h in reader.fieldnames}
    missing = required - headers
    if missing:
        return [], [f"Missing required columns: {sorted(missing)}"]

    rows: list[dict] = []
    errors: list[str] = []
    for i, raw_row in enumerate(reader, start=2):  # row 1 = header
        row = {k.strip().lower(): (v or "").strip() for k, v in raw_row.items() if k}
        row_errors = _validate_row(row, table, i)
        if row_errors:
            errors.extend(row_errors)
        else:
            rows.append(row)

    return rows, errors


def _validate_row(row: dict, table: str, line: int) -> list[str]:
    errs: list[str] = []
    mobile = row.get("employee_mobile", "")
    if not mobile:
        errs.append(f"Row {line}: employee_mobile is required")

    if table == "employees":
        desig = row.get("designation", "")
        if desig and desig not in VALID_DESIGNATIONS:
            errs.append(f"Row {line}: invalid designation '{desig}'. Must be one of {sorted(VALID_DESIGNATIONS)}")
        status = row.get("status", "")
        if status and status not in VALID_EMP_STATUSES:
            errs.append(f"Row {line}: invalid status '{status}'. Must be one of {sorted(VALID_EMP_STATUSES)}")

    elif table == "cash_transactions":
        tx_type = row.get("transaction_type", "")
        if tx_type and tx_type not in VALID_TX_TYPES:
            errs.append(f"Row {line}: invalid transaction_type '{tx_type}'")
        try:
            float(row.get("amount", ""))
        except ValueError:
            errs.append(f"Row {line}: amount must be numeric")
        pm = row.get("payment_method", "")
        if pm and pm not in VALID_PAYMENT_METHODS:
            errs.append(f"Row {line}: invalid payment_method '{pm}'")

    elif table == "attendance":
        att_status = row.get("status", "")
        if att_status and att_status not in VALID_ATT_STATUSES:
            errs.append(f"Row {line}: invalid attendance status '{att_status}'")

    return errs


# ── Per-table importers ──────────────────────────────────────────────────────

async def import_employees(rows: list[dict]) -> dict[str, Any]:
    inserted = updated = 0
    errors: list[str] = []

    for row in rows:
        try:
            existing = await fetch_val(
                "SELECT employee_id FROM fazle_employees_legacy WHERE employee_mobile = $1",
                row["employee_mobile"],
            )
            if existing:
                await execute(
                    """
                    UPDATE fazle_employees_legacy
                    SET employee_name = COALESCE(NULLIF($2,''), employee_name),
                        designation   = COALESCE(NULLIF($3,''), designation),
                        joining_date  = COALESCE(NULLIF($4,'')::date, joining_date),
                        status        = COALESCE(NULLIF($5,''), status),
                        bank_account  = COALESCE(NULLIF($6,''), bank_account),
                        emergency_contact = COALESCE(NULLIF($7,''), emergency_contact),
                        address       = COALESCE(NULLIF($8,''), address),
                        updated_at    = NOW()
                    WHERE employee_mobile = $1
                    """,
                    row["employee_mobile"],
                    row.get("employee_name", ""),
                    row.get("designation", ""),
                    row.get("joining_date", ""),
                    row.get("status", "Active"),
                    row.get("bank_account", ""),
                    row.get("emergency_contact", ""),
                    row.get("address", ""),
                )
                updated += 1
            else:
                await execute(
                    """
                    INSERT INTO fazle_employees_legacy
                        (employee_mobile, employee_name, designation, joining_date,
                         status, bank_account, emergency_contact, address)
                    VALUES ($1, $2, $3, NULLIF($4,'')::date, $5, NULLIF($6,''), NULLIF($7,''), NULLIF($8,''))
                    """,
                    row["employee_mobile"],
                    row["employee_name"],
                    row.get("designation", "Security Guard"),
                    row.get("joining_date", ""),
                    row.get("status", "Active"),
                    row.get("bank_account", ""),
                    row.get("emergency_contact", ""),
                    row.get("address", ""),
                )
                inserted += 1
        except Exception as e:
            errors.append(f"employee_mobile {row.get('employee_mobile')}: {e}")

    return {"inserted": inserted, "updated": updated, "errors": errors}


async def import_cash_transactions(rows: list[dict]) -> dict[str, Any]:
    inserted = 0
    errors: list[str] = []

    for row in rows:
        try:
            emp_id = await fetch_val(
                "SELECT employee_id FROM fazle_employees_legacy WHERE employee_mobile = $1",
                row["employee_mobile"],
            )
            if not emp_id:
                errors.append(f"employee_mobile {row['employee_mobile']}: employee not found — skipped")
                continue

            await execute(
                """
                INSERT INTO fazle_cash_transactions_archive
                    (employee_id, transaction_type, amount, payment_method,
                     payment_mobile, transaction_date, remarks, created_by)
                VALUES ($1, $2, $3::numeric, NULLIF($4,''), NULLIF($5,''),
                        COALESCE(NULLIF($6,'')::date, CURRENT_DATE), NULLIF($7,''), 'csv_import')
                """,
                emp_id,
                row.get("transaction_type", "Other"),
                row["amount"],
                row.get("payment_method", ""),
                row.get("payment_mobile", ""),
                row.get("transaction_date", ""),
                row.get("remarks", ""),
            )
            inserted += 1
        except Exception as e:
            errors.append(f"employee_mobile {row.get('employee_mobile')}: {e}")

    return {"inserted": inserted, "updated": 0, "errors": errors}


async def import_attendance(rows: list[dict]) -> dict[str, Any]:
    inserted = updated = 0
    errors: list[str] = []

    for row in rows:
        try:
            emp_id = await fetch_val(
                "SELECT employee_id FROM fazle_employees_legacy WHERE employee_mobile = $1",
                row["employee_mobile"],
            )
            if not emp_id:
                errors.append(f"employee_mobile {row['employee_mobile']}: employee not found — skipped")
                continue

            existing = await fetch_val(
                "SELECT attendance_id FROM wbom_attendance WHERE employee_id=$1 AND attendance_date=$2::date",
                emp_id,
                row["attendance_date"],
            )
            if existing:
                await execute(
                    """
                    UPDATE wbom_attendance
                    SET status = $3,
                        location = COALESCE(NULLIF($4,''), location),
                        check_in_time  = COALESCE(NULLIF($5,'')::timestamptz, check_in_time),
                        check_out_time = COALESCE(NULLIF($6,'')::timestamptz, check_out_time),
                        remarks = COALESCE(NULLIF($7,''), remarks),
                        recorded_by = 'csv_import'
                    WHERE employee_id=$1 AND attendance_date=$2::date
                    """,
                    emp_id,
                    row["attendance_date"],
                    row.get("status", "Present"),
                    row.get("location", ""),
                    row.get("check_in_time", ""),
                    row.get("check_out_time", ""),
                    row.get("remarks", ""),
                )
                updated += 1
            else:
                await execute(
                    """
                    INSERT INTO wbom_attendance
                        (employee_id, attendance_date, status, location,
                         check_in_time, check_out_time, remarks, recorded_by)
                    VALUES ($1, $2::date, $3, NULLIF($4,''),
                            NULLIF($5,'')::timestamptz, NULLIF($6,'')::timestamptz,
                            NULLIF($7,''), 'csv_import')
                    """,
                    emp_id,
                    row["attendance_date"],
                    row.get("status", "Present"),
                    row.get("location", ""),
                    row.get("check_in_time", ""),
                    row.get("check_out_time", ""),
                    row.get("remarks", ""),
                )
                inserted += 1
        except Exception as e:
            errors.append(f"employee_mobile {row.get('employee_mobile')} / {row.get('attendance_date')}: {e}")

    return {"inserted": inserted, "updated": updated, "errors": errors}


# ── Dispatcher ───────────────────────────────────────────────────────────────

_IMPORTERS = {
    "employees": import_employees,
    "cash_transactions": import_cash_transactions,
    "attendance": import_attendance,
}


async def run_import(data: bytes, table: str) -> dict[str, Any]:
    rows, parse_errors = parse_csv_bytes(data, table)
    if parse_errors and not rows:
        return {"table": table, "inserted": 0, "updated": 0, "errors": parse_errors}

    importer = _IMPORTERS[table]
    result = await importer(rows)
    result["table"] = table
    result["parse_errors"] = parse_errors  # row-level validation failures
    log.info(
        "csv_import table=%s inserted=%d updated=%d errors=%d",
        table, result["inserted"], result["updated"],
        len(result["errors"]) + len(parse_errors),
    )
    return result
