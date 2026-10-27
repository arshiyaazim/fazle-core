"""Admin messages must bypass the inbound reply-cooldown gate.

Regression cover for the Owner decision of 2026-10-25.

Background
----------
``process_bridge_inbound()`` (modules/fazle_bridge_poller/__init__.py) applies
``REPLY_COOLDOWN`` (60s) per sender as step "1. Cooldown", and on a hit it
``return``s *before* ``process_message()``. The constant is documented as
"minimum seconds between replies to same number" -- an outbound anti-spam
concern -- but the gate also suppressed inbound PROCESSING.

Consequence: an admin who sent two commands within 60 seconds had the second
one dropped silently. The webhook still answered 200, so nothing surfaced.
Reproduced with RBAC satisfied (operator role present):

    cooldown armed    -> process_admin_command never reached, draft=pending, txns=0
    cooldown cleared  -> reached,                            draft=approved, txns=1

Fix: ``_cooldown_blocked = (id_role != "admin") and not await _can_reply(phone)``
     Admin traffic skips the gate; every other role keeps it unchanged.

These two tests pin both halves of that: admins get through, everyone else
does not.
"""
from __future__ import annotations

import pytest

from tests.conftest import ADMIN_PHONE, make_bridge_payload

GUARD_PHONE = "8801811111111"


async def _seed_admin_with_operator_role(pool, phone: str) -> None:
    """Admin row + `operator` role, which the `paid` command requires (RBAC)."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO fazle_admins (phone, name, status)
            VALUES ($1, 'Cooldown Test Admin', 'active')
            ON CONFLICT (phone) DO NOTHING
            """,
            phone,
        )
        await conn.execute(
            """
            INSERT INTO fazle_admin_roles (admin_id, role_name, granted_by)
            SELECT id, 'operator', 'system' FROM fazle_admins WHERE phone=$1
            ON CONFLICT DO NOTHING
            """,
            phone,
        )


async def _seed_payment_draft(pool, employee_id: int) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO fazle_payment_drafts
                (draft_type, employee_id, employee_name, employee_mobile,
                 gross_amount, food_bill, conveyance, advance_deduction,
                 version, status, source)
            VALUES ('escort_payment', $1, 'Test Guard', '8801811111111',
                    1500.0, 0, 0, 0, 1, 'pending', 'bridge2')
            RETURNING *
            """,
            employee_id,
        )
    return dict(row)


@pytest.mark.asyncio
async def test_admin_command_reaches_dispatch_while_cooldown_is_armed(
    client, test_db_pool, mock_all_services, seed_employee
):
    """An admin's PAID must execute even though the cooldown is armed.

    This is the whole point of the exemption: before it, this assertion
    failed with draft=pending / txns=0 despite the command being valid.
    """
    import app.database as db

    db._pool = test_db_pool
    from modules import fazle_bridge_poller as bp

    await _seed_admin_with_operator_role(test_db_pool, ADMIN_PHONE)
    draft = await _seed_payment_draft(test_db_pool, seed_employee["employee_id"])

    # Arm the cooldown with a first admin command, then prove it is armed —
    # otherwise the assertion below would pass for the wrong reason.
    await client.post(
        "/webhook/mcp2",
        json=make_bridge_payload(ADMIN_PHONE, "DRAFTS", source="bridge2"),
    )
    assert not await bp._can_reply(ADMIN_PHONE), (
        "precondition: cooldown should be armed after the first admin command"
    )

    reached: list[str] = []
    import modules.message_router as mr

    real = mr.process_admin_command

    async def spy(text, admin_phone):
        reached.append(text)
        return await real(text, admin_phone)

    mr.process_admin_command = spy
    try:
        await client.post(
            "/webhook/mcp2",
            json=make_bridge_payload(
                ADMIN_PHONE, f"PAID {draft['id']} 1500 bkash", source="bridge2"
            ),
        )
    finally:
        mr.process_admin_command = real

    assert reached, (
        "admin command must reach process_admin_command despite the cooldown"
    )

    async with test_db_pool.acquire() as conn:
        status = await conn.fetchval(
            "SELECT status FROM fazle_payment_drafts WHERE id=$1", draft["id"]
        )
        txns = await conn.fetchval("SELECT COUNT(*) FROM fazle_cash_transactions")

    assert status == "approved", f"draft not approved, got {status!r}"
    assert txns == 1, f"expected exactly 1 cash transaction, got {txns}"


@pytest.mark.asyncio
async def test_non_admin_still_gated_by_the_cooldown(
    client, test_db_pool, mock_all_services
):
    """The exemption is scoped to role=admin; everyone else keeps the gate.

    Probe is process_message(), NOT a row count: _save_message() runs at
    lines 2008/2664, i.e. BEFORE the cooldown gate, so a dropped message is
    still persisted and counting rows would hide the gate entirely.
    """
    import app.database as db

    db._pool = test_db_pool
    from modules import fazle_bridge_poller as bp

    # Arm directly: a real first message does not reliably produce a reply in
    # this environment, and _record_reply() only fires once one is enqueued.
    await bp._record_reply(GUARD_PHONE)
    assert not await bp._can_reply(GUARD_PHONE), "precondition: cooldown armed"

    reached: list[str] = []
    import modules.message_router as mr

    real_pm = mr.process_message

    async def spy(*args, **kwargs):
        reached.append(args[1] if len(args) > 1 else kwargs.get("text"))
        return await real_pm(*args, **kwargs)

    mr.process_message = spy
    try:
        await client.post(
            "/webhook/mcp1",
            json=make_bridge_payload(GUARD_PHONE, "আজকে ছুটিতে আছি", source="bridge1"),
        )
    finally:
        mr.process_message = real_pm

    assert not reached, (
        f"non-admin message must still be dropped while cooling down, got {reached}"
    )
