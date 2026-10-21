"""
Batch 14 — Monthly payroll pipeline test (synthetic, idempotent).

Verifies:
  1. compute_run creates draft + items
  2. compute_run idempotent (same period → already_exists)
  3. State machine: submit → approve → lock → paid (with idempotency key set)
  4. Disallowed transitions rejected
  5. cancel_run from draft works on a 2nd employee
  6. list_runs filters by status
  7. Approval log entries written for each transition

Cleans up its own rows.
"""
import asyncio
import sys
from datetime import date
sys.path.insert(0, "/home/azim/fazle-core")

from app.database import fetch_one, fetch_all, fetch_val, execute, init_db, close_db
from modules.payroll import (
    compute_run, submit_run, approve_run, lock_run, mark_paid,
    cancel_run, get_run, list_runs, ALLOWED_TRANSITIONS,
)


YEAR = 2024  # historical period to avoid clashing with live data
MONTH = 1


async def cleanup(emp_ids):
    if not emp_ids:
        return
    await execute(
        "DELETE FROM wbom_payroll_approval_log WHERE run_id IN "
        "(SELECT run_id FROM wbom_payroll_runs WHERE employee_id = ANY($1::int[]) "
        " AND period_year=$2 AND period_month=$3)",
        emp_ids, YEAR, MONTH,
    )
    await execute(
        "DELETE FROM wbom_payroll_run_items WHERE run_id IN "
        "(SELECT run_id FROM wbom_payroll_runs WHERE employee_id = ANY($1::int[]) "
        " AND period_year=$2 AND period_month=$3)",
        emp_ids, YEAR, MONTH,
    )
    await execute(
        "DELETE FROM wbom_payroll_runs WHERE employee_id = ANY($1::int[]) "
        "AND period_year=$2 AND period_month=$3",
        emp_ids, YEAR, MONTH,
    )


async def main():
    print("=== Batch 14 payroll pipeline test ===\n")
    await init_db()

    rows = await fetch_all(
        "SELECT employee_id FROM fazle_employees_legacy ORDER BY employee_id LIMIT 2"
    )
    assert len(rows) >= 2, "need at least 2 employees"
    eid1 = int(rows[0]["employee_id"])
    eid2 = int(rows[1]["employee_id"])
    print(f"Test employees: {eid1}, {eid2}")
    await cleanup([eid1, eid2])

    # 1. compute_run creates draft
    r1 = await compute_run(eid1, YEAR, MONTH, "b14-test")
    assert r1["ok"] and not r1.get("already_exists"), r1
    run_id = r1["run_id"]
    print(f"✅ 1. compute_run created run #{run_id} status=draft "
          f"net={r1['net_salary']}")

    # Verify items
    item_count = await fetch_val(
        "SELECT COUNT(*) FROM wbom_payroll_run_items WHERE run_id=$1", run_id,
    )
    assert item_count >= 1, f"expected items, got {item_count}"
    print(f"   {item_count} line items inserted")

    # 2. idempotent
    r2 = await compute_run(eid1, YEAR, MONTH, "b14-test-2")
    assert r2["ok"] and r2.get("already_exists") and r2["run_id"] == run_id, r2
    cnt = await fetch_val(
        "SELECT COUNT(*) FROM wbom_payroll_runs WHERE employee_id=$1 "
        "AND period_year=$2 AND period_month=$3",
        eid1, YEAR, MONTH,
    )
    assert cnt == 1
    print(f"✅ 2. compute_run idempotent (still 1 run)")

    # 3. state machine: submit → approve → lock → paid
    s1 = await submit_run(run_id, "b14:tester")
    assert s1["ok"] and s1["to_status"] == "reviewed", s1
    s2 = await approve_run(run_id, "b14:approver")
    assert s2["ok"] and s2["to_status"] == "approved", s2
    s3 = await lock_run(run_id, "b14:locker")
    assert s3["ok"] and s3["to_status"] == "locked", s3
    s4 = await mark_paid(run_id, "b14:payer", r1["net_salary"], "bkash", "B14TX1")
    assert s4["ok"] and s4["to_status"] == "paid", s4
    print(f"✅ 3. state machine draft→reviewed→approved→locked→paid")

    final = await get_run(run_id)
    assert final["status"] == "paid"
    assert final["payment_method"] == "bkash"
    assert final["payment_reference"] == "B14TX1"
    assert final["payout_idempotency_key"] is not None
    assert final["paid_at"] is not None
    print(f"   final: paid_at set, idem_key={final['payout_idempotency_key']}")

    # 4. disallowed: paid → submit
    bad = await submit_run(run_id, "b14:tester")
    assert not bad["ok"] and "not allowed" in bad["error"], bad
    print(f"✅ 4. disallowed transition rejected: {bad['error']}")

    # 5. cancel from draft on emp2
    r5 = await compute_run(eid2, YEAR, MONTH, "b14-test")
    assert r5["ok"]
    run_id2 = r5["run_id"]
    c = await cancel_run(run_id2, "b14:canceller", "test cancel")
    assert c["ok"] and c["to_status"] == "cancelled", c
    print(f"✅ 5. cancel run #{run_id2} from draft → cancelled")

    # After cancel, recompute must create a NEW run (UNIQUE allows it)
    r5b = await compute_run(eid2, YEAR, MONTH, "b14-test")
    assert r5b["ok"] and not r5b.get("already_exists"), r5b
    assert r5b["run_id"] != run_id2
    print(f"   recompute after cancel created new run #{r5b['run_id']}")

    # 6. list filters
    all_rows = await list_runs(YEAR, MONTH)
    paid_rows = await list_runs(YEAR, MONTH, "paid")
    cancelled_rows = await list_runs(YEAR, MONTH, "cancelled")
    assert any(r["run_id"] == run_id for r in paid_rows)
    assert any(r["run_id"] == run_id2 for r in cancelled_rows)
    print(f"✅ 6. list_runs all={len(all_rows)} paid={len(paid_rows)} "
          f"cancelled={len(cancelled_rows)}")

    # 7. approval log
    log_count = await fetch_val(
        "SELECT COUNT(*) FROM wbom_payroll_approval_log WHERE run_id=$1", run_id,
    )
    # compute + 4 transitions = 5
    assert log_count == 5, f"expected 5 log rows, got {log_count}"
    print(f"✅ 7. approval log has {log_count} entries for run #{run_id}")

    # cleanup (also include r5b)
    await cleanup([eid1, eid2])
    # verify cleanup
    remaining = await fetch_val(
        "SELECT COUNT(*) FROM wbom_payroll_runs "
        "WHERE employee_id = ANY($1::int[]) AND period_year=$2 AND period_month=$3",
        [eid1, eid2], YEAR, MONTH,
    )
    assert remaining == 0
    print(f"✅ cleanup complete (0 rows remaining)")
    print("\n=== ALL BATCH 14 TESTS PASSED ===")
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
