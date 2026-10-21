"""
shared.consistency — DB Write Consistency Wrappers (Phase 12E)
==============================================================

Provides optimistic-version checks and double-commit prevention for
critical tables (employees, payments, escort programs).

How optimistic locking works
----------------------------
1. Before writing, the caller reads the current `updated_at` (or `version`)
   from the DB.
2. The actual write includes `WHERE id=$x AND updated_at=$expected`.
3. If another worker updated the row between read and write, the UPDATE
   affects 0 rows → OptimisticLockError is raised.
4. The caller can retry with a fresh read.

Double-commit prevention
------------------------
`assert_not_duplicate(table, idempotency_key)` raises DuplicateWriteError
if a row with that idempotency key already exists.  Use this for payment
ingestion where the bridge might retry the same message.

USAGE
-----
    from shared.consistency import (
        optimistic_update,
        assert_not_duplicate,
        OptimisticLockError,
        DuplicateWriteError,
    )

    # Optimistic update
    try:
        rows_affected = await optimistic_update(
            conn=ctx.conn,
            table="fazle_employees_legacy",
            pk_col="employee_id",
            pk_val=employee_id,
            updates={"salary": 28000},
            version_col="updated_at",
            expected_version=seen_at,
        )
    except OptimisticLockError:
        # Row was updated by another worker — retry from fresh read
        raise

    # Duplicate check before inserting payment
    await assert_not_duplicate(conn, "fazle_cash_transactions", txn_ref)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

log = logging.getLogger("fazle.consistency")


# ── Custom exceptions ─────────────────────────────────────────────────────────

class OptimisticLockError(Exception):
    """Raised when an optimistic update finds a row modified by another writer."""
    def __init__(self, table: str, pk_val: Any, expected: Any, actual: Any = None):
        self.table = table
        self.pk_val = pk_val
        self.expected = expected
        self.actual = actual
        msg = (
            f"Optimistic lock conflict on {table} pk={pk_val}: "
            f"expected version={expected}, row was already modified"
        )
        super().__init__(msg)


class DuplicateWriteError(Exception):
    """Raised when a duplicate idempotency key is detected before insert."""
    def __init__(self, table: str, key: str):
        self.table = table
        self.key = key
        super().__init__(f"Duplicate write detected: table={table} key={key}")


# ── Optimistic update ─────────────────────────────────────────────────────────

async def optimistic_update(
    conn: Any,                         # asyncpg.Connection (from WriteContext.conn)
    table: str,
    pk_col: str,
    pk_val: Any,
    updates: dict[str, Any],
    *,
    version_col: str = "updated_at",
    expected_version: Any,
) -> int:
    """
    Perform an UPDATE that only applies if the row has not been modified
    since `expected_version` was read.

    Parameters
    ----------
    conn             : Open asyncpg connection (inside a transaction).
    table            : Table name (must be a literal — not user-supplied).
    pk_col           : Primary key column name.
    pk_val           : Primary key value.
    updates          : Dict of column → new value.
    version_col      : Column used as the optimistic version (default: updated_at).
    expected_version : The value we expect the version column to have RIGHT NOW.

    Returns
    -------
    Number of rows affected (1 on success, 0 if lock conflict).

    Raises
    ------
    OptimisticLockError if rows_affected == 0 (row was updated by another writer).
    """
    if not updates:
        return 0

    # Build: SET col1=$1, col2=$2, updated_at=NOW()
    set_clauses = []
    params: list[Any] = []
    idx = 1
    for col, val in updates.items():
        set_clauses.append(f"{col} = ${idx}")
        params.append(val)
        idx += 1

    # Append updated_at=NOW() if version_col is updated_at and not in updates
    if version_col == "updated_at" and "updated_at" not in updates:
        set_clauses.append("updated_at = NOW()")

    # WHERE clause: pk + version guard
    params.append(pk_val)       # $idx
    params.append(expected_version)  # $idx+1

    sql = (
        f"UPDATE {table} "
        f"SET {', '.join(set_clauses)} "
        f"WHERE {pk_col} = ${idx} AND {version_col} = ${idx + 1}"
    )

    result = await conn.execute(sql, *params)
    # asyncpg returns "UPDATE N" string
    rows_affected = int(result.split()[-1]) if result else 0

    if rows_affected == 0:
        raise OptimisticLockError(
            table=table,
            pk_val=pk_val,
            expected=expected_version,
        )

    return rows_affected


# ── Duplicate write guard ─────────────────────────────────────────────────────

async def assert_not_duplicate(
    conn: Any,
    table: str,
    idempotency_key: str,
    *,
    key_col: str = "txn_ref",
) -> None:
    """
    Check that no row with `idempotency_key` already exists in `table`.

    Raises DuplicateWriteError immediately if a duplicate is found, before
    any INSERT is attempted.

    Parameters
    ----------
    conn            : Open asyncpg connection.
    table           : Table name.
    idempotency_key : The unique key to check (e.g. txn_ref, idempotency_key column).
    key_col         : Column name holding the idempotency key (default: txn_ref).
    """
    existing = await conn.fetchval(
        f"SELECT 1 FROM {table} WHERE {key_col} = $1 LIMIT 1",
        idempotency_key,
    )
    if existing:
        log.warning(
            "[consistency] duplicate write blocked: table=%s key=%s",
            table, idempotency_key,
        )
        raise DuplicateWriteError(table=table, key=idempotency_key)


# ── Version read helper ───────────────────────────────────────────────────────

async def read_version(
    conn: Any,
    table: str,
    pk_col: str,
    pk_val: Any,
    version_col: str = "updated_at",
) -> Optional[Any]:
    """
    Read the current version of a row without locking it.

    Returns the value of `version_col` (usually a datetime), or None if
    the row does not exist.

    Use this to fetch `expected_version` before calling `optimistic_update`.
    """
    row = await conn.fetchrow(
        f"SELECT {version_col} FROM {table} WHERE {pk_col} = $1",
        pk_val,
    )
    return row[version_col] if row else None
