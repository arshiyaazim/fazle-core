"""Isolated contract tests for the Vessel Register/Core read-only boundary."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest


def test_draft_preview_is_explicitly_non_mutating():
    from modules.vessel_register_context import render_draft_preview

    preview = render_draft_preview(
        "escort_assignment_confirmation",
        {"vessel": "MV Test", "destination": "Chattogram", "shift": "D"},
    )

    assert preview["draft_only"] is True
    assert preview["approved"] is False
    assert preview["sent"] is False
    assert preview["posted"] is False
    assert "MV Test" in preview["body"]


def test_operational_context_has_no_write_or_send_dependencies():
    from modules import vessel_register_context

    source = inspect.getsource(vessel_register_context)
    assert "fetch_all" in source
    assert "execute(" not in source
    assert "enqueue(" not in source
    assert "send(" not in source
    assert "create_transaction" not in source


def test_unknown_template_fails_closed():
    from modules.vessel_register_context import render_draft_preview

    with pytest.raises(ValueError):
        render_draft_preview("unknown", {})


def test_read_key_and_internal_key_must_be_distinct():
    from app.config import Settings

    with pytest.raises(ValueError, match="FAZLE_CORE_READ_KEY"):
        Settings(
            database_url="postgresql://test",
            internal_api_key="same-secret",
            fazle_core_read_key="same-secret",
        )


@pytest.mark.asyncio
async def test_missing_or_invalid_read_key_is_rejected(monkeypatch):
    from fastapi import HTTPException
    from modules.fazle_payroll_engine import routes

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(fazle_core_read_key="read-secret", internal_api_key="internal-secret"),
    )

    async def reject(_key):
        raise HTTPException(status_code=403, detail="viewer role or above required")

    monkeypatch.setattr(routes, "_require_viewer_or_above", reject)
    assert await routes._require_core_read_scope("read-secret") == "read-secret"
    with pytest.raises(HTTPException) as missing:
        await routes._require_core_read_scope(None)
    assert missing.value.status_code == 403
    with pytest.raises(HTTPException) as invalid:
        await routes._require_core_read_scope("wrong-secret")
    assert invalid.value.status_code == 403


@pytest.mark.asyncio
async def test_read_key_is_not_accepted_by_generic_mutation_auth(monkeypatch):
    from fastapi import HTTPException
    from modules.fazle_payroll_engine import routes

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(fazle_core_read_key="read-secret", internal_api_key="internal-secret"),
    )
    with pytest.raises(HTTPException) as exc:
        await routes._require_api_key("read-secret")
    assert exc.value.status_code == 403


def test_read_key_dependency_is_attached_only_to_read_routes():
    from modules.fazle_payroll_engine import routes

    for path in ("/health", "/transactions", "/transactions/{txn_id}",
                 "/employees/search", "/unmatched", "/stats"):
        route = next(item for item in routes.router.routes if item.path == f"/api/fpe{path}")
        dependency_names = {
            getattr(getattr(dep, "dependency", None), "__name__", "")
            for dep in route.dependencies
        }
        assert "_require_core_read_scope" in dependency_names

    mutation_paths = {"/api/fpe/ingest", "/api/fpe/transactions/manual"}
    for route in routes.router.routes:
        if route.path in mutation_paths:
            dependency_names = {
                getattr(getattr(dep, "dependency", None), "__name__", "")
                for dep in route.dependencies
            }
            assert "_require_core_read_scope" not in dependency_names


def test_unmatched_read_route_does_not_cleanup_or_delete():
    from modules.fazle_payroll_engine import routes

    source = inspect.getsource(routes.list_unmatched)
    assert "_cleanup_stale_review_queue_rows" not in source
    assert "DELETE FROM" not in source
    assert "UPDATE " not in source


def test_operational_context_is_bounded_and_read_only():
    from modules import vessel_register_context

    source = inspect.getsource(vessel_register_context.build_operational_context)
    assert "asyncio.wait_for" in source
    assert "LIMIT 6" in source
    assert "no assignment selected" in source
    assert "payout_phone" not in source


@pytest.mark.asyncio
async def test_context_disabled_preserves_existing_message_path(monkeypatch):
    from app import config, database
    from modules.vessel_register_context import build_operational_context

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            vessel_register_context_enabled=False,
            vessel_register_context_timeout_seconds=0.01,
        ),
    )

    async def unexpected_query(*_args, **_kwargs):
        raise AssertionError("disabled context must not query the database")

    monkeypatch.setattr(database, "fetch_all", unexpected_query)
    assert await build_operational_context(text="lighter MV TEST duty") == ""


@pytest.mark.asyncio
async def test_context_timeout_or_upstream_failure_is_non_blocking(monkeypatch):
    from app import config, database
    from modules.vessel_register_context import build_operational_context

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            vessel_register_context_enabled=True,
            vessel_register_context_timeout_seconds=0.01,
        ),
    )

    async def timed_out(*_args, **_kwargs):
        raise TimeoutError("synthetic upstream timeout")

    monkeypatch.setattr(database, "fetch_all", timed_out)
    assert await build_operational_context(text="lighter MV TEST duty") == ""


@pytest.mark.asyncio
async def test_separate_voyages_are_not_collapsed_into_one_assignment(monkeypatch):
    from app import config, database
    from modules.vessel_register_context import build_operational_context

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            vessel_register_context_enabled=True,
            vessel_register_context_timeout_seconds=0.1,
        ),
    )
    rows = [
        {
            "program_id": 101,
            "mother_vessel": "MV TEST",
            "lighter_vessel": "LT SAME",
            "destination": "Chattogram",
            "start_date": "2026-10-01",
            "end_date": "2026-10-01",
            "start_shift": "D",
            "end_shift": "D",
            "status": "cancelled",
        },
        {
            "program_id": 102,
            "mother_vessel": "MV TEST",
            "lighter_vessel": "LT SAME",
            "destination": "Chattogram",
            "start_date": "2026-10-02",
            "end_date": "2026-10-02",
            "start_shift": "N",
            "end_shift": "N",
            "status": "released",
        },
    ]

    async def fake_fetch(*_args, **_kwargs):
        return rows

    monkeypatch.setattr(database, "fetch_all", fake_fetch)
    result = await build_operational_context(text="lighter LT SAME")
    assert "program_id=101" in result
    assert "program_id=102" in result
    assert "reason=multiple_voyage_matches" in result
    assert "no assignment selected" in result
