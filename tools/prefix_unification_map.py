#!/usr/bin/env python3
"""
Shared prefix-unification maps.

Single source of truth for the `fazle_` prefix unification.  Imported by
`tools/gen_unify_migrations.py`, `tools/apply_prefix_unification.py` and
`tests/test_prefix_unification.py` so the table map, the object-rename rule
and the module map can never drift apart.
"""
from __future__ import annotations

# ── The 7 in-scope table renames (task EXACT RENAMING MAP) ─────────────────
TABLE_MAP: dict[str, str] = {
    "wbom_whatsapp_messages": "fazle_whatsapp_messages",
    "wbom_contacts": "fazle_contacts",
    "wbom_cash_transactions": "fazle_cash_transactions_archive",
    "wbom_employees": "fazle_employees_legacy",
    "fpe_cash_transactions": "fazle_cash_transactions",
    "fpe_employee_ledger": "fazle_employee_ledger",
    "fpe_employees": "fazle_employees",
}

# Longest-first so `fpe_cash_transactions` is never shadowed by `fpe_employees`.
TABLE_MAP_LONGEST_FIRST = sorted(TABLE_MAP.items(), key=lambda kv: -len(kv[0]))

# ── Module rename map (task EXACT RENAMING MAP) ─────────────────────────────
#   source path                       -> target path
#   (a trailing ".py" means a single-file module, not a package)
MODULE_MAP: dict[str, str] = {
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

# The real on-disk sources.  `modules/wbom_fpe_sync` does not exist as a
# top-level path — the only match in the tree is a FILE nested inside
# `modules/payment_ingest/`, which is itself renamed.  Resolved per the
# approved STEP 1 decision: the file becomes the top-level package
# `modules/fazle_data_sync/`.
MODULE_SOURCE_TO_TARGET: dict[str, str] = {
    "modules/payment_ingest/wbom_fpe_sync.py": "modules/fazle_data_sync/__init__.py",
    "modules/payment_ingest": "modules/fazle_payment_ingest",
    "modules/payment_ingest/fpe_bridge.py": "modules/fazle_payment_ingest/fpe_bridge.py",
    "modules/payment_workflow": "modules/fazle_payment_workflow",
    "modules/bridge_poller": "modules/fazle_bridge_poller",
    "modules/message_archive": "modules/fazle_message_archive",
    "modules/media_normalization": "modules/fazle_media_normalization",
    "modules/identity_resolver.py": "modules/fazle_identity_resolver.py",
    "modules/identity_brain": "modules/fazle_identity_brain",
    "modules/admin_commands": "modules/fazle_admin_commands",
    "modules/draft_approval": "modules/fazle_draft_approval",
    "modules/group_identity.py": "modules/fazle_group_identity.py",
    "modules/intent": "modules/fazle_intent",
    "modules/image_hash": "modules/fazle_image_hash",
}

# Import-path rewrites: `modules.X` -> `modules.fazle_X` etc.
IMPORT_PATH_MAP: dict[str, str] = {
    "modules.payment_ingest": "modules.fazle_payment_ingest",
    "modules.payment_workflow": "modules.fazle_payment_workflow",
    "modules.bridge_poller": "modules.fazle_bridge_poller",
    "modules.message_archive": "modules.fazle_message_archive",
    "modules.media_normalization": "modules.fazle_media_normalization",
    "modules.identity_resolver": "modules.fazle_identity_resolver",
    "modules.identity_brain": "modules.fazle_identity_brain",
    "modules.admin_commands": "modules.fazle_admin_commands",
    "modules.draft_approval": "modules.fazle_draft_approval",
    "modules.group_identity": "modules.fazle_group_identity",
    "modules.intent": "modules.fazle_intent",
    "modules.image_hash": "modules.fazle_image_hash",
    "modules.payment_ingest.wbom_fpe_sync": "modules.fazle_data_sync",
    "modules.payment_ingest.fpe_bridge": "modules.fazle_payment_ingest.fpe_bridge",
}

# Slash-form module path references (docs, comments, markdown).
MODULE_PATH_MAP: dict[str, str] = {
    "modules/payment_ingest/wbom_fpe_sync.py": "modules/fazle_data_sync/__init__.py",
    "modules/payment_ingest/wbom_fpe_sync": "modules/fazle_data_sync",
    "modules/payment_ingest/fpe_bridge.py": "modules/fazle_payment_ingest/fpe_bridge.py",
    "modules/payment_ingest": "modules/fazle_payment_ingest",
    "modules/payment_workflow": "modules/fazle_payment_workflow",
    "modules/bridge_poller": "modules/fazle_bridge_poller",
    "modules/message_archive": "modules/fazle_message_archive",
    "modules/media_normalization": "modules/fazle_media_normalization",
    "modules/identity_resolver.py": "modules/fazle_identity_resolver.py",
    "modules/identity_resolver": "modules/fazle_identity_resolver",
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
    "modules/group_identity": "modules/fazle_group_identity",
    "modules/intent": "modules/fazle_intent",
    "modules/image_hash": "modules/fazle_image_hash",
}

# ── Column names that legitimately keep the legacy prefix ───────────────────
# HARD CONSTRAINT #4 forbids changing column names.  These are columns on
# the renamed tables and MUST NOT be rewritten.
PROTECTED_COLUMN_TOKENS: frozenset[str] = frozenset({
    "wbom_employee_id",
    "wbom_employee_name",
    "wbom_employee_mobile",
    "fpe_wa_message_id",
})

# ── Object-rename rule for dependent DB objects ─────────────────────────────
def rename_db_object(obj_name: str) -> str:
    """
    Derive the new name of a dependent DB object (index / constraint /
    sequence / trigger / function) from its current name.

    Rules, applied in order:
      1. If the object name contains an old table name, that occurrence is
         replaced by the new table name.
      2. Otherwise every remaining `wbom_` / `fpe_` fragment in the name
         becomes `fazle_` (this covers `idx_wbom_messages_hash` ->
         `idx_fazle_messages_hash` and `fpe_ledger_unique` ->
         `fazle_ledger_unique`).
      3. Otherwise the name is left alone (`idx_txn_idempotency` keeps its
         name, so the queue idempotency_key index is untouched).
    """
    if any(old in obj_name for old, _ in TABLE_MAP_LONGEST_FIRST):
        out = obj_name
        for old, new in TABLE_MAP_LONGEST_FIRST:
            out = out.replace(old, new)
        return out
    return obj_name.replace("wbom_", "fazle_").replace("fpe_", "fazle_")


def all_new_table_names() -> list[str]:
    return list(TABLE_MAP.values())


def all_old_table_names() -> list[str]:
    return list(TABLE_MAP.keys())


# ── Columns that the new prefix-unification test must tolerate ─────────────
# (legacy-prefixed COLUMN names + legacy-prefixed identifiers that are not
#  table names).  Used by tests/test_prefix_unification.py.
KNOWN_LEGACY_COLUMN_NAMES: frozenset[str] = frozenset({
    "wbom_employee_id", "wbom_employee_name", "wbom_employee_mobile",
    "wbom_employee", "wbom_emp", "wbom_id", "wbom_txn_id",
    "wbom_transaction_id", "wbom_received_at", "wbom_direction",
    "wbom_name", "wbom_mobile", "wbom_role", "wbom_status",
    "wbom_match", "wbom_match_id", "wbom_match_name", "wbom_match_mobile",
    "wbom_match_unlinked", "wbom_match_unlinked_count", "wbom_match_count",
    "wbom_match_is_resolved", "wbom_match_stays_unresolved",
    "wbom_phone_match", "wbom_messages_hash",
    "wbom_msg_intent", "wbom_msg_conv_key", "wbom_msg_status",
    "wbom_msg_received_at", "wbom_msg_platform",
    "wbom_msg_platform_direction", "wbom_msg_contact_identifier",
    "wbom_msg_canonical_key", "wbom_msg_actor_type",
    "wbom_msg_meta_source_ref", "wbom_msg_meta_wamid",
    "wbom_msg_workflow_triggered", "wbom_msg_autofill",
    "wbom_messages_sender", "wbom_messages_class",
    "wbom_messages_sender_name_source", "wbom_messages_received",
    "wbom_messages_phone_last10", "wbom_messages_canonical_phone",
    "wbom_messages_identity", "wbom_employee_excluded_from_cross_lookup",
    "wbom_to_fpe", "wbom_actor_attribution_stage_b",
    "wbom_write_delta", "wbom_new_writes_today", "wbom_write_check_failed",
    "wbom_legacy_reads", "wbom_freeze", "wbom_reactivate",
    "wbom_deactivate", "wbom_update_employee", "wbom_update_calls",
    "wbom_cross_lookup", "wbom_type_to_category", "wbom_cash_transactions_write",
    "wbom_cash_transactions_updated_by_intent_advance_record",
    "wbom_cash_transactions_columns", "wbom_contacts_columns",
    "wbom_contacts_delete_result", "wbom_contacts_whatsapp_row_still_resolves",
    "wbom_contacts_platform_filter", "wbom_contacts_platform_filter_positive_and_negative",
    "wbom_cash", "wbom_cash_txn", "wbom_count", "wbom_col", "wbom_clients",
    "wbom_changes", "wbom_rows", "wbom_row", "wbom_bkash", "wbom_nagad",
    "wbom_name", "wbom_reminders", "wbom_recruitment_",
    "fpe_wa_message_id", "fpe_id", "fpe_employee_id", "fpe_employee",
    "fpe_emp", "fpe_name", "fpe_txn", "fpe_txn_id", "fpe_msg_id",
    "fpe_link", "fpe_match", "fpe_rows", "fpe_row", "fpe_params",
    "fpe_err", "fpe_sql", "fpe_count", "fpe_employee_link",
    "fpe_employee_for_wbom_employee", "fpe_emp_primary_phone",
    "fpe_emp_name_norm", "fpe_emp_id_phone", "fpe_emp_canonical",
    "fpe_emp_wbom_link", "fpe_emp_resolution_status",
    "fpe_employee_by_id", "fpe_employee_payout_destinations",
    "fpe_employee_resolution_status", "fpe_ledger", "fpe_ledger_unique",
    "fpe_api_key", "fpe_bridge", "fpe_bridge_alias",
    "fpe_bridge_path_authority", "fpe_bridge_health",
    "fpe_bridge_gap_minutes", "fpe_bridge_last_hour_count",
    "fpe_cash", "fpe_cash_txn", "fpe_cash_txn_date", "fpe_cash_emp_date",
    "fpe_cash_period", "fpe_cash_source_msg", "fpe_cash_status",
    "fpe_txn_set_updated_at", "fpe_txn_updated_at_trig", "fpe_txn_phone",
    "fpe_txn_raw_collapsed_trgm", "fpe_txn_not_deleted",
    "fpe_txn_emp_name_raw_trgm", "fpe_txn_status", "fpe_txn_source",
    "fpe_txn_source_message", "fpe_txn_program", "fpe_txn_period",
    "fpe_txn_employee", "fpe_txn_date_desc", "fpe_txn_legacy_wbom",
    "fpe_ledger_total_earned_backfill",
    "fpe_config", "fpe_changes", "fpe_write_errors",
    "fpe_or_ledger_mutation", "fpe_or_hermes_writes", "fpe_available",
    "fpe_by_phone", "fpe_engine", "fpe_payroll_engine", "fpe_router",
    "fpe_routes", "fpe_rules", "fpe_parser", "fpe_parser_results",
    "fpe_msg_processor", "fpe_messages", "fpe_message_processing_state",
    "fpe_wam_source", "fpe_wam_chat", "fpe_wa_messages",
    "fpe_wa_messages_unique", "fpe_normalization",
    "fpe_normalization_audit_logs", "fpe_norm_audit_entity",
    "fpe_norm_audit_action", "fpe_soft_delete_columns",
    "fpe_missing_indexes", "fpe_search_indexes", "fpe_zero_loss",
    "fpe_uniform_salary_10000", "fpe_income", "fpe_income_soft_delete",
    "fpe_income_not_deleted", "fpe_income_txn_date", "fpe_income_emp",
    "fpe_income_period", "fpe_income_reporter",
    "fpe_income_authorized_phone_list", "fpe_income_authorized_phones",
    "fpe_cash_authorized_phone_list", "fpe_cash_authorized_phones",
    "fpe_unmatched_messages", "fpe_unmatched_review_status",
    "fpe_unmatched_pending_amount", "fpe_unmatched_notification",
    "fpe_accounting_audit_logs", "fpe_accounting_audit", "fpe_audit_entity",
    "fpe_audit", "fpe_transaction_repairs", "fpe_transaction_from_ingest",
    "fpe_review_audit_logs", "fpe_review_audit_item", "fpe_review_audit_actor",
    "fpe_review_audit_action", "fpe_review_status", "fpe_review_candidate",
    "fpe_review_no_self", "fpe_employee_review_queue",
    "fpe_employee_edit_requests", "fpe_employee_aliases",
    "fpe_aliases_unique", "fpe_aliases_lookup", "fpe_resolution_unique",
    "fpe_resolution_no_self", "fpe_reslinks_employee",
    "fpe_reslinks_canonical", "fpe_link_zero_txn_count",
    "fpe_link_under_review", "fpe_link_treated_as_no_link",
    "fpe_link_no_deduction_draft_still_created", "fpe_link_deduction_is_zero",
    "fpe_sync_checkpoints", "fpe_checkpoint_unique", "fpe_sync_target",
    "fpe_sync_fields", "fpe_sync_chat_jids", "fpe_manual_sync",
    "fpe_gap_scan_runs", "fpe_gap_scan_missing_total",
    "fpe_gap_scan_last_missing", "fpe_gap_scan_backfilled_total",
    "fpe_gapscan_source_started", "fpe_gapscan",
    "fpe_processing_diagnostics", "fpe_diag_worker", "fpe_diag_type_status",
    "fpe_diag_failure", "fpe_diag_created", "fpe_diagnostics",
    "fpe_health_worker", "fpe_health_watchdog", "fpe_health", "fpe_workers",
    "fpe_processed_1h", "fpe_pending_review_count", "fpe_dlq_backlog",
    "fpe_dlq_count", "fpe_retry_storm_count", "fpe_skip_ratio_1h",
    "fpe_type_status_count", "fpe_mps_unique", "fpe_mps_status",
    "fpe_mps_status_attempts", "fpe_staging_payments", "fpe_mps",
    "fpe_hsync", "fpe_endpoint_sets_resolved",
    "fpe_endpoint_rejects_already_linked", "fpe_id_1", "fpe_id_2",
    "fpe_seeded", "fpe_source", "fpe_override__", "fpe_to_wbom",
    "fpe_wbom_link", "fpe_writes", "fpe_dlq_backlog",
})
