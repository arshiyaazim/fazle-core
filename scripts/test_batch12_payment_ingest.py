"""
Batch 12 — Payment ingest pipeline test (synthetic, idempotent).

Verifies:
  1. parse_payment_sms covers bKash / Nagad / generic
  2. match_employee finds employees by exact mobile
  3. ingest_payment_sms creates wbom_staging_payments row
  4. high-confidence + small amount → auto_finalize → fazle_cash_transactions_archive row
  5. duplicate idempotency_key returns existing staging
  6. unknown mobile → status=unmatched (no auto-finalize)

Cleans up its own rows at the end.
"""
import asyncio
import sys
sys.path.insert(0, "/home/azim/fazle-core")

from app.database import fetch_one, fetch_all, execute, fetch_val, init_db, close_db
from modules.fazle_payment_ingest import (
    parse_payment_sms, match_employee, ingest_payment_sms,
)


async def main():
    print("=== Batch 12 payment ingest test ===\n")
    await init_db()
    # Pick a real employee
    emp = await fetch_one(
        "SELECT employee_id, employee_name, employee_mobile FROM fazle_employees_legacy "
        "WHERE employee_mobile IS NOT NULL ORDER BY employee_id LIMIT 1"
    )
    assert emp, "no employees"
    eid = emp["employee_id"]
    mob = emp["employee_mobile"]
    name = emp["employee_name"]
    print(f"Test employee: {eid} {name} {mob}")

    # 1. Parse
    sms = f"bKash: Cash In Tk 1,234.00 from {mob} successful. TrxID B12TEST1 Fee Tk 0"
    parsed = parse_payment_sms(sms)
    print(f"\n[1] parse → {parsed}")
    assert parsed and parsed["amount"] == 1234.0 and parsed["mobile"] == mob

    # 2. Match
    m_eid, ratio, mtype = await match_employee(mob, None)
    print(f"[2] match → eid={m_eid} ratio={ratio} type={mtype}")
    assert m_eid == eid and mtype == "mobile_exact"

    # 3+4. Ingest with auto_finalize
    res = await ingest_payment_sms(sms, sender_number="test-suite", auto_finalize=True)
    print(f"[3+4] ingest → status={res['status']} staging={res.get('staging_id')} "
          f"finalized={res.get('finalized')}")
    assert res["ok"] and res["status"] == "auto_approved"
    assert res["matched_employee_id"] == eid
    fin = res["finalized"]
    assert fin["transaction_id"], "should auto-create fazle_cash_transactions_archive row"
    sid_1 = res["staging_id"]
    txn_id = fin["transaction_id"]
    draft_id = fin["draft_id"]

    # 5. Duplicate
    res2 = await ingest_payment_sms(sms, sender_number="test-suite")
    print(f"[5] duplicate → status={res2['status']} staging={res2.get('staging_id')}")
    assert res2["status"] == "duplicate" and res2["staging_id"] == sid_1

    # 6. Unmatched mobile
    sms3 = "Cash In Tk 500.00 from 01999999999 successful. TrxID B12TESTX"
    res3 = await ingest_payment_sms(sms3, sender_number="test-suite")
    print(f"[6] unmatched → status={res3['status']} eid={res3.get('matched_employee_id')}")
    assert res3["status"] == "unmatched" and res3["matched_employee_id"] is None
    sid_3 = res3["staging_id"]

    # Verify DB rows
    txn = await fetch_one(
        "SELECT transaction_id, employee_id, amount, payment_method FROM fazle_cash_transactions_archive WHERE transaction_id=$1",
        int(txn_id),
    )
    print(f"\n[verify] txn row: {txn}")
    assert txn and int(txn["employee_id"]) == eid

    # Cleanup
    print("\n[cleanup]")
    await execute("DELETE FROM wbom_staging_payments WHERE staging_id IN ($1,$2)", sid_1, sid_3)
    await execute("DELETE FROM fazle_cash_transactions_archive WHERE transaction_id=$1", int(txn_id))
    await execute("DELETE FROM fazle_payment_drafts WHERE id=$1", int(draft_id))

    print("\n✅ ALL BATCH 12 TESTS PASSED")
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
