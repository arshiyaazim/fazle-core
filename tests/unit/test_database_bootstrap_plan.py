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

    assert keys[0] == "core/029_bootstrap_core_tables_schema_record.sql"
    assert keys[1] == "schema/000_foundation.sql"
    assert keys[-1] == "schema/900_runtime_support.sql"
    assert len(keys) == len(set(keys))
    assert any(key.startswith("core/") for key in keys)
    assert any(key.startswith("fpe/") for key in keys)
    assert not any("086_k32_recruitment_reconciliation.sql" in key for key in keys)
    compat = keys.index("bootstrap_compat/003c_schema_align_pre.sql")
    assert keys[compat + 1] == "core/003c_schema_align.sql"
    role_compat = keys.index("bootstrap_compat/012_ai_readonly_views_pre.sql")
    assert keys[role_compat + 1] == "core/012_ai_readonly_views.sql"
    history = keys.index("legacy_prerequisite/escort_history_schema.sql")
    assert keys[history + 1] == "core/024_escort_history_fk.sql"
    assert keys == [step.key for step in module.migration_steps()]

    manifest = module._expected_manifest()
    assert list(manifest) == keys
    assert all(len(checksum) == 64 for checksum in manifest.values())
