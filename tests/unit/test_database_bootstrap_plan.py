from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.mark.unit
def test_new_database_bootstrap_plan_is_complete_and_deterministic():
    path = Path(__file__).resolve().parents[2] / "db" / "bootstrap.py"
    spec = importlib.util.spec_from_file_location("fazle_db_bootstrap", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    steps = module.migration_steps()
    keys = [step.key for step in steps]

    assert keys[0] == "schema/000_foundation.sql"
    assert keys[-1] == "schema/900_runtime_support.sql"
    assert len(keys) == len(set(keys))
    assert any(key.startswith("core/") for key in keys)
    assert any(key.startswith("fpe/") for key in keys)
    assert not any("086_k32_recruitment_reconciliation.sql" in key for key in keys)
    assert keys == [step.key for step in module.migration_steps()]
