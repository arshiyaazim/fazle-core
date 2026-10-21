"""
shared.write_router — Canonical Write Path (Phase 12A + 12B)
=============================================================

ALL database writes for employees, payments, escort programs, and transactions
must flow through this module.

Architecture
------------
* Apps MAY read and render independently.
* ALL writes are serialized through `routed_write()` which:
    1. Acquires a per-resource distributed lock (via shared.locks)
    2. Runs an optional optimistic-version check (via shared.consistency)
    3. Executes the writer callback inside a DB transaction
    4. Emits a domain event (via shared.events)
    5. Releases the lock on exit (even on failure)

Write types
-----------
  employee      → lock key: "write:employee:{employee_id}"
  payment       → lock key: "write:payment:{txn_ref}"
  escort        → lock key: "write:escort:{program_id}"
  transaction   → lock key: "write:txn:{txn_id}"
  generic       → lock key: "write:{resource}:{resource_id}"

Safe for standalone apps
------------------------
Payroll Engine and Escort Roster may call these helpers directly when they
want coordination.  They also remain fully operational WITHOUT this layer —
nothing in their existing code paths is broken or replaced.

USAGE
-----
    from shared.write_router import routed_write, WriteContext

    async def _do_salary_update(ctx: WriteContext) -> dict:
        await ctx.conn.execute(
            "UPDATE fazle_employees_legacy SET salary=$1 WHERE employee_id=$2",
            new_salary, employee_id
        )
        return {"employee_id": employee_id, "salary": new_salary}

    result = await routed_write(
        resource="employee",
        resource_id=str(employee_id),
        writer=_do_salary_update,
        event_type="employee_updated",
        event_payload={"employee_id": employee_id},
        caller="payroll_engine",
        ttl_s=30,
    )

    if not result.ok:
        # lock contention or write failure
        log.warning("write blocked: %s", result.error)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from app.database import get_pool
from shared.locks import acquire_lock, release_lock
from shared import events as _events
from shared.state_version import bump_state_version as _bump_version

log = logging.getLogger("fazle.write_router")

# In-memory per-process asyncio.Lock for ultra-fast intra-process serialization.
# The distributed DB lock handles cross-process (multi-worker) coordination.
_local_locks: dict[str, asyncio.Lock] = {}
_local_locks_guard = asyncio.Lock()


async def _get_local_lock(key: str) -> asyncio.Lock:
    async with _local_locks_guard:
        if key not in _local_locks:
            _local_locks[key] = asyncio.Lock()
        return _local_locks[key]


# ── Write context ─────────────────────────────────────────────────────────────

@dataclass
class WriteContext:
    """Passed to the writer callback so it can use the open DB connection."""
    conn: Any               # asyncpg.Connection
    resource: str           # "employee" | "payment" | "escort" | "txn" | custom
    resource_id: str        # e.g. "42" or "EMP-0015"
    caller: str             # module/worker identifier for tracing
    lock_key: str           # full lock key used
    meta: dict = field(default_factory=dict)  # extra metadata callers can attach


# ── Write result ──────────────────────────────────────────────────────────────

@dataclass
class WriteResult:
    ok: bool
    data: Any = None
    error: Optional[str] = None
    lock_key: Optional[str] = None
    event_emitted: bool = False


# ── Core router ──────────────────────────────────────────────────────────────

async def routed_write(
    resource: str,
    resource_id: str,
    writer: Callable[[WriteContext], Awaitable[Any]],
    *,
    event_type: Optional[str] = None,
    event_payload: Optional[dict] = None,
    caller: str = "unknown",
    ttl_s: int = 30,
    meta: Optional[dict] = None,
    enqueue_on_contention: bool = False,
) -> WriteResult:
    """
    Execute a coordinated, serialized DB write.

    Parameters
    ----------
    resource        : Resource domain — "employee", "payment", "escort", "txn", or custom.
    resource_id     : Unique identifier within the domain (string).
    writer          : Async callback that receives a WriteContext and performs DB writes.
                      The callback runs INSIDE a DB transaction — raise to rollback.
    event_type      : Domain event to emit after a successful write (optional).
    event_payload   : Payload for the event (optional, defaults to resource info).
    caller          : Identifier of the calling module/worker for observability.
    ttl_s           : Distributed lock TTL in seconds (default 30).
    meta            : Extra metadata passed to the WriteContext.
    enqueue_on_contention : If True and the lock is held, the write is enqueued
                            for retry (via shared.queue) instead of failing.
                            NOT YET IMPLEMENTED — reserved for future use.

    Returns WriteResult with ok=True on success, ok=False on contention/failure.
    """
    lock_key = f"write:{resource}:{resource_id}"

    # ── Step 1: In-process serialization (fast path) ──────────────────────────
    local_lock = await _get_local_lock(lock_key)
    async with local_lock:

        # ── Step 2: Distributed lock (cross-process) ──────────────────────────
        acquired = await acquire_lock(lock_key, worker_id=caller, ttl_s=ttl_s)
        if not acquired:
            log.warning(
                "[write_router] lock contention resource=%s id=%s caller=%s",
                resource, resource_id, caller,
            )
            if enqueue_on_contention:
                # TODO: enqueue to fazle_write_queue for deferred retry
                pass
            return WriteResult(ok=False, error="lock_contention", lock_key=lock_key)

        try:
            # ── Step 3: Execute writer inside a DB transaction ─────────────
            pool = get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    ctx = WriteContext(
                        conn=conn,
                        resource=resource,
                        resource_id=resource_id,
                        caller=caller,
                        lock_key=lock_key,
                        meta=meta or {},
                    )
                    data = await writer(ctx)

            # ── Step 4: Emit domain event ──────────────────────────────────
            emitted = False
            if event_type:
                payload = event_payload or {}
                payload.setdefault("resource", resource)
                payload.setdefault("resource_id", resource_id)
                payload.setdefault("caller", caller)
                try:
                    await _events.emit(event_type, payload)
                    emitted = True
                except Exception as evt_exc:
                    log.warning(
                        "[write_router] event emit failed type=%s: %s",
                        event_type, evt_exc,
                    )

            log.debug(
                "[write_router] ✔ resource=%s id=%s caller=%s event=%s",
                resource, resource_id, caller, event_type or "none",
            )

            # ── Step 5: Bump global state version ─────────────────────────
            try:
                await _bump_version()
            except Exception as sv_exc:
                log.debug("[write_router] state_version bump failed: %s", sv_exc)

            return WriteResult(ok=True, data=data, lock_key=lock_key, event_emitted=emitted)

        except Exception as exc:
            log.error(
                "[write_router] ✘ resource=%s id=%s caller=%s error=%s",
                resource, resource_id, caller, exc,
            )
            return WriteResult(ok=False, error=str(exc), lock_key=lock_key)

        finally:
            await release_lock(lock_key)


# ── Convenience wrappers ──────────────────────────────────────────────────────

async def write_employee(
    employee_id: int | str,
    writer: Callable[[WriteContext], Awaitable[Any]],
    *,
    caller: str = "unknown",
    event_payload: Optional[dict] = None,
) -> WriteResult:
    """Serialized write for an employee record."""
    return await routed_write(
        resource="employee",
        resource_id=str(employee_id),
        writer=writer,
        event_type="employee_updated",
        event_payload=event_payload or {"employee_id": employee_id},
        caller=caller,
        ttl_s=30,
    )


async def write_payment(
    txn_ref: str,
    writer: Callable[[WriteContext], Awaitable[Any]],
    *,
    caller: str = "unknown",
    event_payload: Optional[dict] = None,
) -> WriteResult:
    """Serialized write for a payment / cash transaction."""
    return await routed_write(
        resource="payment",
        resource_id=txn_ref,
        writer=writer,
        event_type="payment_created",
        event_payload=event_payload or {"txn_ref": txn_ref},
        caller=caller,
        ttl_s=30,
    )


async def write_escort(
    program_id: int | str,
    writer: Callable[[WriteContext], Awaitable[Any]],
    *,
    caller: str = "unknown",
    event_payload: Optional[dict] = None,
) -> WriteResult:
    """Serialized write for an escort program record."""
    return await routed_write(
        resource="escort",
        resource_id=str(program_id),
        writer=writer,
        event_type="escort_assigned",
        event_payload=event_payload or {"program_id": program_id},
        caller=caller,
        ttl_s=30,
    )


async def write_transaction(
    txn_id: int | str,
    writer: Callable[[WriteContext], Awaitable[Any]],
    *,
    caller: str = "unknown",
    event_payload: Optional[dict] = None,
) -> WriteResult:
    """Serialized write for an FPE cash transaction row."""
    return await routed_write(
        resource="txn",
        resource_id=str(txn_id),
        writer=writer,
        event_type="payment_corrected",
        event_payload=event_payload or {"txn_id": txn_id},
        caller=caller,
        ttl_s=30,
    )


# ── Diagnostics ───────────────────────────────────────────────────────────────

def get_local_lock_stats() -> dict:
    """Return in-memory lock stats for the diagnostics endpoint."""
    return {
        "tracked_resources": len(_local_locks),
        "lock_keys": list(_local_locks.keys())[:50],  # cap at 50 for safety
    }
