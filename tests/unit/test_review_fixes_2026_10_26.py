"""Regression tests for the three defects found by the 2026-10-26 full-app review.

Each test here FAILS against the pre-fix code and PASSES after the fix, so a
later change cannot silently reintroduce any of them.

  1. GET /observability/summary returned 500 on any server that had served at
     least one request (`app/main.py` bound `obs` to its own incomplete
     `_InMemoryObservability` class instead of `modules.observability`).
  2. GET /backup/status returned 500 when the backup directory was not
     creatable (`_backup_dir()` mkdirs unconditionally and the handler had no
     error handling).
  3. `modules.owner_contact_registry` resolved its CSV under a hardcoded
     "/home/azim/core", so on any other checkout the owner-contact
     suppression gate quietly failed OPEN.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── 1. /observability/summary ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_observability_summary_returns_200_after_traffic(
    client, test_db_pool, monkeypatch
):
    """The endpoint must survive having actual traffic to summarise.

    The bug only appeared once at least one HTTP request had been observed,
    because the sample list is empty on a cold server -- a startup smoke test
    could never have caught it. So this test deliberately makes requests
    FIRST, then asks for the summary.
    """
    import app.database as db
    import app.main as m
    from tests.conftest import TEST_API_KEY

    db._pool = test_db_pool

    # Some suites swap app.main.settings for a stub object, and the value
    # app.main captured at import time can differ from what the `client`
    # fixture authenticates with. Pin the key so this test does not depend on
    # whatever ran before it (it passed alone and 403'd in a full-suite run).
    monkeypatch.setattr(m.settings, "internal_api_key", TEST_API_KEY, raising=False)

    for _ in range(3):
        r = await client.get("/api/state-version")
        assert r.status_code == 200, "precondition: traffic must succeed"

    resp = await client.get("/observability/summary")
    assert resp.status_code == 200, (
        f"/observability/summary failed with {resp.status_code}; "
        "the summary reader is out of sync with the metrics store again"
    )

    body = resp.json()
    # Every key the handler reads must actually be present.
    for key in ("uptime_s", "http_total", "http_by_status", "http_avg_ms", "top_paths"):
        assert key in body, f"missing {key!r} in observability summary"

    assert isinstance(body["uptime_s"], (int, float)), (
        "uptime_s should be a number, not a KeyError"
    )
    # We just made at least 3 requests, so they must be counted.
    assert body["http_total"] >= 3, (
        f"expected our requests to be counted, got http_total={body['http_total']}"
    )


def test_obs_is_the_shared_implementation():
    """`obs` must be the complete module, not a partial copy in app.main."""
    from app.main import obs

    assert obs.__name__ == "modules.observability", (
        f"app.main.obs is {obs.__name__!r}. A second, partial in-file copy was "
        "the root cause of the /observability/summary 500s: it stored samples "
        "as {labels, value} and had no uptime_s/gauges."
    )

    obs.inc("test_probe_total", labels={"probe": "1"})
    obs.observe("fazle_http_request_duration_ms", 12.5, labels={"path": "/probe"})
    snap = obs.snapshot()

    assert "uptime_s" in snap, "snapshot() must expose uptime_s"
    sample = snap["histograms"]["fazle_http_request_duration_ms"][0]
    for key in ("count", "sum_ms"):
        assert key in sample, (
            f"histogram sample missing {key!r}: {sample}. "
            "/observability/summary reads d['count'] and d['sum_ms']."
        )


# ── 2. /backup/status ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_backup_status_reports_unusable_dir_instead_of_raising(monkeypatch):
    """An unusable backup directory must be reported, not raise.

    BACKUP_DIR defaults to "/home/azim/backups", which does not exist (and
    cannot be created) off the original VPS. _backup_dir() mkdirs
    unconditionally, so this path used to raise PermissionError and the
    endpoint answered 500.
    """
    from modules import backup as b

    def _boom() -> Path:
        raise PermissionError("[Errno 13] Permission denied: '/home/azim'")

    monkeypatch.setattr(b, "_backup_dir", _boom)

    try:
        status = await b.backup_status()
    except OSError as e:  # pragma: no cover - this is the regression
        pytest.fail(f"backup_status() raised {type(e).__name__}: {e}")

    assert status["status"] == "error", f"expected status='error', got {status!r}"
    assert "error" in status and status["error"]
    # Callers read these keys; they must still be present so existing
    # dashboards and the admin command do not break.
    for key in ("latest", "files_on_disk", "total_bytes", "newest_age_h", "dir"):
        assert key in status, f"missing {key!r} in degraded backup status"

    # The admin-facing text must surface the real cause, not pretend that no
    # backup has run yet.
    text = b.render_status_text(status)
    assert "পাওয়া যাচ্ছে না" in text or "unavailable" in text.lower(), (
        f"render_status_text hid the failure: {text!r}"
    )
    assert "Permission denied" in text, f"cause not shown to the admin: {text!r}"


@pytest.mark.asyncio
async def test_backup_status_still_works_normally(monkeypatch, tmp_path):
    """The happy path must be unchanged by the error handling."""
    from modules import backup as b

    monkeypatch.setattr(b, "_backup_dir", lambda: tmp_path)

    status = await b.backup_status()
    assert "error" not in status, f"unexpected error on a writable dir: {status!r}"
    assert status["files_on_disk"] == 0
    assert status["dir"] == str(tmp_path)


# ── 3. owner_contact_registry ─────────────────────────────────────────────────

def test_owner_contact_registry_resolves_csv_from_this_checkout():
    """The CSV path must be derived from the checkout, not hardcoded.

    With the old "/home/azim/core" literal, the CSV was missing on any other
    machine: the registry loaded 0 numbers and is_owner_managed_contact()
    answered False for everything -- the suppression gate failed OPEN, and
    owners' personal contacts lost their no-auto-reply protection.
    """
    from modules import owner_contact_registry as reg

    expected = REPO_ROOT / "resources" / "ops" / "selected_contacts_normalized_unique.csv"
    assert Path(reg._CSV_PATH) == expected, (
        f"CSV path is not inside this checkout: {reg._CSV_PATH}"
    )
    assert expected.exists(), f"CSV missing at {expected}"

    reg.reload_registry()
    size = reg.registry_size()
    assert size > 0, (
        "registry loaded 0 contacts -- the CSV was not found, so every "
        "is_owner_managed_contact() call silently returns False (fail-open)"
    )
    assert reg._load_error is None, f"registry reported a load error: {reg._load_error}"

    # A number that is genuinely on the first data row of the CSV must be
    # recognised. This is the assertion that actually pins the fail-open bug.
    import csv

    with open(expected, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    probe = (rows[0].get("Phone Number") or "").strip()
    assert probe, "CSV has no phone in its first row; test cannot probe"
    assert reg.is_owner_managed_contact(probe) is True, (
        f"{probe!r} is in the CSV but was not recognised -- the gate is failing open"
    )
