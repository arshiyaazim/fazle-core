
"""Batch 17 — reports tests.
/home/azim/fazle-core/venv/bin/python scripts/test_batch17_reports.py
"""
import asyncio
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, "/home/azim/fazle-core")
from dotenv import load_dotenv
load_dotenv("/home/azim/fazle-core/.env")
os.environ.setdefault("OUTBOUND_ENABLED", "false")

from app.database import init_db, close_db, fetch_one, execute, get_pool
from modules import reports as r

PASS = "✅"


async def cleanup():
    await execute("DELETE FROM fazle_report_runs WHERE requested_by LIKE 'b17-test%'")
    await execute("DELETE FROM fazle_report_cache")


async def t1_list_reports():
    names = r.list_reports()
    expected = {"daily_summary", "monthly_payroll", "escort_utilization",
                "payment_reconciliation", "cash_position"}
    assert expected.issubset(set(names)), f"missing: {expected - set(names)}"
    print(f"{PASS} 1. list_reports returns {len(names)} reports")


async def t2_daily_summary():
    p = await r.run_report("daily_summary", {"date": date.today()}, requested_by="b17-test")
    assert p["report"] == "daily_summary"
    s = p["summary"]
    for k in ("payments_in", "payments_out", "programs_total"):
        assert k in s, f"missing key {k}"
    print(f"{PASS} 2. daily_summary in={s['payments_in']:.2f} out={s['payments_out']:.2f} programs={s['programs_total']}")


async def t3_monthly_payroll():
    p = await r.run_report("monthly_payroll", {"year": 2026, "month": 4}, requested_by="b17-test")
    assert p["report"] == "monthly_payroll"
    assert "summary" in p and "rows" in p
    print(f"{PASS} 3. monthly_payroll runs={p['summary']['runs']}")


async def t4_escort_utilization():
    end = date.today()
    start = end - timedelta(days=30)
    p = await r.run_report("escort_utilization",
                           {"start": start, "end": end}, requested_by="b17-test")
    assert p["report"] == "escort_utilization"
    assert "escorts" in p["summary"]
    print(f"{PASS} 4. escort_utilization escorts={p['summary']['escorts']}")


async def t5_payment_reconciliation():
    p = await r.run_report("payment_reconciliation", {"days": 30}, requested_by="b17-test")
    assert p["report"] == "payment_reconciliation"
    s = p["summary"]
    for k in ("matched", "unmatched", "total"):
        assert k in s
    print(f"{PASS} 5. payment_reconciliation total={s['total']} matched={s['matched']} unmatched={s['unmatched']}")


async def t6_cash_position():
    p = await r.run_report("cash_position", {"days": 30}, requested_by="b17-test")
    assert p["report"] == "cash_position"
    s = p["summary"]
    assert {"total_in", "total_out", "net"} <= set(s)
    print(f"{PASS} 6. cash_position net={s['net']:.2f}")


async def t7_cache_works():
    # Same args twice → second hit must come from cache
    p1 = await r.run_report("cash_position", {"days": 7}, requested_by="b17-test")
    p2 = await r.run_report("cash_position", {"days": 7}, requested_by="b17-test")
    assert p1.get("_cached") in (False, None)
    assert p2.get("_cached") is True, "second call should be cached"
    print(f"{PASS} 7. cache hit on second call")


async def t8_cache_bypass():
    p = await r.run_report("cash_position", {"days": 7}, requested_by="b17-test", use_cache=False)
    assert p.get("_cached") in (False, None)
    print(f"{PASS} 8. use_cache=False bypasses cache")


async def t9_unknown_report():
    try:
        await r.run_report("does_not_exist", {})
        raise AssertionError("should have raised")
    except KeyError:
        pass
    print(f"{PASS} 9. unknown report raises KeyError")


async def t10_record_audit():
    row = await fetch_one(
        "SELECT COUNT(*)::int AS c FROM fazle_report_runs WHERE requested_by='b17-test'"
    )
    assert row["c"] >= 4, f"expected ≥4 audit rows, got {row['c']}"
    print(f"{PASS} 10. audit log captured {row['c']} runs for b17-test")


async def t11_render_text():
    p = await r.run_report("daily_summary", {"date": date.today()}, requested_by="b17-test")
    txt = r.render_text(p, max_rows=5)
    assert "daily_summary" in txt and "payments_in" in txt
    print(f"{PASS} 11. render_text emits {len(txt)} chars")


async def t12_render_csv():
    p = await r.run_report("cash_position", {"days": 30}, requested_by="b17-test", use_cache=False)
    csv_out = r.render_csv(p)
    if p["rows"]:
        assert "payment_method" in csv_out
        print(f"{PASS} 12. render_csv emits {len(csv_out)} chars")
    else:
        print(f"{PASS} 12. render_csv (empty rows, ok)")


async def t13_digest_job():
    if not os.getenv("ADMIN_NUMBERS"):
        os.environ["ADMIN_NUMBERS"] = "8801880446111"
    res = await r.job_daily_admin_digest()
    assert res["status"] == "ok"
    # cleanup queue
    await execute(
        "DELETE FROM fazle_outbound_queue WHERE purpose='daily-digest' AND idempotency_key LIKE $1",
        f"daily-digest-{date.today().isoformat().replace('-','')}-%",
    )
    print(f"{PASS} 13. job_daily_admin_digest sent={res.get('sent', 0)}")


async def t14_cleanup_cache():
    # Insert expired row
    await execute(
        """INSERT INTO fazle_report_cache (cache_key, report_name, payload_json, expires_at)
           VALUES ('b17-test-expired', 'daily_summary', '{}'::jsonb, now() - INTERVAL '1 minute')"""
    )
    deleted = await r.cleanup_cache()
    assert deleted >= 1
    print(f"{PASS} 14. cleanup_cache deleted {deleted} expired rows")


async def main():
    await init_db()
    try:
        print("=== BATCH 17 REPORTS TESTS ===")
        await cleanup()
        await t1_list_reports()
        await t2_daily_summary()
        await t3_monthly_payroll()
        await t4_escort_utilization()
        await t5_payment_reconciliation()
        await t6_cash_position()
        await t7_cache_works()
        await t8_cache_bypass()
        await t9_unknown_report()
        await t10_record_audit()
        await t11_render_text()
        await t12_render_csv()
        await t13_digest_job()
        await t14_cleanup_cache()
        await cleanup()
        print("=== ALL BATCH 17 TESTS PASSED ===")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
