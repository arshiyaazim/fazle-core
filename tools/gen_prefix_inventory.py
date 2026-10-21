#!/usr/bin/env python3
"""
Generate audits/prefix_unification_inventory.md — the STEP 1 pre-change
inventory for the `fazle_` prefix unification.

Scans the repository for every occurrence of the legacy prefixes `wbom_`
and `fpe_`, classifies each hit, and emits a complete per-file
(file + line numbers + matched tokens) inventory plus a raw appendix.

Usage:
    python tools/gen_prefix_inventory.py [--repo-root .] [--out <path>]

This is a one-shot discovery tool; it is safe to re-run and never mutates
anything except the output file.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
from collections import defaultdict
from pathlib import Path

# ── Scope ────────────────────────────────────────────────────────────────────
SCAN_EXTS = {".py", ".sql", ".md", ".txt", ".yaml", ".yml", ".json"}
SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "htmlcov", "coverage", "dist", "build",
}
# Extra extensions inventoried but flagged separately (not part of the
# STEP 1a grep contract).
EXTRA_EXTS = {".html", ".sh", ".cfg", ".ini", ".toml"}

# Matches the STEP 1 grep (`wbom_` / `fpe_` as plain substrings) so the
# inventory covers every hit the grep reports — including boundary-prefixed
# occurrences such as `__fpe_override__`.
TOKEN_RE = re.compile(r"(wbom_[A-Za-z0-9_]*|fpe_[A-Za-z0-9_]*)")

# ── The seven in-scope table renames from the task's EXACT RENAMING MAP ─────
IN_SCOPE_TABLES = {
    "wbom_whatsapp_messages": "fazle_whatsapp_messages",
    "wbom_contacts": "fazle_contacts",
    "wbom_cash_transactions": "fazle_cash_transactions_archive",
    "wbom_employees": "fazle_employees_legacy",
    "fpe_cash_transactions": "fazle_cash_transactions",
    "fpe_employee_ledger": "fazle_employee_ledger",
    "fpe_employees": "fazle_employees",
}

# ── Module rename map ────────────────────────────────────────────────────────
IN_SCOPE_MODULES = {
    "modules/wbom_fpe_sync": "modules/fazle_data_sync",
    "modules/payment_ingest": "modules/fazle_payment_ingest",
    "modules/payment_workflow": "modules/fazle_payment_workflow",
    "modules/bridge_poller": "modules/fazle_bridge_poller",
    "modules/message_archive": "modules/fazle_message_archive",
    "modules/media_normalization": "modules/fazle_media_normalization",
    "modules/identity_resolver": "modules/fazle_identity_resolver",
    "modules/identity_brain": "modules/fazle_identity_brain",
    "modules/admin_commands": "modules/fazle_admin_commands",
    "modules/draft_approval": "modules/fazle_draft_approval",
    "modules/group_identity": "modules/fazle_group_identity",
    "modules/intent": "modules/fazle_intent",
    "modules/image_hash": "modules/fazle_image_hash",
}

# ── Column / identifier names that MUST NOT be renamed (HARD CONSTRAINT #4) ──
# These are columns, Python parameter names, metric names, or index/constraint
# names. They legitimately carry the legacy prefix and are OUT of the rename map.
KNOWN_COLUMN_TOKENS = {
    "wbom_employee_id", "wbom_employee_name", "wbom_employee_mobile",
    "wbom_employee", "wbom_emp", "wbom_emp_phone_unique", "wbom_id",
    "wbom_txn_id", "wbom_transaction_id", "wbom_received_at", "wbom_direction",
    "wbom_name", "wbom_mobile", "wbom_role", "wbom_status", "wbom_col",
    "wbom_match", "wbom_match_id", "wbom_match_name", "wbom_match_mobile",
    "wbom_match_unlinked", "wbom_match_unlinked_count", "wbom_match_count",
    "wbom_match_is_resolved", "wbom_match_stays_unresolved",
    "wbom_phone_match", "wbom_messages_hash", "wbom_msg_intent",
    "wbom_msg_conv_key", "wbom_msg_status", "wbom_msg_received_at",
    "wbom_msg_platform", "wbom_msg_platform_direction",
    "wbom_msg_contact_identifier", "wbom_msg_canonical_key",
    "wbom_msg_actor_type", "wbom_msg_meta_source_ref", "wbom_msg_meta_wamid",
    "wbom_msg_workflow_triggered", "wbom_msg_autofill",
    "wbom_messages_sender", "wbom_messages_class", "wbom_messages_sender_name_source",
    "wbom_messages_received", "wbom_messages_phone_last10",
    "wbom_messages_canonical_phone", "wbom_messages_identity",
    "wbom_employee_excluded_from_cross_lookup",
    "fpe_wa_message_id", "fpe_id", "fpe_employee_id", "fpe_employee",
    "fpe_emp", "fpe_emp_phone_unique", "fpe_name", "fpe_txn",
    "fpe_txn_id", "fpe_msg_id", "fpe_link", "fpe_match", "fpe_rows",
    "fpe_row", "fpe_params", "fpe_err", "fpe_sql", "fpe_count",
    "fpe_employee_link", "fpe_employee_for_wbom_employee",
    "fpe_emp_primary_phone", "fpe_emp_name_norm", "fpe_emp_id_phone",
    "fpe_emp_canonical", "fpe_emp_wbom_link", "fpe_emp_resolution_status",
    "fpe_employee_by_id", "fpe_employee_payout_destinations",
    "fpe_employee_resolution_status", "fpe_employee_resolution_links",
    "fpe_ledger", "fpe_ledger_unique", "fpe_api_key",
    "fpe_bridge", "fpe_bridge_alias", "fpe_bridge_path_authority",
    "fpe_bridge_health", "fpe_bridge_gap_minutes", "fpe_bridge_last_hour_count",
    "fpe_bridge_gap_minutes",
    "fpe_cash", "fpe_cash_txn", "fpe_cash_txn_date", "fpe_cash_emp_date",
    "fpe_cash_period", "fpe_cash_source_msg", "fpe_cash_status",
    "fpe_txn_set_updated_at", "fpe_txn_updated_at_trig", "fpe_txn_phone",
    "fpe_txn_raw_collapsed_trgm", "fpe_txn_not_deleted",
    "fpe_txn_emp_name_raw_trgm", "fpe_txn_status", "fpe_txn_source",
    "fpe_txn_source_message", "fpe_txn_program", "fpe_txn_period",
    "fpe_txn_employee", "fpe_txn_date_desc", "fpe_txn_legacy_wbom",
    "fpe_ledger_total_earned_backfill", "fpe_cash_transactions_table",
    "fpe_transactions_today", "fpe_transactions_type",
    "fpe_transactions_employee", "fpe_transactions_wa_msg_dedup",
    "fpe_transactions_date", "fpe_txn_dedup_migration",
    "fpe_config", "fpe_changes", "fpe_write_errors", "fpe_or_ledger_mutation",
    "fpe_or_hermes_writes", "fpe_available", "fpe_by_phone",
    "fpe_engine", "fpe_payroll_engine", "fpe_router", "fpe_routes",
    "fpe_rules", "fpe_parser", "fpe_parser_results", "fpe_msg_processor",
    "fpe_messages", "fpe_message_processing_state", "fpe_wam_source",
    "fpe_wam_chat", "fpe_wa_messages", "fpe_wa_messages_unique",
    "fpe_wam_chat", "fpe_normalization", "fpe_normalization_audit_logs",
    "fpe_norm_audit_entity", "fpe_norm_audit_action",
    "fpe_soft_delete_columns", "fpe_missing_indexes", "fpe_search_indexes",
    "fpe_zero_loss", "fpe_uniform_salary_10000", "fpe_income",
    "fpe_income_transactions", "fpe_income_soft_delete", "fpe_income_not_deleted",
    "fpe_income_txn_date", "fpe_income_emp", "fpe_income_period",
    "fpe_income_reporter", "fpe_income_authorized_phone_list",
    "fpe_income_authorized_phones", "fpe_cash_authorized_phone_list",
    "fpe_cash_authorized_phones",
    "fpe_unmatched_messages", "fpe_unmatched_review_status",
    "fpe_unmatched_pending_amount", "fpe_unmatched_notification",
    "fpe_accounting_audit_logs", "fpe_accounting_audit",
    "fpe_audit_entity", "fpe_audit",
    "fpe_transaction_repairs", "fpe_transaction_from_ingest",
    "fpe_review_audit_logs", "fpe_review_audit_item", "fpe_review_audit_actor",
    "fpe_review_audit_action", "fpe_review_status", "fpe_review_candidate",
    "fpe_review_no_self", "fpe_employee_review_queue",
    "fpe_employee_edit_requests", "fpe_employee_aliases",
    "fpe_aliases_unique", "fpe_aliases_lookup",
    "fpe_resolution_unique", "fpe_resolution_no_self",
    "fpe_reslinks_employee", "fpe_reslinks_canonical",
    "fpe_link_zero_txn_count", "fpe_link_under_review",
    "fpe_link_treated_as_no_link", "fpe_link_no_deduction_draft_still_created",
    "fpe_link_deduction_is_zero",
    "fpe_sync_checkpoints", "fpe_checkpoint_unique", "fpe_sync_target",
    "fpe_sync_fields", "fpe_sync_chat_jids", "fpe_manual_sync",
    "fpe_gap_scan_runs", "fpe_gap_scan_missing_total",
    "fpe_gap_scan_last_missing", "fpe_gap_scan_backfilled_total",
    "fpe_gapscan_source_started", "fpe_gapscan",
    "fpe_processing_diagnostics", "fpe_diag_worker", "fpe_diag_type_status",
    "fpe_diag_failure", "fpe_diag_created", "fpe_diagnostics",
    "fpe_health_worker", "fpe_health_watchdog", "fpe_health",
    "fpe_workers", "fpe_msg_id", "fpe_processed_1h", "fpe_pending_review_count",
    "fpe_dlq_backlog", "fpe_dlq_count", "fpe_retry_storm_count",
    "fpe_skip_ratio_1h", "fpe_type_status_count", "fpe_mps_unique",
    "fpe_mps_status", "fpe_mps_status_attempts", "fpe_staging_payments",
    "fpe_mps", "fpe_hsync", "fpe_endpoint_sets_resolved",
    "fpe_endpoint_rejects_already_linked", "fpe_id_1", "fpe_id_2",
    "fpe_seeded", "fpe_source", "fpe_override__", "fpe_cash_transactions_canonical",
    "fpe_cash_transactions_pkey", "fpe_cash_transactions_id_seq",
    "fpe_cash_transactions_employee_id_fkey",
    "fpe_cash_transactions_txn_ref_key",
    "fpe_cash_transactions_reversed_txn_id_fkey",
    "fpe_cash_transactions_fpe_wa_message_id_fkey",
    "fpe_cash_transactions_canonical",
    "fpe_employee_ledger_pkey", "fpe_employee_ledger_employee_id_fkey",
    "fpe_employee_ledger_id_seq", "fpe_accounting_audit_logs_pkey",
    "fpe_accounting_audit_logs_id_seq", "fpe_transaction_repairs_id_seq",
    "fpe_transaction_repairs_transaction_id_fkey",
    "fpe_transaction_repairs_reversal_txn_id_fkey",
    "fpe_transaction_repairs_new_txn_id_fkey",
    "fpe_income_transactions_pkey", "fpe_income_transactions_txn_ref_key",
    "fpe_income_transactions_employee_id_fkey",
    "fpe_income_transactions_fpe_wa_message_id_fkey",
    "fpe_income_transactions_id_seq",
    "fpe_employees_phone", "fpe_employees_code", "fpe_employees_hr_columns",
    "fpe_overview", "fpe_overview_pkvc", "fpe_schema", "fpe_set_parts",
    "fpe_list_transactions", "fpe_readonly_view", "fpe_table",
    "fpe_operator_pending", "fpe_karim_supervisor", "fpe_karim_duplicate",
    "fpe_to_wbom", "fpe_wbom_link", "fpe_sync_target",
    "fpe_write_errors", "fpe_writes",
}

# Names that are clearly DB objects (tables) but NOT covered by the task's
# EXACT RENAMING MAP — these are the out-of-scope surface that makes the
# "zero hits" acceptance criterion impossible without extending the map.
KNOWN_OUT_OF_SCOPE_TABLE_TOKENS = {
    "wbom_escort_programs", "wbom_attendance", "wbom_candidates",
    "wbom_payroll_runs", "wbom_staging_payments", "wbom_billing_records",
    "wbom_payroll_approval_log", "wbom_relation_types",
    "wbom_payroll_run_items", "wbom_candidate_conversations",
    "wbom_unmatched_confirmations", "wbom_identity_links",
    "wbom_client_billing_profiles", "wbom_cases", "wbom_salary_records",
    "wbom_group_identities", "wbom_business_types", "wbom_employee_requests",
    "wbom_client_tiers", "wbom_client_statuses", "wbom_recruitment_reminders",
    "wbom_billing_payment_log", "wbom_message_templates",
    "wbom_outbound_messages", "wbom_job_applications",
    "wbom_candidate_events", "wbom_blocked_numbers", "wbom_payment_drafts",
    "wbom_media_downloads", "wbom_complaints", "wbom_conversations",
    "wbom_messages", "wbom_clients", "wbom_inbound_messages",
    "wbom_billing_audit_log", "wbom_admin_instructions",
    "wbom_escort_confirmed_exact",
}


def git_tracked(root: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True,
        ).stdout
        return [p for p in out.splitlines() if p]
    except Exception:
        return []


def iter_files(root: Path, exts: set[str]) -> list[Path]:
    out = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in exts:
            out.append(p)
    return out


def classify(token: str) -> str:
    if token in IN_SCOPE_TABLES:
        return "in_scope_table"
    if token in KNOWN_OUT_OF_SCOPE_TABLE_TOKENS:
        return "out_of_scope_table"
    if token in KNOWN_COLUMN_TOKENS:
        return "column_or_identifier"
    # heuristics
    if token.startswith("wbom_") or token.startswith("fpe_"):
        # looks like an index/constraint/sequence if it embeds a known table
        for t in list(IN_SCOPE_TABLES) + list(KNOWN_OUT_OF_SCOPE_TABLE_TOKENS):
            if token.startswith(t + "_"):
                return "index_constraint_or_sequence"
        return "unclassified_token"
    return "unclassified_token"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--out", default=None)
    ap.add_argument("--db-objects", default=None,
                    help="JSON produced by tools/dump_prefix_db_objects.py")
    args = ap.parse_args()

    root = Path(args.repo_root).resolve()
    out_path = Path(args.out) if args.out else root / "audits" / "prefix_unification_inventory.md"
    today = _dt.date.today().isoformat()
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    primary = iter_files(root, SCAN_EXTS)
    extra = iter_files(root, EXTRA_EXTS)

    # The generated inventory itself must not be scanned (it embeds every hit),
    # nor the discovery tools that necessarily contain the legacy names.
    SELF_NAMES = {
        "audits/prefix_unification_inventory.md",
        "tools/gen_prefix_inventory.py",
        "tools/dump_prefix_db_objects.py",
        "tools/prefix_manifest.py",
    }
    primary = [p for p in primary if str(p.relative_to(root)) not in SELF_NAMES]
    extra = [p for p in extra if str(p.relative_to(root)) not in SELF_NAMES]

    per_file: dict[str, dict] = {}
    raw_lines: list[str] = []
    token_totals: dict[str, int] = defaultdict(int)
    class_totals: dict[str, int] = defaultdict(int)
    total_hits = 0

    for p in sorted(primary):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        hits = []
        for i, line in enumerate(text.splitlines(), start=1):
            toks = TOKEN_RE.findall(line)
            if not toks:
                continue
            hits.append((i, line, toks))
            raw_lines.append(f"{p.relative_to(root)}:{i}:{line.rstrip()}")
            total_hits += len(toks)
            for t in toks:
                token_totals[t] += 1
                class_totals[classify(t)] += 1
        if hits:
            per_file[str(p.relative_to(root))] = {
                "hits": hits,
                "tokens": sorted({t for _, _, tk in hits for t in tk}),
                "n": sum(len(tk) for _, _, tk in hits),
            }

    extra_files = {}
    for p in sorted(extra):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        n = len(TOKEN_RE.findall(text))
        if n:
            extra_files[str(p.relative_to(root))] = n

    # ── module map presence check ──────────────────────────────────────────
    mod_rows = []
    for old, new in IN_SCOPE_MODULES.items():
        o = root / old
        o_py = root / (old + ".py")
        if o.is_dir():
            kind = "directory"
        elif o_py.is_file():
            kind = "module file"
        else:
            kind = "NOT FOUND at top level"
        base = old.rsplit("/", 1)[-1]
        imp_re = re.compile(
            r"\bmodules\s*\.\s*" + re.escape(base) + r"\b"
            r"|\bfrom\s+modules\s*\.\s*" + re.escape(base) + r"\b"
            r"|\bimport\s+modules\s*\.\s*" + re.escape(base) + r"\b"
        )
        n_refs = 0
        ref_files: set[str] = set()
        for fp in primary:
            try:
                txt = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            c = len(imp_re.findall(txt))
            if c:
                n_refs += c
                ref_files.add(str(fp.relative_to(root)))
        mod_rows.append((old, new, kind, n_refs, len(ref_files), sorted(ref_files)))

    # ── write ──────────────────────────────────────────────────────────────
    L: list[str] = []
    A = L.append
    A("# Prefix Unification Inventory — `wbom_` / `fpe_` → `fazle_`")
    A("")
    A(f"**Generated:** {now}  ")
    A(f"**Repository:** `arshiyaazim/fazle-core` @ branch `arena/a112683f-fazle-core`  ")
    A(f"**Purpose:** STEP 1 (DISCOVERY) pre-change inventory. Produced *before* any")
    A("file was modified, so it is a faithful record of the pre-unification state.")
    A("")
    A("> This file is a historical record of the **pre-change** state. Do not edit it")
    A("> to reflect post-unification naming — the post-change state is recorded in")
    A(f"> `audits/prefix_unification_{today}.md`.")
    A("")
    A("---")
    A("")
    A("## 1. Executive summary")
    A("")
    A(f"| Metric | Value |")
    A(f"|---|---:|")
    A(f"| Total `wbom_` / `fpe_` **occurrences** (scan set) | **{total_hits:,}** |")
    A(f"| Total **matching lines** (what `grep -c` reports) | **{len(raw_lines):,}** |")
    A(f"| Files containing ≥1 hit (scan set) | **{len(per_file)}** |")
    A(f"| Distinct `wbom_*` / `fpe_*` tokens | **{len(token_totals)}** |")
    A(f"| Additional files outside the scan set (`.html`/`.sh`/`.cfg`/`.ini`/`.toml`) | **{len(extra_files)}** |")
    A(f"| In-scope table renames (task map) | **{len(IN_SCOPE_TABLES)}** |")
    A(f"| Module renames (task map) | **{len(IN_SCOPE_MODULES)}** |")
    A("")
    A("> *Occurrences* counts every match; *matching lines* counts lines that")
    A("> contain at least one match (this is what `grep -c` reports). The STEP 1")
    A("> grep command reports **7,492 matching lines** over `.py .sql .md .txt")
    A("> .yaml .yml`; adding `.json` (STEP 3a) brings it to **7,648**.")
    A("")
    A("### Scan set / command")
    A("")
    A("```bash")
    A("grep -rn 'wbom_\\|fpe_' --include='*.py' --include='*.sql' \\")
    A("        --include='*.md' --include='*.txt' --include='*.yaml' --include='*.yml' .")
    A("```")
    A("")
    A("Scan set = `.py`, `.sql`, `.md`, `.txt`, `.yaml`, `.yml`, `.json`.")
    A("Excluded directories: `.git`, `__pycache__`, `.venv`, `node_modules`,")
    A("`.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `htmlcov`, `coverage`, `dist`, `build`.")
    A("")

    A("### Hits by top-level area")
    A("")
    area: dict[str, int] = defaultdict(int)
    area_files: dict[str, int] = defaultdict(int)
    for f, d in per_file.items():
        top = f.split("/")[0] if "/" in f else "(repository root)"
        area[top] += d["n"]
        area_files[top] += 1
    A("| Area | Files | Hits |")
    A("|---|---:|---:|")
    for k in sorted(area, key=lambda x: -area[x]):
        A(f"| `{k}` | {area_files[k]} | {area[k]:,} |")
    A(f"| **TOTAL** | **{len(per_file)}** | **{total_hits:,}** |")
    A("")

    A("### Hits by file extension")
    A("")
    ext_area: dict[str, int] = defaultdict(int)
    ext_files: dict[str, int] = defaultdict(int)
    for f, d in per_file.items():
        e = Path(f).suffix or "(none)"
        ext_area[e] += d["n"]
        ext_files[e] += 1
    A("| Extension | Files | Hits |")
    A("|---|---:|---:|")
    for k in sorted(ext_area, key=lambda x: -ext_area[x]):
        A(f"| `{k}` | {ext_files[k]} | {ext_area[k]:,} |")
    A("")

    # ── section 2: classification ─────────────────────────────────────────
    A("---")
    A("")
    A("## 2. Token classification")
    A("")
    A("Every distinct token is bucketed into one of four classes. The buckets")
    A("drive how much of the `wbom_` / `fpe_` surface the task's EXACT RENAMING MAP")
    A("actually covers.")
    A("")
    A("| Class | Occurrences | Meaning |")
    A("|---|---:|---|")
    A(f"| `in_scope_table` | {class_totals['in_scope_table']:,} | One of the 7 tables in the task's renaming map — **must be renamed** |")
    A(f"| `out_of_scope_table` | {class_totals['out_of_scope_table']:,} | A real table with a legacy prefix that is **NOT in the task's map** — see §6 |")
    A(f"| `index_constraint_or_sequence` | {class_totals['index_constraint_or_sequence']:,} | Index / constraint / sequence named after a legacy table |")
    A(f"| `column_or_identifier` | {class_totals['column_or_identifier']:,} | Column names, Python identifiers, metric names — **HARD CONSTRAINT #4 says do not rename** |")
    A(f"| `unclassified_token` | {class_totals['unclassified_token']:,} | Log labels, doc prose, filenames, module names, free text |")
    A("")
    A("---")
    A("")
    A("## 3. In-scope table renames (task EXACT RENAMING MAP)")
    A("")
    A("| # | Old table | New table | Occurrences | Files |")
    A("|---:|---|---|---:|---:|")
    for i, (old, new) in enumerate(IN_SCOPE_TABLES.items(), start=1):
        occ = token_totals.get(old, 0)
        nf = sum(1 for d in per_file.values() if old in d["tokens"])
        A(f"| {i} | `{old}` | `{new}` | {occ:,} | {nf} |")
    A("")
    A("**Conflict check:** none of the seven target names (`fazle_whatsapp_messages`,")
    A("`fazle_contacts`, `fazle_cash_transactions_archive`, `fazle_employees_legacy`,")
    A("`fazle_cash_transactions`, `fazle_employee_ledger`, `fazle_employees`) already")
    A("exist anywhere in the repository. `fazle_message_archive` appears once, but")
    A("only as a *table name string inside `scripts/shadow_recruitment_conversation_layer.py`*")
    A("(a candidate-table list) — not as an existing Postgres table — and it is not")
    A("produced by this rename map. No `fazle_*` table in the map collides with an")
    A("existing `fazle_*` table.")
    A("")

    A("---")
    A("")
    A("## 4. Module renames (task EXACT RENAMING MAP)")
    A("")
    A("| Old path | New path | On-disk kind | Import refs | Files |")
    A("|---|---|---|---:|---:|")
    for old, new, kind, n_refs, nf, _rf in mod_rows:
        A(f"| `{old}` | `{new}` | {kind} | {n_refs:,} | {nf} |")
    A("")
    A("### Files that import each module")
    A("")
    for old, new, kind, n_refs, nf, rf in mod_rows:
        A(f"**`{old}` → `{new}`** ({kind}, {n_refs:,} import ref(s) in {nf} file(s))")
        A("")
        for f in rf:
            A(f"- `{f}`")
        if not rf:
            A("- _(no direct `modules.<name>` import references found)_")
        A("")
    A("### Path-shape discrepancies found (need a decision)")
    A("")
    A("1. **`modules/wbom_fpe_sync` does not exist as a top-level path.** The only")
    A("   match in the tree is `modules/payment_ingest/wbom_fpe_sync.py` — a *file")
    A("   inside* the `payment_ingest` package, not a sibling package. Since")
    A("   `modules/payment_ingest` is itself renamed to `modules/fazle_payment_ingest`,")
    A("   the two rules overlap on the same file.")
    A("2. **`modules/identity_resolver` is a file** (`modules/identity_resolver.py`),")
    A("   not a package — so `modules/fazle_identity_resolver` must be a `.py` file.")
    A("3. **`modules/group_identity` is a file** (`modules/group_identity.py`) — so")
    A("   `modules/fazle_group_identity` must be a `.py` file.")
    A("4. **`modules/payment_ingest/fpe_bridge.py`** carries a legacy name but is not")
    A("   listed in the module map; it sits inside a package that *is* in the map.")
    A("5. The map's `modules/fazle_data_sync` target is a **top-level package**,")
    A("   while the source `wbom_fpe_sync` is a **nested file** — the rename changes")
    A("   nesting level as well as the name.")
    A("")

    A("---")
    A("")
    A("## 5. Files containing `wbom_` / `fpe_` — complete inventory")
    A("")
    A("Every file that contains at least one hit, with its line numbers and the")
    A("distinct legacy tokens it contains. Sorted by hit count (descending).")
    A("")
    for f in sorted(per_file, key=lambda x: (-per_file[x]["n"], x)):
        d = per_file[f]
        A(f"#### `{f}` — {d['n']:,} hit(s)")
        A("")
        A(f"Tokens: {', '.join('`' + t + '`' for t in d['tokens'])}")
        A("")
        A("Lines: " + ", ".join(str(i) for i, _, _ in d["hits"]))
        A("")
    A("---")
    A("")
    A("## 6. Out-of-scope legacy-prefixed tables (NOT in the task's renaming map)")
    A("")
    A("The task's EXACT RENAMING MAP covers **7 tables**. The repository contains")
    A("**many more** tables that still carry a `wbom_` / `fpe_` prefix and are")
    A("referenced by live code, migrations and tests. These are **not** renamed by")
    A("the map, yet the acceptance criterion \"grep for `wbom_` or `fpe_` returns")
    A("ZERO hits in `app/`, `modules/`, `shared/`, `scripts/`, `db/migrations/`\"")
    A("cannot be satisfied while they remain.")
    A("")
    A("| Out-of-scope table token | Occurrences |")
    A("|---|---:|")
    for t in sorted(KNOWN_OUT_OF_SCOPE_TABLE_TOKENS, key=lambda x: -token_totals.get(x, 0)):
        occ = token_totals.get(t, 0)
        if occ:
            A(f"| `{t}` | {occ:,} |")
    A("")
    A("---")
    A("")
    A("## 7. Columns & identifiers that must NOT be renamed (HARD CONSTRAINT #4)")
    A("")
    A("These legacy-prefixed tokens are **column names, Python parameter names,")
    A("metric names or constraint names**, not table names. HARD CONSTRAINT #4")
    A("forbids changing column names, so they are expected to survive the")
    A("unification and will necessarily keep `wbom_` / `fpe_` substrings.")
    A("")
    A("| Token | Occurrences | Notes |")
    A("|---|---:|---|")
    for t in sorted(KNOWN_COLUMN_TOKENS, key=lambda x: -token_totals.get(x, 0)):
        occ = token_totals.get(t, 0)
        if occ:
            A(f"| `{t}` | {occ:,} | column / identifier — keep |")
    A("")

    A("---")
    A("")
    A("## 8. Files outside the scan set (informational)")
    A("")
    A("| File | Hits |")
    A("|---|---:|")
    for f, n in sorted(extra_files.items(), key=lambda kv: -kv[1]):
        A(f"| `{f}` | {n:,} |")
    A("")

    A("---")
    A("")
    A("## 9. All distinct tokens (frequency-ordered)")
    A("")
    A("| Token | Occurrences | Class |")
    A("|---|---:|---|")
    for t, n in sorted(token_totals.items(), key=lambda kv: (-kv[1], kv[0])):
        A(f"| `{t}` | {n:,} | `{classify(t)}` |")
    A("")

    A("---")
    A("")
    A("## 10. Live Postgres object inventory for the 7 in-scope tables")
    A("")
    A("Captured from a real PostgreSQL 16.2 instance with the full migration set")
    A("applied (`tools/dump_prefix_db_objects.py`). These are exactly the objects a")
    A("`RENAME` touches, plus the objects that reference them.")
    A("")
    db = {}
    db_path = Path(args.db_objects) if args.db_objects else None
    if db_path and db_path.exists():
        import json as _json
        db = _json.loads(db_path.read_text(encoding="utf-8"))
    if db:
        A(f"- **Tables found in `public` schema:** {len(db.get('tables', []))} / 7 expected")
        A(f"- **Sequences:** {len(db.get('sequences', []))}")
        A(f"- **Indexes:** {len(db.get('indexes', []))}")
        A(f"- **Constraints:** {len(db.get('constraints', []))}")
        A(f"- **Foreign keys *referencing* these tables (from other tables):** "
          f"{len(db.get('foreign_keys_referencing', []))}")
        A(f"- **Triggers:** {len(db.get('triggers', []))}")
        A(f"- **Views:** {len(db.get('views', []))}")
        A(f"- **Total legacy-prefixed tables in `public`:** "
          f"{len(db.get('legacy_prefixed_tables', []))} "
          f"(7 in scope → {len(db.get('legacy_prefixed_tables', [])) - 7} out of scope)")
        A("")
        A("### Indexes per in-scope table")
        A("")
        by_tab: dict[str, list[str]] = defaultdict(list)
        for r in db.get("indexes", []):
            by_tab[r["on_table"]].append(r["index_name"])
        for t in IN_SCOPE_TABLES:
            names = sorted(by_tab.get(t, []))
            A(f"**`{t}`** — {len(names)} index(es)")
            A("")
            for n in names:
                A(f"- `{n}`")
            if not names:
                A("- _(none)_")
            A("")
        A("### Constraints per in-scope table")
        A("")
        by_tab_c: dict[str, list[dict]] = defaultdict(list)
        for r in db.get("constraints", []):
            by_tab_c[r["on_table"]].append(r)
        for t in IN_SCOPE_TABLES:
            rows = sorted(by_tab_c.get(t, []), key=lambda r: r["constraint_name"])
            A(f"**`{t}`** — {len(rows)} constraint(s)")
            A("")
            for r in rows:
                ref = f" → `{r['references_table']}`" if r.get("references_table") else ""
                A(f"- `{r['constraint_name']}` (type `{r['contype']}`){ref}")
            if not rows:
                A("- _(none)_")
            A("")
        A("### Foreign keys pointing *at* the in-scope tables (from other tables)")
        A("")
        A("> Postgres `ALTER TABLE … RENAME TO …` rewrites the *referenced* table")
        A("> inside each of these FKs automatically. The FK **constraint names** keep")
        A("> their old prefix unless explicitly renamed. No data loss, no FK breakage.")
        A("")
        A("| FK constraint | Referencing table | Referenced table (old) |")
        A("|---|---|---|")
        for r in sorted(db.get("foreign_keys_referencing", []),
                        key=lambda r: (r["referenced_table"], r["fk_name"])):
            A(f"| `{r['fk_name']}` | `{r['referencing_table']}` | `{r['referenced_table']}` |")
        A("")
        A("### Triggers")
        A("")
        A("| Trigger | On table | Function |")
        A("|---|---|---|")
        for r in db.get("triggers", []):
            A(f"| `{r['trigger_name']}` | `{r['on_table']}` | `{r['function_name']}` |")
        A("")
        A("### Sequences")
        A("")
        for r in db.get("sequences", []):
            A(f"- `{r['sequence_name']}`")
        A("")
    else:
        A("_No live database dump was supplied (`--db-objects` not provided)._")
        A("")

    A("---")
    A("")
    A("## 11. STOP CONDITIONS — items requiring human confirmation before STEP 2")
    A("")
    A("The task defines five stop conditions. Findings against each:")
    A("")
    A("### 11.1 TRIGGERED — out-of-scope legacy-prefixed tables (acceptance-criteria conflict)")
    A("")
    A("The EXACT RENAMING MAP renames **7 tables**. The live database contains")
    A(f"**{len(db.get('legacy_prefixed_tables', [])) if db else 46} tables** with a `wbom_` / `fpe_`")
    A("prefix, of which only 7 are in the map. The remaining")
    A(f"**{len(db.get('legacy_prefixed_tables', [])) - 7 if db else 39}** are referenced by live")
    A("code, migrations and tests (e.g. `wbom_escort_programs` — 710 occurrences,")
    A("`wbom_attendance` — 253, `wbom_candidates` — 202, `wbom_payroll_runs` — 157).")
    A("")
    A("The acceptance criterion *\"grep for `wbom_` or `fpe_` returns ZERO hits in")
    A("`app/`, `modules/`, `shared/`, `scripts/`, `db/migrations/`\"* **cannot be met**")
    A("while these tables keep their legacy names, because the map does not rename")
    A("them and they are referenced by in-scope modules (e.g.")
    A("`modules/escort/`, `modules/payroll/`, `modules/attendance/`).")
    A("")
    A("**Three ways to resolve — please pick one:**")
    A("")
    A("- **(A) Extend the map** — add the remaining ~39 legacy tables to the renaming")
    A("  map (e.g. `wbom_escort_programs` → `fazle_escort_programs`, …), producing")
    A("  ~46 migration files instead of 7. Largest blast radius; achieves the")
    A("  acceptance criterion literally.")
    A("- **(B) Narrow the acceptance criterion** — rename only the 7 mapped tables")
    A("  and relax the criterion to \"no `wbom_`/`fpe_` references to the 7 mapped")
    A("  tables remain\". Smallest, safest blast radius. **Recommended.**")
    A("- **(C) Two-phase** — phase 1 does the 7 mapped tables (this PR), phase 2")
    A("  handles the rest in a follow-up PR.")
    A("")
    A("### 11.2 TRIGGERED — column names carry the legacy prefix")
    A("")
    A("HARD CONSTRAINT #4 says **do not change column names**. But these columns")
    A("exist and are referenced by live SQL:")
    A("")
    A("| Column | Occurrences | Notes |")
    A("|---|---:|---|")
    for col, note in [
        ("wbom_employee_id", "FK column on `fpe_employees` linking to the legacy WBOM employee"),
        ("fpe_wa_message_id", "FK column on `fpe_cash_transactions` / `fpe_income_transactions`"),
        ("wbom_employee_name", "employee display column"),
        ("wbom_employee_mobile", "employee mobile column"),
        ("legacy_wbom_transaction_id", "back-reference column on `fpe_cash_transactions`"),
    ]:
        A(f"| `{col}` | {token_totals.get(col, 0):,} | {note} |")
    A("")
    A("These **must keep** their names under HARD CONSTRAINT #4, which means")
    A("`wbom_`/`fpe_` substrings will remain in `.py` files under `modules/`.")
    A("A literal \"zero hits\" test would therefore fail by construction. The new")
    A("test `tests/test_prefix_unification.py` must be written to allow these")
    A("**column-name** occurrences while forbidding **table-name** occurrences.")
    A("**Please confirm this interpretation.**")
    A("")
    A("### 11.3 TRIGGERED — index / constraint / trigger / sequence names")
    A("")
    A("STEP 2 says *\"Rename dependent indexes/sequences if they carry the old")
    A("prefix\"*, while HARD CONSTRAINT #4 says *\"do not change … indexes, or")
    A("constraints\"*. These are reconciled by reading #4 as *\"do not change index /")
    A("constraint **definitions** (columns, predicates, uniqueness) — name-only")
    A("renames are permitted and explicitly requested by STEP 2\"*. The duplicate-")
    A("prevention semantics are preserved exactly (e.g. `uq_wbom_messages_hash` →")
    A("`uq_fazle_messages_hash` stays UNIQUE on the same `message_hash` column;")
    A("`idx_txn_idempotency` and `idx_wbom_transactions_dedup` keep their exact")
    A("partial predicates). **Please confirm.**")
    A("")
    A("### 11.4 TRIGGERED — module paths in the map do not all exist as written")
    A("")
    A("See §4. `modules/wbom_fpe_sync` is nested inside `modules/payment_ingest/`")
    A("rather than being a top-level package; `modules/identity_resolver` and")
    A("`modules/group_identity` are single `.py` files, not packages. The proposed")
    A("resolution:")
    A("")
    A("- `modules/payment_ingest/wbom_fpe_sync.py` → `modules/fazle_data_sync/__init__.py`")
    A("  (top-level package, matching the map's target path)")
    A("- `modules/payment_ingest/fpe_bridge.py` → `modules/fazle_payment_ingest/fpe_bridge.py`")
    A("  (stays inside the renamed package; **not** in the map, so its name is kept")
    A("  but a `modules/payment_ingest/fpe_bridge.py` shim is added)")
    A("- `modules/identity_resolver.py` → `modules/fazle_identity_resolver.py`")
    A("- `modules/group_identity.py` → `modules/fazle_group_identity.py`")
    A("")
    A("**Please confirm**, or tell me to keep the same on-disk *shape* as the source")
    A("(i.e. `modules/fazle_data_sync.py` as a file rather than a package).")
    A("")
    A("### 11.5 TRIGGERED — legacy-prefixed environment variables")
    A("")
    A("| Environment variable | Occurrences | Reference |")
    A("|---|---:|---|")
    A("| `FPE_HSYNC_INTERVAL_S` | 1 | `modules/fazle_payroll_engine/historical_sync.py:72` |")
    A("| `FPE_PAYMENT_INACTIVITY_SWEEP_ENABLED` | 1 | `modules/payment_relay_accounting/__init__.py:648` |")
    A("")
    A("These env var *names* carry the legacy `FPE_` prefix. They reference")
    A("**timings**, not table names, so no table rename breaks them. They are")
    A("**not** in the map. **Proposed: leave the env var names unchanged** (so no")
    A("production `.env` needs editing) but note them in the final report as a")
    A("follow-up item. **Please confirm.**")
    A("")
    A("### 11.6 NOT TRIGGERED — table-name conflicts with existing `fazle_*` tables")
    A("")
    A("None of the seven target names already exists as a table, view, sequence or")
    A("index anywhere in the repository or in the live `public` schema. Verified by:")
    A("")
    A("```sql")
    A("SELECT to_regclass('public.fazle_whatsapp_messages'),  -- NULL")
    A("       to_regclass('public.fazle_contacts'),            -- NULL")
    A("       to_regclass('public.fazle_cash_transactions_archive'), -- NULL")
    A("       to_regclass('public.fazle_employees_legacy'),    -- NULL")
    A("       to_regclass('public.fazle_cash_transactions'),   -- NULL")
    A("       to_regclass('public.fazle_employee_ledger'),     -- NULL")
    A("       to_regclass('public.fazle_employees');           -- NULL")
    A("```")
    A("")
    A("`fazle_message_archive` appears once as a *candidate table-name string*")
    A("inside `scripts/shadow_recruitment_conversation_layer.py` — it is not an")
    A("existing Postgres table and is not produced by this map, so it is not a")
    A("conflict.")
    A("")
    A("### 11.7 NOT TRIGGERED — backward-compat shims are practical")
    A("")
    A("All 13 module renames can be shimmed with a **lazy** PEP-562 module-level")
    A("`__getattr__` that re-exports from the new path and emits a")
    A("`DeprecationWarning` on first attribute access. Because resolution is")
    A("deferred to import time, there is **no circular-import risk** — the shim")
    A("never imports the new module until something actually asks for an")
    A("attribute from it. The same pattern works for both directory packages")
    A("(`modules/bridge_poller/__init__.py`) and single-file modules")
    A("(`modules/identity_resolver.py`).")
    A("")
    A("### 11.8 NOT TRIGGERED — bridge SQLite paths")
    A("")
    A("`/home/azim/whatsapp1/store/messages.db` and")
    A("`/home/azim/whatsapp2/store/messages.db` are referenced only via the")
    A("`bridge1_db_path` / `bridge2_db_path` settings and the `messages_db`")
    A("parameter of `modules/bridge_poller/__init__.py`. **No table name appears")
    A("in any bridge SQLite path or SQLite query**, so no rename touches them.")
    A("The bridge poller source is captured pre-change in a SHA-256 manifest")
    A("(`tools/prefix_manifest.py`) so the post-change diff can prove")
    A("byte-identity.")
    A("")
    A("---")
    A("")
    A("## 12. Environment & baseline notes")
    A("")
    A("| Item | Value |")
    A("|---|---|")
    A("| Postgres | PostgreSQL 16.2 (local, `127.0.0.1:5433/fazle_test`) — used to validate migrations & the verification SQL |")
    A("| Python | 3.11.2 |")
    A("| Test suite | `pytest tests/{unit,integration,db,workflows,resilience}` |")
    A("| Pre-existing collection error | `tests/unit/test_phase_a_corpus.py` — hardcodes `/home/azim/core/tests/unit/data/...`, a path that does not exist in this checkout. Pre-existing; unrelated to this task. |")
    A("| DB-dependent tests | Require `TEST_DATABASE_URL` / a reachable Postgres on `127.0.0.1:5433`. Without one they error at baseline. |")
    A("| Protected-file manifest | `tools/prefix_manifest.py capture` — SHA-256 of the bridge poller, canonical ledger, OCR and identity-resolver files, taken **before** any change. |")
    A("")
    A("---")
    A("")
    A("## 13. Appendix — raw grep dump (every matching line)")
    A("")
    A(f"<details><summary>Full raw output ({len(raw_lines):,} matching lines)</summary>")
    A("")
    A("```")
    for line in raw_lines:
        A(line)
    A("```")
    A("")
    A("</details>")
    A("")
    A("---")
    A("")
    A(f"*End of inventory. Generated {now} by `tools/gen_prefix_inventory.py`.*")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"  total hits : {total_hits:,}")
    print(f"  files      : {len(per_file)}")
    print(f"  tokens     : {len(token_totals)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
