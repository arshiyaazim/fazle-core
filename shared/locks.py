"""
Fazle Core — Shared Processing Lock Helpers
============================================

Provides lightweight distributed-lock semantics backed by the
`fazle_processing_locks` PostgreSQL table (created in migration 008).

Use locks to prevent two workers from processing the same message
or job concurrently.  TTL-based expiry means crashes never leave
locks permanently stuck.

USAGE
-----
    from shared.locks import acquire_lock, release_lock, locked

    # Manual acquire / release:
    ok = await acquire_lock("msg:abc123", worker_id="bridge1", ttl_s=30)
    if ok:
        try:
            ...process...
        finally:
            await release_lock("msg:abc123")

    # Context-manager (preferred):
    async with locked("msg:abc123", worker_id="bridge1", ttl_s=30) as got_lock:
        if not got_lock:
            return  # another worker has it
        ...process...

    # Scheduler cleanup (called every 5 min by scheduler):
    deleted = await cleanup_expired_locks()

SAFETY
------
* All DB operations are idempotent — safe to call repeatedly.
* A lock is acquired only when it does not exist OR has expired.
* TTL defaults to 60 s; callers should set a value that fits their job.
* Uses INSERT ... ON CONFLICT DO NOTHING — no DB exceptions on contention.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from app.database import execute, fetch_val

log = logging.getLogger("fazle.shared.locks")

_DEFAULT_TTL = 60  # seconds


async def acquire_lock(
    lock_key: str,
    worker_id: str,
    ttl_s: int = _DEFAULT_TTL,
) -> bool:
    """
    Try to acquire a lock for `lock_key`.

    Returns True on success, False if another worker currently holds it.
    Expired locks are removed automatically before the attempt.

    Parameters
    ----------
    lock_key  : Unique identifier for the resource being locked.
    worker_id : Label for the worker acquiring the lock (for observability).
    ttl_s     : Lock time-to-live in seconds (default 60).
    """
    try:
        # Remove any expired lock for this key first (safe DELETE)
        await execute(
            "DELETE FROM fazle_processing_locks WHERE lock_key = $1 AND expires_at < NOW()",
            lock_key,
        )

        # Attempt to insert — ON CONFLICT DO NOTHING means no error on contention
        inserted = await fetch_val(
            """
            WITH ins AS (
                INSERT INTO fazle_processing_locks (lock_key, locked_by, expires_at)
                VALUES ($1, $2, NOW() + ($3 || ' seconds')::INTERVAL)
                ON CONFLICT (lock_key) DO NOTHING
                RETURNING 1
            )
            SELECT COUNT(*) FROM ins
            """,
            lock_key,
            worker_id,
            str(ttl_s),
        )
        acquired = int(inserted or 0) > 0
        if not acquired:
            log.debug("[locks] contention on %s (worker=%s)", lock_key, worker_id)
        return acquired
    except Exception as exc:
        # Never crash the caller — log and fail open (don't acquire)
        log.warning("[locks] acquire_lock failed lock_key=%s: %s", lock_key, exc)
        return False


async def release_lock(lock_key: str) -> None:
    """
    Release a lock unconditionally.

    Safe to call even if the lock has already expired or was never held.
    """
    try:
        await execute(
            "DELETE FROM fazle_processing_locks WHERE lock_key = $1",
            lock_key,
        )
    except Exception as exc:
        log.warning("[locks] release_lock failed lock_key=%s: %s", lock_key, exc)


async def cleanup_expired_locks() -> int:
    """
    Delete all locks whose TTL has elapsed.

    Called by the scheduler every 5 minutes.  Returns the number of rows
    deleted (useful for metrics / log alerting).
    """
    try:
        deleted = await fetch_val(
            """
            WITH del AS (
                DELETE FROM fazle_processing_locks
                WHERE expires_at < NOW()
                RETURNING 1
            )
            SELECT COUNT(*) FROM del
            """
        )
        n = int(deleted or 0)
        if n:
            log.info("[locks] cleaned up %d expired lock(s)", n)
        return n
    except Exception as exc:
        log.warning("[locks] cleanup_expired_locks failed: %s", exc)
        return 0


@asynccontextmanager
async def locked(
    lock_key: str,
    worker_id: str,
    ttl_s: int = _DEFAULT_TTL,
) -> AsyncGenerator[bool, None]:
    """
    Async context manager that acquires the lock on entry and releases on exit.

    Yields True if the lock was acquired, False if already held by another worker.
    The caller should check the yielded value and skip processing if False.

    Example
    -------
        async with locked("msg:abc", worker_id="bridge1") as got_lock:
            if not got_lock:
                return
            ...safe to process...
    """
    acquired = await acquire_lock(lock_key, worker_id, ttl_s)
    try:
        yield acquired
    finally:
        if acquired:
            await release_lock(lock_key)


# ── Ingestion dedup fingerprint ───────────────────────────────────────────────

import hashlib as _hashlib


def ingestion_fingerprint(
    wa_message_id: str,
    source: str,
    *,
    employee_id: int | None = None,
    amount_cents: int | None = None,
) -> str:
    """
    Build a stable deduplication key for a message ingestion event.

    The fingerprint is a short hex digest that can be used as:
    - A `txn_ref` in fazle_cash_transactions (when employee + amount are known)
    - A `lock_key` in fazle_processing_locks (always, using message_id + source)

    Parameters
    ----------
    wa_message_id : WhatsApp message ID string (unique per device).
    source        : Bridge identifier, e.g. "bridge1" | "bridge2".
    employee_id   : FPE employee row ID (optional, used when building txn_ref).
    amount_cents  : Integer amount × 100 (optional, used when building txn_ref).

    Returns a 16-hex-char prefix of the SHA-256 of all supplied fields.
    This is collision-resistant enough for these volumes (~10⁶ annual messages).
    """
    parts = [wa_message_id, source]
    if employee_id is not None:
        parts.append(str(employee_id))
    if amount_cents is not None:
        parts.append(str(amount_cents))
    raw = "|".join(parts).encode()
    return _hashlib.sha256(raw).hexdigest()[:16]


# ── Per-entity convenience context managers (Phase 12B) ──────────────────────

@asynccontextmanager
async def per_employee_lock(
    employee_id: int | str,
    worker_id: str = "fazle-core",
    ttl_s: int = 30,
):
    """
    Distributed lock scoped to a single employee record.

    Prevents concurrent updates to the same employee from multiple workers
    or API callers.

    Example
    -------
        async with per_employee_lock(employee_id=42, worker_id="payroll") as ok:
            if not ok:
                return  # another worker is updating this employee right now
            ...safe to update...
    """
    key = f"entity:employee:{employee_id}"
    async with locked(key, worker_id=worker_id, ttl_s=ttl_s) as got:
        yield got


@asynccontextmanager
async def per_program_lock(
    program_id: int | str,
    worker_id: str = "fazle-core",
    ttl_s: int = 30,
):
    """
    Distributed lock scoped to a single escort program.

    Prevents concurrent state changes (assign/release/complete) from racing.

    Example
    -------
        async with per_program_lock(program_id=7, worker_id="escort-worker") as ok:
            if not ok:
                return
            ...safe to update...
    """
    key = f"entity:program:{program_id}"
    async with locked(key, worker_id=worker_id, ttl_s=ttl_s) as got:
        yield got


@asynccontextmanager
async def per_transaction_lock(
    txn_ref: str,
    worker_id: str = "fazle-core",
    ttl_s: int = 30,
):
    """
    Distributed lock scoped to a single transaction reference.

    Prevents double-commit of the same payment when the bridge retries.

    Example
    -------
        async with per_transaction_lock("fpe-abc123", worker_id="bridge1") as ok:
            if not ok:
                return  # already being processed
            ...safe to insert...
    """
    key = f"entity:txn:{txn_ref}"
    async with locked(key, worker_id=worker_id, ttl_s=ttl_s) as got:
        yield got
