# B26 — Reviewed Reply Memory Implementation Checklist

This checklist turns
[B26_REVIEWED_REPLY_MEMORY_DESIGN.md](B26_REVIEWED_REPLY_MEMORY_DESIGN.md)
into an implementation-ready worklist with exact files, migration name,
 endpoints, and test cases.

## Execution Boundary

This checklist is for the first shippable `B26` cut only.

Included:

- reviewed reply persistence
- `EDIT`-driven reviewed entry creation
- conservative reviewed lookup during future draft generation
- minimal admin HTTP surface for inspect and disable
- minimal dashboard visibility
- unit and integration coverage for the reviewed path

Not included in this first cut:

- broad text-similarity reuse
- automatic learning from approved or sent drafts
- payment correction logic from `B28`
- media pipeline work from `B27`

## Exact Files

### New files to add

- [ ] `db/migrations/007_reviewed_reply_memory.sql`
- [ ] `modules/reviewed_reply_memory/__init__.py`
- [ ] `scripts/test_batch26_reviewed_reply_memory.py`

### Existing files to update

- [ ] `app/config.py`
- [ ] `app/main.py`
- [ ] `modules/fazle_admin_commands/__init__.py`
- [ ] `modules/message_router/__init__.py`
- [ ] `modules/fazle_bridge_poller/__init__.py`
- [ ] `app/static/dashboard.html`
- [ ] `docs/API.md`
- [ ] `scripts/run_ci.sh`
- [ ] `.github/workflows/ci.yml`

### Existing helper files to reuse without first-cut changes unless needed

- [ ] `modules/number_identity/__init__.py`
- [ ] `modules/draft_quality/__init__.py`
- [ ] `modules/observability/__init__.py`

## Migration Checklist

### File

- [ ] Create `db/migrations/007_reviewed_reply_memory.sql`

### SQL work

- [ ] Create table `fazle_reviewed_replies`
- [ ] Add columns from the design first cut:
  - `id BIGSERIAL PRIMARY KEY`
  - `source_draft_id BIGINT NOT NULL`
  - `source TEXT NOT NULL`
  - `intent TEXT NOT NULL`
  - `draft_type TEXT NOT NULL DEFAULT 'generic'`
  - `role TEXT`
  - `recipient_phone TEXT`
  - `last10_phone TEXT`
  - `language TEXT`
  - `normalized_trigger_text TEXT`
  - `match_scope TEXT NOT NULL DEFAULT 'intent_role_phone'`
  - `reply_text TEXT NOT NULL`
  - `status TEXT NOT NULL DEFAULT 'active'`
  - `priority INTEGER NOT NULL DEFAULT 100`
  - `usage_count INTEGER NOT NULL DEFAULT 0`
  - `last_used_at TIMESTAMPTZ`
  - `created_by TEXT`
  - `created_at TIMESTAMPTZ DEFAULT NOW()`
  - `updated_at TIMESTAMPTZ DEFAULT NOW()`
  - `meta JSONB NOT NULL DEFAULT '{}'`
- [ ] Add index on `(intent, role, draft_type, status)`
- [ ] Add index on `(last10_phone, status)`
- [ ] Add index on `(source_draft_id)`
- [ ] Do not add destructive changes to existing draft tables in `B26`
- [ ] Do not backfill reviewed entries from historical drafts in `B26`

### Migration validation

- [ ] Apply migration on local dev database
- [ ] Confirm table and indexes exist
- [ ] Confirm rollback plan is documented if manual rollback is needed

## Module Checklist

### `modules/reviewed_reply_memory/__init__.py`

- [ ] Add `create_or_update_from_edit(...)`
- [ ] Add `lookup_reviewed_reply(...)`
- [ ] Add `disable_reviewed_reply(...)`
- [ ] Add `reactivate_reviewed_reply(...)`
- [ ] Add `list_reviewed_replies(...)`
- [ ] Add helper `normalize_lookup_context(...)`
- [ ] Reuse `phone_last10()` from `modules/number_identity`
- [ ] Reuse `check_draft_quality()` from `modules/draft_quality`
- [ ] Emit observability counters for hit, miss, blocked, created, updated, disabled

### Matching rules to implement

- [ ] Match order is exactly:
  1. `intent + role + draft_type + last10_phone`
  2. `intent + role + draft_type`
  3. `intent + role`
- [ ] Reject disabled entries
- [ ] Reject cross-role matches
- [ ] Reject unsafe draft types in first cut
- [ ] Update `usage_count` and `last_used_at` on hit

## Backend Integration Checklist

### `modules/fazle_admin_commands/__init__.py`

- [ ] Keep the `EDIT <id> <text>` command syntax unchanged
- [ ] Update `_cmd_edit(...)` to fetch the full draft row, not only `id`
- [ ] Run edited text through `check_draft_quality()` before reviewed persistence
- [ ] After successful draft update, call `create_or_update_from_edit(...)`
- [ ] Write reviewed linkage into draft `meta` or equivalent lightweight field
- [ ] Preserve current human-facing success message for the operator

### `modules/message_router/__init__.py`

- [ ] Insert reviewed lookup after workflow-specific handlers and KB checks
- [ ] Keep deterministic business workflows ahead of reviewed lookup
- [ ] Run reviewed lookup before final generic AI fallback is accepted
- [ ] When a reviewed match is used, return the reviewed text as the candidate reply
- [ ] Make the reviewed decision visible to downstream draft persistence via metadata or reply context
- [ ] Preserve existing behavior when no reviewed match exists

### `app/main.py`

- [ ] Add `GET /admin/reviewed-replies`
- [ ] Add `POST /admin/reviewed-replies/{id}/disable`
- [ ] Add `POST /admin/reviewed-replies/{id}/reactivate`
- [ ] Use the existing `require_api_key` dependency on all new endpoints
- [ ] Extend draft persistence helper `_save_draft(...)` to accept optional metadata for reviewed-source markers
- [ ] Extend `/admin/drafts` response to include stored `meta` needed by the dashboard

### `modules/fazle_bridge_poller/__init__.py`

- [ ] Extend `_save_draft(...)` to accept optional metadata for reviewed-source markers
- [ ] Preserve draft-quality gate behavior on the bridge path
- [ ] Persist reviewed-source markers the same way as the main FastAPI path

### `app/config.py`

- [ ] Add `reviewed_reply_memory_enabled: bool = True`
- [ ] Load it from `.env` through the existing settings model
- [ ] Ensure the read path bypasses reviewed lookup when disabled

## Exact Endpoint Checklist

### 1. List reviewed replies

- [ ] Add `GET /admin/reviewed-replies`

Suggested query params:

- `limit=50`
- `status=active`
- `intent=`
- `role=`
- `phone=`

Suggested response shape:

```json
{
  "count": 1,
  "reviewed_replies": [
    {
      "id": 12,
      "intent": "salary_query",
      "draft_type": "generic",
      "role": "employee",
      "last10_phone": "844836824",
      "match_scope": "intent_role_phone",
      "reply_text": "...",
      "status": "active",
      "usage_count": 3,
      "last_used_at": "2026-04-29T12:00:00Z",
      "created_by": "8801880446111",
      "meta": {}
    }
  ]
}
```

### 2. Disable reviewed reply

- [ ] Add `POST /admin/reviewed-replies/{id}/disable`

Suggested request body:

```json
{
  "reason": "too broad"
}
```

Suggested response shape:

```json
{
  "ok": true,
  "id": 12,
  "status": "disabled"
}
```

### 3. Reactivate reviewed reply

- [ ] Add `POST /admin/reviewed-replies/{id}/reactivate`

Suggested response shape:

```json
{
  "ok": true,
  "id": 12,
  "status": "active"
}
```

### 4. No new WhatsApp admin command in `B26`

- [ ] Keep reviewed entry management HTTP-only in the first cut
- [ ] Do not add `ENABLE REVIEWED` or similar chat commands in `B26`

## Dashboard Checklist

### File

- [ ] Update `app/static/dashboard.html`

### Draft page changes

- [ ] Show a reviewed-source badge on draft rows when `meta.reviewed_reply_id` exists
- [ ] Show reviewed scope summary in the draft row or detail area
- [ ] Preserve existing draft navigation and filters

### New reviewed section

- [ ] Add a compact reviewed-replies box or section under the existing Drafts route
- [ ] Fetch from `GET /admin/reviewed-replies`
- [ ] Render columns for intent, role, scope, created-by, usage count, status, last used
- [ ] Add disable and reactivate buttons backed by the new endpoints
- [ ] Reuse existing loading, error, empty-state, and action-bar patterns

### Conversations page enhancement

- [ ] If a conversation-linked draft used reviewed memory, surface that in the Conversations draft list
- [ ] Do not create a new Conversations route for `B26`

## API Documentation Checklist

### `docs/API.md`

- [ ] Add `GET /admin/reviewed-replies`
- [ ] Add `POST /admin/reviewed-replies/{id}/disable`
- [ ] Add `POST /admin/reviewed-replies/{id}/reactivate`
- [ ] Mention `REVIEWED_REPLY_MEMORY_ENABLED` behavior briefly where relevant

## Test File Checklist

### New test file

- [ ] Create `scripts/test_batch26_reviewed_reply_memory.py`

### Required test cases

- [ ] `test_reviewed_lookup_prefers_phone_scoped_exact_match`
- [ ] `test_reviewed_lookup_falls_back_to_intent_role_after_phone_miss`
- [ ] `test_reviewed_lookup_blocks_wrong_role`
- [ ] `test_reviewed_lookup_skips_disabled_entries`
- [ ] `test_create_or_update_from_edit_creates_new_entry`
- [ ] `test_create_or_update_from_edit_updates_existing_same_scope_entry`
- [ ] `test_edit_flow_persists_reviewed_link_in_draft_meta`
- [ ] `test_message_router_uses_reviewed_reply_before_generic_ai_fallback`
- [ ] `test_message_router_preserves_current_behavior_on_reviewed_miss`
- [ ] `test_admin_reviewed_replies_list_endpoint_filters_active_entries`
- [ ] `test_admin_reviewed_reply_disable_endpoint_blocks_future_reuse`
- [ ] `test_reviewed_lookup_bypassed_when_feature_flag_disabled`

### Nice-to-have test cases if time remains in `B26`

- [ ] `test_conversation_draft_payload_exposes_reviewed_marker`
- [ ] `test_reviewed_reply_usage_count_increments_on_hit`
- [ ] `test_reviewed_reply_requires_quality_gate_pass`

## CI Checklist

### `scripts/run_ci.sh`

- [ ] Add `scripts/test_batch26_reviewed_reply_memory.py` to the offline test sequence

### `.github/workflows/ci.yml`

- [ ] Add a `Batch 26 reviewed reply memory test` step
- [ ] Run `python scripts/test_batch26_reviewed_reply_memory.py`

## Verification Checklist

### Manual backend verification

- [ ] Edit a draft with known intent and confirm a reviewed entry is created
- [ ] Trigger a same-intent future draft and confirm reviewed text is reused
- [ ] Disable the reviewed entry and confirm reuse stops
- [ ] Confirm no reviewed reuse occurs when the feature flag is off

### Manual dashboard verification

- [ ] Draft row shows reviewed badge when applicable
- [ ] Reviewed list loads on the Drafts page
- [ ] Disable action updates the reviewed list without breaking other draft UI

### Regression verification

- [ ] Existing `/admin/drafts` still loads cleanly
- [ ] Existing `/dashboard/drafts` still renders both reply and payment queues
- [ ] Existing finance, attendance, and escort flows still create drafts normally when no reviewed match exists

## Recommended Build Order

- [ ] 1. Add migration and module skeleton
- [ ] 2. Wire `EDIT` write path
- [ ] 3. Wire reviewed lookup into the generation path
- [ ] 4. Extend draft persistence metadata
- [ ] 5. Add admin endpoints
- [ ] 6. Add dashboard visibility
- [ ] 7. Add tests and CI hooks
- [ ] 8. Run manual verification on local copy

## Ship Gate For `B26`

Do not mark `B26` complete until all of the following are true:

- [ ] Migration applies cleanly
- [ ] Reviewed entries are created from eligible edits
- [ ] Reviewed lookup is conservative and observable
- [ ] Operators can inspect and disable reviewed entries
- [ ] Offline `B26` tests pass locally and in CI
- [ ] Existing draft workflows remain stable