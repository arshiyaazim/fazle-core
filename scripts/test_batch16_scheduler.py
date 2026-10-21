"""Batch 16 — scheduler tests.
/home/azim/fazle-core/venv/bin/python scripts/test_batch16_scheduler.py
"""
import asyncio
import os
import sys

sys.path.insert(0, "/home/azim/fazle-core")
from dotenv import load_dotenv
load_dotenv("/home/azim/fazle-core/.env")
os.environ.setdefault("OUTBOUND_ENABLED", "false")
os.environ.setdefault("SCHEDULER_ENABLED", "true")

from app.database import init_db, close_db, fetch_one, fetch_all, fetch_val, execute, get_pool
from modules import scheduler as sch
from modules import outbound as ob

PASS = "✅"


async def cleanup():
    await execute("DELETE FROM fazle_scheduled_jobs WHERE job_name LIKE 'b16-test%'")
    await execute("DELETE FROM fazle_reminders_sent WHERE reminder_key LIKE 'b16-test%'")
    await execute("DELETE FROM fazle_reconciliation_log WHERE source_ref LIKE 'b16-test%'")
    await execute("DELETE FROM fazle_outbound_queue WHERE purpose IN ('b16-test', 'dlq-alert', 'health-summary', 'stale-escort', 'backup-stale', 'payroll-daily') AND idempotency_key LIKE '%b16-test%'")


async def t1_register_and_status():
    async def fake_job():
        return {"status": "ok", "extra": 42}
    sch.register_job("b16-test-job", fake_job)
    s = await sch.get_status()
    names = [j["job_name"] for j in s["jobs"]]
    assert "b16-test-job" in names, names
    print(f"{PASS} 1. register_job + get_status (jobs={len(names)})")


async def t2_trigger_and_record():
    r = await sch.trigger_job("b16-test-job")
    assert r.get("status") == "ok"
    row = await fetch_one("SELECT last_status, run_count FROM fazle_scheduled_jobs WHERE job_name='b16-test-job'")
    assert row and row["last_status"] == "ok" and row["run_count"] >= 1
    # Run again, count should increment
    await sch.trigger_job("b16-test-job")
    row2 = await fetch_one("SELECT run_count FROM fazle_scheduled_jobs WHERE job_name='b16-test-job'")
    assert row2["run_count"] >= 2
    print(f"{PASS} 2. trigger_job records run, increments count to {row2['run_count']}")


async def t3_trigger_unknown():
    r = await sch.trigger_job("does-not-exist")
    assert r.get("status") == "error"
    print(f"{PASS} 3. unknown job returns error")


async def t4_failing_job_records_error():
    async def bad_job():
        raise RuntimeError("intentional b16-test failure")
    sch.register_job("b16-test-bad", bad_job)
    r = await sch.trigger_job("b16-test-bad")
    assert r.get("status") == "error"
    row = await fetch_one("SELECT last_status, last_error FROM fazle_scheduled_jobs WHERE job_name='b16-test-bad'")
    assert row["last_status"] == "error" and "intentional" in (row["last_error"] or "")
    print(f"{PASS} 4. failing job records error: {row['last_error'][:50]}")


async def t5_dlq_alert_no_dlq():
    # Ensure no DLQ rows
    await execute("DELETE FROM fazle_outbound_queue WHERE status='dlq' AND purpose='b16-test'")
    r = await sch.job_dlq_alert()
    assert r["status"] == "ok" and r["dlq"] == 0
    print(f"{PASS} 5. dlq_alert with no DLQ → no alert (dlq=0)")


async def t6_dlq_alert_with_dlq():
    # Insert a DLQ row
    pool = get_pool()
    async with pool.acquire() as c:
        await c.execute(
            """INSERT INTO fazle_outbound_queue (recipient, body, purpose, idempotency_key, attempts, max_attempts, status)
               VALUES ('8801999000099', 'forced dlq', 'b16-test', 'b16-test-dlq-row', 3, 3, 'dlq')
               ON CONFLICT (idempotency_key) DO NOTHING"""
        )
    r = await sch.job_dlq_alert()
    assert r["dlq"] >= 1
    # Check alert was enqueued (idempotency_key dlq-alert-<hour>)
    from datetime import datetime
    hour = datetime.utcnow().strftime("%Y%m%d%H")
    alert = await fetch_one(
        "SELECT id FROM fazle_outbound_queue WHERE idempotency_key=$1",
        f"dlq-alert-{hour}",
    )
    assert alert is not None, "alert not enqueued"
    print(f"{PASS} 6. dlq_alert enqueues admin alert (dlq={r['dlq']})")
    # cleanup
    await execute("DELETE FROM fazle_outbound_queue WHERE idempotency_key=$1", f"dlq-alert-{hour}")
    await execute("DELETE FROM fazle_outbound_queue WHERE idempotency_key='b16-test-dlq-row'")


async def t7_payment_reconciliation_match():
    # Pick a real employee with mobile
    emp = await fetch_one(
        "SELECT employee_id, employee_mobile FROM fazle_employees_legacy "
        "WHERE employee_mobile IS NOT NULL AND length(regexp_replace(employee_mobile,'\\D','','g')) >= 10 LIMIT 1"
    )
    assert emp, "need at least one employee with mobile"
    mob_digits = "".join(ch for ch in emp["employee_mobile"] if ch.isdigit())[-11:]
    # Insert staging row 2 hours ago, unmatched
    pool = get_pool()
    async with pool.acquire() as c:
        sid = await c.fetchval(
            """INSERT INTO wbom_staging_payments
                  (sender_number, extracted_mobile, extracted_name, amount, payment_method,
                   transaction_type, status, created_at)
               VALUES ($1, $1, 'b16-test-name', 100, 'bkash', 'in', 'pending', NOW() - INTERVAL '2 hours')
               RETURNING staging_id""",
            mob_digits,
        )
    r = await sch.job_payment_reconciliation()
    assert r["matched"] >= 1, r
    row = await fetch_one("SELECT matched_employee_id FROM wbom_staging_payments WHERE staging_id=$1", sid)
    assert row["matched_employee_id"] == emp["employee_id"]
    log_row = await fetch_one(
        "SELECT matched, match_method FROM fazle_reconciliation_log WHERE source_ref=$1",
        str(sid),
    )
    assert log_row and log_row["matched"] is True
    print(f"{PASS} 7. payment_reconciliation matched staging→employee (sid={sid}→eid={emp['employee_id']})")
    # cleanup
    await execute("DELETE FROM fazle_reconciliation_log WHERE source_ref=$1", str(sid))
    await execute("DELETE FROM wbom_staging_payments WHERE staging_id=$1", sid)


async def t8_stale_escort_idempotent():
    # Insert a stale Active program
    pool = get_pool()
    async with pool.acquire() as c:
        pid = await c.fetchval(
            """INSERT INTO wbom_escort_programs
                  (mother_vessel, lighter_vessel, master_mobile, program_date,
                   shift, status, start_date)
               VALUES ('B16TEST_MV', 'B16TEST_LV', '01700000000', CURRENT_DATE - 60,
                       'D', 'Active', CURRENT_DATE - 60)
               RETURNING program_id""",
        )
    r1 = await sch.job_stale_escort_reminder()
    r2 = await sch.job_stale_escort_reminder()
    # First call should alert; second should not (reminder marker prevents re-send)
    assert r1["alerted"] >= 1
    assert r2["alerted"] == 0, f"second run should be idempotent, got {r2}"
    print(f"{PASS} 8. stale_escort reminder idempotent (run1 alerted={r1['alerted']}, run2={r2['alerted']})")
    # cleanup
    await execute("DELETE FROM fazle_reminders_sent WHERE ref_id=$1", str(pid))
    await execute("DELETE FROM fazle_outbound_queue WHERE idempotency_key=$1", f"stale-escort-{pid}")
    await execute("DELETE FROM wbom_escort_programs WHERE program_id=$1", pid)


async def t9_backup_staleness():
    # Run with a temp empty dir → no backups warning
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.environ["BACKUP_DIR"] = td
        r = await sch.job_backup_staleness()
    os.environ["BACKUP_DIR"] = "/home/azim/backups"
    assert r["status"] == "ok"
    print(f"{PASS} 9. backup_staleness handles empty dir ({r})")


async def t10_health_summary():
    r = await sch.job_health_summary()
    assert r["status"] == "ok"
    assert "overall" in r
    print(f"{PASS} 10. health_summary runs (overall={r['overall']})")


async def main():
    await init_db()
    try:
        print("=== BATCH 16 SCHEDULER TESTS ===")
        await cleanup()
        await t1_register_and_status()
        await t2_trigger_and_record()
        await t3_trigger_unknown()
        await t4_failing_job_records_error()
        await t5_dlq_alert_no_dlq()
        await t6_dlq_alert_with_dlq()
        await t7_payment_reconciliation_match()
        await t8_stale_escort_idempotent()
        await t9_backup_staleness()
        await t10_health_summary()
        await cleanup()
        print("=== ALL BATCH 16 TESTS PASSED ===")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
