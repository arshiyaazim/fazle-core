"""
Fazle Core — Employee Utilities
Shared helpers for consistent employee identity resolution and auto-creation.

Rules:
  - Phone is the single source of truth for identity
  - normalize_phone() MUST be called before any DB lookup or insert
  - ON CONFLICT (employee_mobile) DO UPDATE keeps the canonical DB name
    (never overwrites with incoming message name)
"""
import logging
from typing import Optional

from app.database import fetch_val, fetch_one
from modules.user_role import normalize_phone

log = logging.getLogger("fazle.employee_utils")


async def get_or_create_employee(
    phone: str,
    fallback_name: str = "Unknown",
    designation: str = "Staff",
) -> Optional[int]:
    """
    Look up employee by normalised phone; auto-create if missing.
    Returns employee_id or None on failure.

    Safety guarantees:
      - normalize_phone() applied before every DB call
      - ON CONFLICT (employee_mobile) DO UPDATE preserves canonical name
        (COALESCE keeps existing DB name; only fills in if NULL)
      - Race-condition safe: uses upsert not separate check+insert
    """
    if not phone:
        return None

    norm = normalize_phone(phone)
    if not norm:
        log.warning(f"[employee_utils] could not normalize phone: {phone!r}")
        return None

    try:
        emp_id = await fetch_val(
            """INSERT INTO fazle_employees_legacy
                   (employee_name, employee_mobile, designation, status, joining_date)
               VALUES ($1, $2, $3, 'Active', CURRENT_DATE)
               ON CONFLICT (employee_mobile)
               DO UPDATE SET
                   employee_name = COALESCE(
                       fazle_employees_legacy.employee_name,
                       EXCLUDED.employee_name
                   )
               RETURNING employee_id""",
            fallback_name, norm, designation,
        )
        log.debug(f"[employee_utils] upsert phone={norm!r} → emp_id={emp_id}")
        return emp_id
    except Exception as e:
        log.error(f"[employee_utils] get_or_create_employee failed phone={norm!r}: {e}")
        return None


async def resolve_employee_id(
    phone: Optional[str] = None,
    name: Optional[str] = None,
) -> Optional[int]:
    """
    Look up employee by phone (preferred) or name (fallback).
    Does NOT auto-create. Returns None if not found.
    Used when you want to find without creating.
    """
    if phone:
        norm = normalize_phone(phone)
        if norm:
            row = await fetch_one(
                "SELECT employee_id FROM fazle_employees_legacy WHERE employee_mobile = $1",
                norm,
            )
            if row:
                return row["employee_id"]
            # Try 880-prefixed variant
            alt = "880" + norm[1:] if norm.startswith("0") else "0" + norm[3:]
            row = await fetch_one(
                "SELECT employee_id FROM fazle_employees_legacy WHERE employee_mobile = $1",
                alt,
            )
            if row:
                return row["employee_id"]

    if name:
        row = await fetch_one(
            """SELECT employee_id FROM fazle_employees_legacy
               WHERE LOWER(employee_name) LIKE LOWER($1)
                 AND status = 'Active'
               LIMIT 1""",
            f"%{name.split()[0]}%",
        )
        if row:
            return row["employee_id"]

    return None
