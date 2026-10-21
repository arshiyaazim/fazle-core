"""Regression tests for the ``fazle_`` prefix unification (2026-10-21).

The unification renamed seven database tables and thirteen module paths onto a
single ``fazle_`` prefix.  These tests lock the outcome in so a later change
cannot silently reintroduce a legacy table name, drop one of the deliberately
preserved column names, break a backward-compatibility shim, or turn one of
the rename migrations into something that is not idempotent.

Design notes
------------
* Only the seven tables listed in :data:`TABLE_RENAMES` are in scope.  The
  other legacy-prefixed tables (39 of them) were explicitly left alone by the
  owner decision recorded in ``audits/prefix_unification_inventory.md`` and
  are listed in :data:`OUT_OF_SCOPE_TABLES`.
* Column names are deliberately NOT renamed, so identifiers such as
  ``wbom_employee_id`` and ``fpe_wa_message_id`` legitimately remain.  They
  are pinned by :data:`PROTECTED_COLUMN_NAMES`.
* The seven ``*_unify_rename_*.sql`` migrations MUST keep the old table names
  in their ``ALTER TABLE ... RENAME TO`` statements, so they are excluded
  from the "no legacy name in source" scan.
* The backward-compatibility shims under the old module paths are excluded
  from the scans for the same reason.
"""
from __future__ import annotations

import importlib
import re
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------
# The maps
# --------------------------------------------------------------------------

#: old table name -> new table name (the seven in-scope renames)
TABLE_RENAMES: dict[str, str] = {
    "wbom_whatsapp_messages": "fazle_whatsapp_messages",
    "wbom_contacts": "fazle_contacts",
    "wbom_cash_transactions": "fazle_cash_transactions_archive",
    "wbom_employees": "fazle_employees_legacy",
    "fpe_cash_transactions": "fazle_cash_transactions",
    "fpe_employee_ledger": "fazle_employee_ledger",
    "fpe_employees": "fazle_employees",
}

#: old module path (repo-relative) -> new module path (repo-relative)
MODULE_RENAMES: dict[str, str] = {
    "modules/payment_ingest": "modules/fazle_payment_ingest",
    "modules/payment_ingest/fpe_bridge.py": "modules/fazle_payment_ingest/fpe_bridge.py",
    "modules/payment_ingest/wbom_fpe_sync.py": "modules/fazle_data_sync/__init__.py",
    "modules/payment_workflow": "modules/fazle_payment_workflow",
    "modules/bridge_poller": "modules/fazle_bridge_poller",
    "modules/message_archive": "modules/fazle_message_archive",
    "modules/media_normalization": "modules/fazle_media_normalization",
    "modules/identity_resolver.py": "modules/fazle_identity_resolver.py",
    "modules/identity_brain": "modules/fazle_identity_brain",
    "modules/identity_brain/claim_verification.py": "modules/fazle_identity_brain/claim_verification.py",
    "modules/admin_commands": "modules/fazle_admin_commands",
    "modules/admin_commands/date_parser.py": "modules/fazle_admin_commands/date_parser.py",
    "modules/admin_commands/nl_advance_record.py": "modules/fazle_admin_commands/nl_advance_record.py",
    "modules/admin_commands/nl_employee_stats.py": "modules/fazle_admin_commands/nl_employee_stats.py",
    "modules/admin_commands/nl_outbound.py": "modules/fazle_admin_commands/nl_outbound.py",
    "modules/admin_commands/nl_payments.py": "modules/fazle_admin_commands/nl_payments.py",
    "modules/admin_commands/nl_router.py": "modules/fazle_admin_commands/nl_router.py",
    "modules/admin_commands/nl_search.py": "modules/fazle_admin_commands/nl_search.py",
    "modules/draft_approval": "modules/fazle_draft_approval",
    "modules/draft_approval/routes.py": "modules/fazle_draft_approval/routes.py",
    "modules/group_identity.py": "modules/fazle_group_identity.py",
    "modules/intent": "modules/fazle_intent",
    "modules/image_hash": "modules/fazle_image_hash",
}

#: Column / identifier names that were deliberately NOT renamed.
PROTECTED_COLUMN_NAMES = {
    "wbom_employee_id",
    "wbom_employee_name",
    "wbom_employee_mobile",
    "wbom_id",
    "wbom_txn_id",
    "fpe_id",
    "fpe_employee_id",
    "fpe_wa_message_id",
    "legacy_wbom_transaction_id",
}

#: The seven rename migrations (they must keep the old table names).
UNIFY_MIGRATION_FILES = [
    "090_unify_rename_wbom_whatsapp_messages.sql",
    "091_unify_rename_wbom_contacts.sql",
    "092_unify_rename_wbom_cash_transactions_archive.sql",
    "093_unify_rename_wbom_employees_legacy.sql",
    "094_unify_rename_fpe_cash_transactions.sql",
    "095_unify_rename_fpe_employee_ledger.sql",
    "096_unify_rename_fpe_employees.sql",
]

#: Directories scanned for residual legacy names.
SCAN_AREAS = ["app", "modules", "shared", "scripts", "db/migrations", "tests"]

#: File suffixes considered "source" for the scans.
TEXT_SUFFIXES = {".py", ".sql", ".md", ".txt", ".yaml", ".yml", ".json", ".html", ".sh"}

#: Directories never descended into.
SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "htmlcov", "coverage", "dist", "build",
}

#: This file itself (it names the old tables on purpose).
SELF_FILE = "tests/test_prefix_unification.py"

#: A legacy token only counts when it is a standalone identifier -- ``fpe_``
#: inside ``unresolved_fpe_employees`` is part of an API route name, not a
#: table reference.
_LEGACY_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])(wbom_[A-Za-z0-9_]*|fpe_[A-Za-z0-9_]*)(?![A-Za-z0-9_])"
)


OUT_OF_SCOPE_TABLES = {
    "fpe_accounting_audit_logs",
    "fpe_employee_aliases",
    "fpe_employee_edit_requests",
    "fpe_employee_resolution_links",
    "fpe_employee_review_queue",
    "fpe_gap_scan_runs",
    "fpe_income_transactions",
    "fpe_message_processing_state",
    "fpe_normalization_audit_logs",
    "fpe_parser_results",
    "fpe_processing_diagnostics",
    "fpe_review_audit_logs",
    "fpe_sync_checkpoints",
    "fpe_transaction_repairs",
    "fpe_unmatched_messages",
    "fpe_wa_messages",
    "wbom_attendance",
    "wbom_billing_payment_log",
    "wbom_billing_records",
    "wbom_business_types",
    "wbom_candidate_conversations",
    "wbom_candidates",
    "wbom_cases",
    "wbom_client_billing_profiles",
    "wbom_client_statuses",
    "wbom_client_tiers",
    "wbom_employee_requests",
    "wbom_escort_programs",
    "wbom_group_identities",
    "wbom_identity_links",
    "wbom_message_templates",
    "wbom_payroll_approval_log",
    "wbom_payroll_run_items",
    "wbom_payroll_runs",
    "wbom_recruitment_reminders",
    "wbom_relation_types",
    "wbom_salary_records",
    "wbom_staging_payments",
    "wbom_unmatched_confirmations",
}

LEGACY_IDENTIFIERS = {
    "fpe_",
    "fpe_accounting",
    "fpe_accounting_audit",
    "fpe_aliases_unique",
    "fpe_api_key",
    "fpe_available",
    "fpe_bridge",
    "fpe_bridge_gap_minutes",
    "fpe_bridge_health",
    "fpe_bridge_last_hour_count",
    "fpe_by_phone",
    "fpe_cash_authorized_phone_list",
    "fpe_cash_authorized_phones",
    "fpe_changes",
    "fpe_checkpoint_unique",
    "fpe_dlq_backlog",
    "fpe_dlq_count",
    "fpe_emp",
    "fpe_employee",
    "fpe_employee_id",
    "fpe_engine",
    "fpe_gap_scan_backfilled_total",
    "fpe_gap_scan_last_missing",
    "fpe_gap_scan_missing_total",
    "fpe_gapscan",
    "fpe_health",
    "fpe_health_watchdog",
    "fpe_health_worker",
    "fpe_hsync",
    "fpe_id",
    "fpe_id_1",
    "fpe_id_2",
    "fpe_identity_anomalies",
    "fpe_identity_anomalies_occurrence_count_positive",
    "fpe_identity_anomalies_resolved_fields_consistent",
    "fpe_income_authorized_phone_list",
    "fpe_income_authorized_phones",
    "fpe_link",
    "fpe_list_transactions",
    "fpe_manual_sync",
    "fpe_mps_unique",
    "fpe_msg_id",
    "fpe_msg_processor",
    "fpe_name",
    "fpe_overview",
    "fpe_params",
    "fpe_payment_drafts",
    "fpe_pending_review_count",
    "fpe_processed_1h",
    "fpe_readonly_view",
    "fpe_resolution_no_self",
    "fpe_resolution_unique",
    "fpe_retry_storm_count",
    "fpe_review_no_self",
    "fpe_reviewer",
    "fpe_router",
    "fpe_routes",
    "fpe_row",
    "fpe_rows",
    "fpe_seeded",
    "fpe_set_parts",
    "fpe_skip_ratio_1h",
    "fpe_sql",
    "fpe_sync_chat_jids",
    "fpe_sync_fields",
    "fpe_table",
    "fpe_transactions",
    "fpe_txn",
    "fpe_txn_id",
    "fpe_type_status_count",
    "fpe_wa_message_id",
    "fpe_wa_messages_unique",
    "wbom_",
    "wbom_backfill_011",
    "wbom_billing_records_program_id_fkey",
    "wbom_changes",
    "wbom_col",
    "wbom_contact",
    "wbom_contacts_delete_result",
    "wbom_count",
    "wbom_create_link_spa",
    "wbom_direction",
    "wbom_emp",
    "wbom_employee",
    "wbom_employee_id",
    "wbom_employee_mobile",
    "wbom_employee_name",
    "wbom_fpe_sync",
    "wbom_freeze",
    "wbom_id",
    "wbom_id_1",
    "wbom_id_2",
    "wbom_inbound_messages",
    "wbom_job_applications",
    "wbom_link_review_spa",
    "wbom_match",
    "wbom_match_id",
    "wbom_match_mobile",
    "wbom_match_name",
    "wbom_match_unlinked",
    "wbom_match_unlinked_count",
    "wbom_migration",
    "wbom_name",
    "wbom_phone_match",
    "wbom_received_at",
    "wbom_recruitment_",
    "wbom_role",
    "wbom_row",
    "wbom_status",
    "wbom_txn",
    "wbom_txn_id",
    "wbom_unmatched_confirmations_status_check",
    "wbom_update_calls",
    "wbom_write_check_failed",
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _iter_source_files():
    """Yield (repo_relative_path, text) for every scannable source file."""
    for area in SCAN_AREAS:
        base = REPO_ROOT / area
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel == SELF_FILE:
                continue
            if path.name in UNIFY_MIGRATION_FILES:
                # These must keep the old names -- that is the whole point.
                continue
            if rel == "scripts/verify_prefix_unification.sql":
                # The verification script checks for the old names on purpose.
                continue
            yield rel, path.read_text(encoding="utf-8", errors="replace")


def _shim_paths() -> set[str]:
    """Repo-relative paths of the backward-compatibility shims."""
    out = set()
    for old in MODULE_RENAMES:
        out.add(old)
        if not old.endswith(".py"):
            out.add(f"{old}/__init__.py")
    return out


def _strip_sql_comments(text: str) -> str:
    """Remove ``--`` line comments so prose is not parsed as SQL."""
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def _dotted(path: str) -> str:
    """Repo-relative path -> importable dotted module name."""
    if path.endswith(".py"):
        path = path[:-3]
    dotted = path.replace("/", ".")
    if dotted.endswith(".__init__"):
        dotted = dotted[: -len(".__init__")]
    return dotted


# --------------------------------------------------------------------------
# 1. The seven renamed tables
# --------------------------------------------------------------------------


@pytest.mark.unit
class TestRenamedTables:
    def test_no_legacy_table_name_remains_in_source(self):
        """None of the seven legacy table names may appear in source again."""
        offenders: dict[str, list[str]] = {}
        for rel, text in _iter_source_files():
            for old in TABLE_RENAMES:
                pattern = re.compile(
                    r"(?<![A-Za-z0-9_])" + re.escape(old) + r"(?![A-Za-z0-9_])"
                )
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    offenders.setdefault(old, []).append(f"{rel}:{line}")
        assert not offenders, (
            "legacy table names re-introduced in source: "
            + "; ".join(f"{k} -> {v[:5]}" for k, v in offenders.items())
        )

    def test_new_table_names_are_actually_used(self):
        """Every new table name must be referenced somewhere in the source."""
        corpus = "\n".join(text for _rel, text in _iter_source_files())
        missing = [
            new
            for new in TABLE_RENAMES.values()
            if not re.search(
                r"(?<![A-Za-z0-9_])" + re.escape(new) + r"(?![A-Za-z0-9_])", corpus
            )
        ]
        assert not missing, f"new table names never referenced in source: {missing}"

    def test_column_names_were_not_renamed(self):
        """Column names carrying the legacy prefix are intentionally preserved."""
        corpus = "\n".join(text for _rel, text in _iter_source_files())
        for column in PROTECTED_COLUMN_NAMES:
            assert re.search(
                r"(?<![A-Za-z0-9_])" + re.escape(column) + r"(?![A-Za-z0-9_])", corpus
            ), f"protected column name {column!r} disappeared from the source"

    def test_only_allow_listed_legacy_tokens_remain(self):
        """Every remaining standalone ``wbom_``/``fpe_`` token must be expected."""
        allowed = OUT_OF_SCOPE_TABLES | LEGACY_IDENTIFIERS
        unknown: dict[str, set[str]] = {}
        for rel, text in _iter_source_files():
            for token in _LEGACY_TOKEN_RE.findall(text):
                if token in allowed:
                    continue
                unknown.setdefault(token, set()).add(rel)
        assert not unknown, (
            "unexpected legacy tokens still present: "
            + ", ".join(f"{k} ({sorted(v)[0]})" for k, v in sorted(unknown.items()))
        )


# --------------------------------------------------------------------------
# 2. The renamed module paths
# --------------------------------------------------------------------------


@pytest.mark.unit
class TestRenamedModules:
    @pytest.mark.parametrize("old,new", sorted(MODULE_RENAMES.items()))
    def test_new_module_path_exists(self, old, new):
        assert (REPO_ROOT / new).exists(), f"new module path {new} is missing"

    @pytest.mark.parametrize("old,new", sorted(MODULE_RENAMES.items()))
    def test_old_module_path_still_importable(self, old, new):
        """The old path must still import (backward compatibility)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            old_mod = importlib.import_module(_dotted(old))
            new_mod = importlib.import_module(_dotted(new))
        assert old_mod is not None and new_mod is not None

    @pytest.mark.parametrize("old,new", sorted(MODULE_RENAMES.items()))
    def test_old_module_path_is_a_deprecation_shim(self, old, new):
        """The old path must be a thin shim that warns on attribute access."""
        rel = old if old.endswith(".py") else f"{old}/__init__.py"
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "DeprecationWarning" in text, f"{rel} does not warn"
        assert "Backward-compatibility shim" in text
        assert _dotted(new) in text, f"{rel} does not point at {new}"

    def test_no_old_module_import_path_remains(self):
        """Source must import the new module paths, not the old ones."""
        offenders: dict[str, list[str]] = {}
        shims = _shim_paths()
        old_dotted = {_dotted(old) for old in MODULE_RENAMES}
        alt = "|".join(re.escape(m) for m in sorted(old_dotted, key=len, reverse=True))
        # `import modules.foo` / `from modules.foo import ...`
        dotted_pattern = re.compile(r"(?:from|import)\s+(" + alt + r")(?![A-Za-z0-9_])")
        # `from modules import foo` -- only the IMPORTED NAME counts, not the
        # local alias (`from modules import fazle_admin_commands as
        # admin_commands` is a legitimate new-path import).
        from_modules_pattern = re.compile(r"from\s+modules\s+import\s+([^\n(]+)")
        base_names = {m.split(".")[-1] for m in old_dotted}
        for rel, text in _iter_source_files():
            if rel in shims:
                continue
            for match in dotted_pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offenders.setdefault(match.group(1), []).append(f"{rel}:{line}")
            for match in from_modules_pattern.finditer(text):
                for part in match.group(1).split(","):
                    imported = part.strip().split(" as ")[0].strip()
                    if imported in base_names:
                        line = text.count("\n", 0, match.start()) + 1
                        offenders.setdefault(imported, []).append(f"{rel}:{line}")
        assert not offenders, (
            "old module import paths still used: "
            + "; ".join(f"{k} -> {v[:5]}" for k, v in offenders.items())
        )


# --------------------------------------------------------------------------
# 3. The rename migrations
# --------------------------------------------------------------------------


@pytest.mark.unit
class TestRenameMigrations:
    @pytest.mark.parametrize("filename", UNIFY_MIGRATION_FILES)
    def test_migration_file_exists(self, filename):
        assert (REPO_ROOT / "db" / "migrations" / filename).is_file()

    @pytest.mark.parametrize(
        "filename,old,new",
        [
            ("090_unify_rename_wbom_whatsapp_messages.sql", "wbom_whatsapp_messages", "fazle_whatsapp_messages"),
            ("091_unify_rename_wbom_contacts.sql", "wbom_contacts", "fazle_contacts"),
            ("092_unify_rename_wbom_cash_transactions_archive.sql", "wbom_cash_transactions", "fazle_cash_transactions_archive"),
            ("093_unify_rename_wbom_employees_legacy.sql", "wbom_employees", "fazle_employees_legacy"),
            ("094_unify_rename_fpe_cash_transactions.sql", "fpe_cash_transactions", "fazle_cash_transactions"),
            ("095_unify_rename_fpe_employee_ledger.sql", "fpe_employee_ledger", "fazle_employee_ledger"),
            ("096_unify_rename_fpe_employees.sql", "fpe_employees", "fazle_employees"),
        ],
    )
    def test_migration_renames_the_right_table(self, filename, old, new):
        text = (REPO_ROOT / "db" / "migrations" / filename).read_text(encoding="utf-8")
        assert f"ALTER TABLE IF EXISTS {old} RENAME TO {new};" in text, (
            f"{filename} does not perform the expected guarded rename"
        )

    @pytest.mark.parametrize("filename", UNIFY_MIGRATION_FILES)
    def test_migration_is_idempotent(self, filename):
        """No unguarded RENAME / no DROP / no TRUNCATE in the forward section."""
        text = (REPO_ROOT / "db" / "migrations" / filename).read_text(encoding="utf-8")
        body = _strip_sql_comments(_rollback_free(text))
        assert not re.search(r"\bDROP\s+TABLE\b", body, re.IGNORECASE), f"{filename} drops a table"
        assert not re.search(r"\bTRUNCATE\b", body, re.IGNORECASE), f"{filename} truncates a table"
        unguarded = re.findall(r"ALTER\s+TABLE\s+(?!IF\s+EXISTS)([^\n;]+);", body, re.IGNORECASE)
        assert not unguarded, f"{filename} has unguarded ALTER TABLE statements: {unguarded}"

    @pytest.mark.parametrize("filename", UNIFY_MIGRATION_FILES)
    def test_migration_has_rollback_section(self, filename):
        text = (REPO_ROOT / "db" / "migrations" / filename).read_text(encoding="utf-8")
        assert "ROLLBACK-SQL-BEGIN" in text and "ROLLBACK-SQL-END" in text, (
            f"{filename} has no marked rollback section"
        )


def _rollback_free(text: str) -> str:
    """Return the forward (executable) part of a migration file."""
    begin = text.find("ROLLBACK-SQL-BEGIN")
    if begin == -1:
        return text
    return text[:begin]


# --------------------------------------------------------------------------
# 4. The live database
# --------------------------------------------------------------------------


@pytest.mark.db
class TestLiveSchema:
    async def test_new_tables_exist(self, test_db_pool):
        async with test_db_pool.acquire() as conn:
            for new in TABLE_RENAMES.values():
                row = await conn.fetchrow("SELECT to_regclass($1) AS reg", new)
                assert row["reg"] is not None, f"new table {new} does not exist"

    async def test_old_tables_are_gone(self, test_db_pool):
        async with test_db_pool.acquire() as conn:
            for old in TABLE_RENAMES:
                row = await conn.fetchrow("SELECT to_regclass($1) AS reg", old)
                assert row["reg"] is None, f"legacy table {old} still exists"

    async def test_dependent_objects_carry_the_new_prefix(self, test_db_pool):
        async with test_db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.relname FROM pg_class c
                WHERE c.relkind IN ('r', 'S')
                  AND c.relname = ANY($1::text[])
                """,
                list(TABLE_RENAMES.keys()),
            )
            stale = sorted(r["relname"] for r in rows)
            assert not stale, f"legacy relations still present: {stale}"


# --------------------------------------------------------------------------
# 5. The verification query file and the audit report
# --------------------------------------------------------------------------


@pytest.mark.unit
class TestDeliverables:
    def test_verification_sql_exists(self):
        path = REPO_ROOT / "scripts" / "verify_prefix_unification.sql"
        assert path.is_file(), "scripts/verify_prefix_unification.sql is missing"

    def test_verification_sql_covers_every_renamed_table(self):
        text = (REPO_ROOT / "scripts" / "verify_prefix_unification.sql").read_text(encoding="utf-8")
        for old, new in TABLE_RENAMES.items():
            assert old in text, f"verification script never mentions {old}"
            assert new in text, f"verification script never mentions {new}"

    def test_audit_report_exists(self):
        path = REPO_ROOT / "audits" / "prefix_unification_2026-10-21.md"
        assert path.is_file(), "audits/prefix_unification_2026-10-21.md is missing"

    def test_migration_inventory_lists_the_new_migrations(self):
        text = (REPO_ROOT / "db" / "MIGRATION_INVENTORY.md").read_text(encoding="utf-8")
        for filename in UNIFY_MIGRATION_FILES:
            assert filename in text, f"MIGRATION_INVENTORY.md does not list {filename}"
