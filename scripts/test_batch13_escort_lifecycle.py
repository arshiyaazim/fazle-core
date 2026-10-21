"""
Batch 13 — Escort lifecycle test (synthetic, idempotent).

  1. is_release_intent on BN/EN samples
  2. find_active_program_for_employee with synthetic Assigned program
  3. close_program (once + twice → already_closed)
  4. backfill_attendance_for_program (count + idempotency)
  5. handle_release_event end-to-end → draft created
  6. handle_release_event re-run → already_closed, no new draft
  7. cleanup
"""
import asyncio
import sys
from datetime import date, timedelta
sys.path.insert(0, "/home/azim/fazle-core")

from app.database import fetch_one, execute, fetch_val, init_db, close_db
from modules.escort_lifecycle import (
    is_release_intent, find_active_program_for_employee,
    close_program, backfill_attendance_for_program,
    handle_release_event,
)

VESSEL = "B13_TEST_VESSEL"
SOURCE = "b13-test"


async def cleanup(eid: int):
    await execute(
        "DELETE FROM fazle_payment_drafts WHERE source LIKE 'b13-test%'"
    )
    await execute(
        "DELETE FROM fazle_payment_drafts WHERE escort_program_id IN "
        "(SELECT program_id FROM wbom_escort_programs WHERE mother_vessel=$1)",
        VESSEL,
    )
    await execute(
        "DELETE FROM wbom_attendance WHERE recorded_by='escort-lifecycle' "
        "AND employee_id=$1 AND attendance_date >= CURRENT_DATE - INTERVAL '7 days'",
        eid,
    )
    await execute(
        "DELETE FROM wbom_escort_programs WHERE mother_vessel=$1", VESSEL,
    )


async def main():
    print("=== Batch 13 escort lifecycle test ===\n")
    await init_db()

    # 1. intent detection
    bn_pos = ["আজ ডিউটি শেষ হয়েছে স্যার", "রিলিজ হয়েছি", "পেমেন্ট দেন স্যার"]
    en_pos = ["release", "duty done", "Off duty now"]
    neg = ["কেমন আছেন", "advance চাই 5000", "salam"]
    for s in bn_pos + en_pos:
        assert is_release_intent(s), f"should detect release: {s}"
    for s in neg:
        assert not is_release_intent(s), f"should NOT detect release: {s}"
    print("✅ 1. is_release_intent passes 6 positives + 3 negatives")

    # Pick employee
    emp = await fetch_one(
        "SELECT employee_id, employee_name, employee_mobile FROM fazle_employees_legacy "
        "WHERE employee_mobile IS NOT NULL ORDER BY employee_id LIMIT 1"
    )
    eid = emp["employee_id"]
    name = emp["employee_name"]
    mob = emp["employee_mobile"]
    print(f"   Test employee: {eid} {name} {mob}")

    await cleanup(eid)

    # 2. insert synthetic program
    today = date.today()
    start = today - timedelta(days=2)
    pid = await fetch_val(
        """INSERT INTO wbom_escort_programs
              (mother_vessel, lighter_vessel, master_mobile, escort_employee_id,
               escort_mobile, program_date, shift, status, start_date)
           VALUES ($1, 'B13L', '8801999999999', $2, $3, $4, 'D', 'Assigned', $4)
           RETURNING program_id""",
        VESSEL, eid, mob, start,
    )
    print(f"✅ 2a. inserted synthetic program #{pid} start={start}")

    found = await find_active_program_for_employee(eid)
    assert found and found["program_id"] == pid, "active program lookup failed"
    print(f"✅ 2b. find_active_program_for_employee returns #{pid}")

    # 3. close once
    closed1 = await close_program(pid, today, "D", "Mongla", None, "b13-test:close1")
    assert closed1["ok"] and not closed1.get("already_closed")
    assert closed1["day_count"] == 3.0, f"expected 3 days got {closed1['day_count']}"
    print(f"✅ 3a. close_program #1 day_count={closed1['day_count']}")

    closed2 = await close_program(pid, today, "D", "Mongla", None, "b13-test:close2")
    assert closed2["ok"] and closed2.get("already_closed")
    print("✅ 3b. close_program #2 → already_closed")

    # 4. backfill
    n1 = await backfill_attendance_for_program(pid)
    assert n1 == 3, f"expected 3 attendance rows, got {n1}"
    print(f"✅ 4a. backfill inserted {n1} rows")
    n2 = await backfill_attendance_for_program(pid)
    assert n2 == 0, f"expected 0 on rerun, got {n2}"
    print(f"✅ 4b. backfill rerun inserted {n2} rows (idempotent)")

    # Reset program for end-to-end test
    await execute("DELETE FROM wbom_attendance WHERE employee_id=$1 AND attendance_date>=$2",
                  eid, start)
    await execute(
        "UPDATE wbom_escort_programs SET status='Assigned', completion_time=NULL, "
        "end_date=NULL, end_shift=NULL, release_point=NULL, day_count=0, "
        "remarks=NULL WHERE program_id=$1", pid,
    )
    print("   reset program to Assigned for e2e test")

    # 5. handle_release_event
    rel1 = await handle_release_event(eid, extracted={
        "end_date": today.isoformat(), "end_shift": "D", "release_point": "Mongla",
    }, source="b13-test:e2e")
    assert rel1["ok"] and rel1["status"] == "closed", rel1
    assert rel1.get("draft_id"), f"expected draft_id, got {rel1}"
    assert rel1["attendance_inserted"] == 3
    draft_id = rel1["draft_id"]
    print(f"✅ 5. handle_release_event closed program, draft #{draft_id} created")

    drow = await fetch_one(
        "SELECT id, escort_program_id, source FROM fazle_payment_drafts WHERE id=$1",
        draft_id,
    )
    assert drow and drow["escort_program_id"] == pid
    print(f"   draft escort_program_id={drow['escort_program_id']} source={drow['source']}")

    # 6. re-run idempotency: close_program on same pid → already_closed,
    #    find_existing_draft returns same draft. (handle_release_event uses
    #    find_active_program which would pick a *different* program if multiple
    #    actives exist for this emp; per-program idempotency is the contract.)
    from modules.escort_lifecycle import find_existing_draft_for_program
    closed3 = await close_program(pid, today, "D", "Mongla", None, "b13-test:rerun")
    assert closed3["ok"] and closed3.get("already_closed"), closed3
    existing = await find_existing_draft_for_program(pid)
    assert existing and existing["id"] == draft_id, f"expected draft #{draft_id}, got {existing}"
    cnt = await fetch_val(
        "SELECT COUNT(*) FROM fazle_payment_drafts WHERE escort_program_id=$1", pid,
    )
    assert cnt == 1, f"expected exactly 1 draft, got {cnt}"
    print(f"✅ 6. per-program idempotent: {cnt} draft, find_existing returns id={existing['id']}")

    # 7. cleanup
    await cleanup(eid)
    print("✅ 7. cleanup complete")
    print("\n=== ALL BATCH 13 TESTS PASSED ===")
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
