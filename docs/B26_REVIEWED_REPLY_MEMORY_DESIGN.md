# B26 — Reviewed Reply Memory Design

> **Pre-unification schema note.** Table names in this document refer to the
> pre-unification schema. See `audits/prefix_unification_2026-10-21.md` for the
> current table names.
This document defines the technical design for `B26`, the first batch in
the `P0` execution sequence documented in
[WORKSPACE_P0_EXECUTION_BACKLOG_2026-04-29.md](WORKSPACE_P0_EXECUTION_BACKLOG_2026-04-29.md).

Implementation checklist:
[B26_REVIEWED_REPLY_MEMORY_IMPLEMENTATION_CHECKLIST.md](B26_REVIEWED_REPLY_MEMORY_IMPLEMENTATION_CHECKLIST.md)

## Why This Batch Exists

Today, admin `EDIT` changes only one row in `fazle_draft_replies`.

Observed current behavior:

- `EDIT` updates `reply_text`, `status`, and `admin_phone` for one draft
- draft creation already stores `intent` and can store `meta`
- there is no reviewed-reply lookup before the normal reply generation path
- there is no reusable operator-reviewed memory source for future drafts

The result is operator effort without cumulative improvement.

## Current Anchors

The design is grounded in these current code paths:

- admin edit path in
  [`../modules/admin_commands/__init__.py`](../modules/admin_commands/__init__.py)
- draft persistence in [`../app/main.py`](../app/main.py) and
  [`../modules/bridge_poller/__init__.py`](../modules/bridge_poller/__init__.py)
- main fallback generation path in
  [`../modules/message_router/__init__.py`](../modules/message_router/__init__.py)
- existing `reviewed` flag and `meta` support on `fazle_draft_replies`
  from the migrations under [`../db/migrations`](../db/migrations)

## Design Goal

Create an additive, inspectable reviewed-reply memory that can:

- learn from operator-corrected drafts
- match future draft-generation requests conservatively
- explain why a reviewed reply was selected
- fall back safely when no reviewed match is appropriate

## Non-Goals

- no autonomous self-learning from sent messages without operator review
- no model fine-tuning
- no replacement of the knowledge base or RAG stack
- no worker-scaling changes
- no silent rewrite of already-approved or already-sent replies

## Design Principles

- reviewed reuse must be explicit, conservative, and auditable
- role boundaries matter more than raw text similarity
- exact business context should beat broad intent buckets
- operators must be able to see and disable reviewed influence
- the new path must degrade cleanly to current behavior

## Proposed Architecture

### New module

Add a dedicated module, proposed name:

- `modules/reviewed_reply_memory`

This module owns:

- normalization of matching keys
- reviewed entry persistence
- lookup and scoring
- safety checks for reuse eligibility
- observability counters around reuse decisions

### New persistence model

Add a new table instead of overloading `fazle_draft_replies` as the
primary memory source.

Proposed table:

- `fazle_reviewed_replies`

Why a new table:

- draft rows are event history, not stable memory entries
- one draft may generate zero, one, or many reusable patterns over time
- memory rows need activation, confidence, and matching metadata that do
  not belong on every draft row
- this keeps audit history separate from reuse policy

## Proposed Schema

### `fazle_reviewed_replies`

Suggested columns:

- `id` `BIGSERIAL PRIMARY KEY`
- `source_draft_id` `BIGINT NOT NULL`
- `source` `TEXT NOT NULL`
- `intent` `TEXT NOT NULL`
- `draft_type` `TEXT NOT NULL DEFAULT 'generic'`
- `role` `TEXT`
- `recipient_phone` `TEXT`
- `last10_phone` `TEXT`
- `language` `TEXT`
- `normalized_trigger_text` `TEXT`
- `match_scope` `TEXT NOT NULL DEFAULT 'intent_role'`
- `reply_text` `TEXT NOT NULL`
- `status` `TEXT NOT NULL DEFAULT 'active'`
- `priority` `INTEGER NOT NULL DEFAULT 100`
- `usage_count` `INTEGER NOT NULL DEFAULT 0`
- `last_used_at` `TIMESTAMPTZ`
- `created_by` `TEXT`
- `created_at` `TIMESTAMPTZ DEFAULT NOW()`
- `updated_at` `TIMESTAMPTZ DEFAULT NOW()`
- `meta` `JSONB NOT NULL DEFAULT '{}'`

Suggested indexes:

- `(intent, role, status)`
- `(last10_phone, status)`
- `(draft_type, status)`
- `GIN (meta)` only if later queries justify it

### Suggested `meta` contents

- `source_reason`: `edited_draft` or future reviewed source types
- `original_reply_text`
- `review_note`
- `match_hints`
- `language_confidence`
- `created_from_status`
- `guard_version`

### Optional small extension to `fazle_draft_replies`

Keep the existing draft table as history and add only minimal linkage if
needed:

- `reviewed_reply_id` nullable foreign key
- or store the linkage in `meta.reviewed_reply_id`

The preferred first step is to use `meta` so the initial migration stays
lighter and more reversible.

## Matching Model

### Conservative matching order

When generating a draft, reviewed lookup should try the following order:

1. exact `intent + role + draft_type + last10_phone`
2. exact `intent + role + draft_type`
3. exact `intent + role`

No broader match should be allowed in `B26`.

This avoids leaking one corrected reply across unrelated recipients or
roles.

### Inputs required for lookup

The lookup function should receive:

- raw sender phone
- normalized last-10 phone
- intent
- role
- draft type
- candidate language if available
- current generated reply text

### Match eligibility guards

Reuse is allowed only when:

- reviewed entry is `active`
- intent matches exactly
- role matches exactly when role is known
- draft type matches or is explicitly marked generic-safe
- optional phone scope rules pass

Reuse must be denied when:

- the reviewed entry is disabled
- the reviewed entry is marked too specific for the current sender
- the current message belongs to a protected workflow where generic reuse
  is unsafe

## Write Path Design

### Source of truth for reviewed creation

The first write path should be admin `EDIT`.

Proposed behavior:

1. admin edits a pending draft
2. system updates the draft row as it does today
3. system evaluates whether the draft is eligible to become reviewed memory
4. if eligible, create or update a `fazle_reviewed_replies` row
5. store link and explanation in draft `meta`

### Eligibility rules for the first version

Create reviewed memory only when:

- source draft exists and is in a draft state that represents a model- or
  rule-generated candidate
- draft has non-empty `intent`
- edited text passes draft-quality checks

Do not create reviewed memory when:

- draft belongs to a structured finance or admin command confirmation path
- draft is already a system-generated explicit workflow notice that should
  stay deterministic elsewhere
- edited text is too short or too context-dependent

### Upsert strategy

First version should prefer simple deterministic upsert:

- same `intent + role + draft_type + last10_phone` updates the existing
  active entry
- otherwise insert a new active entry

This avoids multiple nearly-identical active entries for the same narrow
scope.

## Read Path Design

### Insertion point

Insert reviewed lookup after intent and role are known, but before the
final generic AI fallback is accepted for saving.

Practical target:

- in the common draft-generation path, after workflow-specific handlers
  and KB replies have had a chance to respond
- before a generated reply is persisted through `_save_draft`

This keeps stronger deterministic business logic ahead of reviewed reuse.

### Runtime behavior

If a reviewed match is found:

- use the reviewed `reply_text` as the candidate draft text
- mark the draft `meta` with reviewed source information
- increment reviewed usage counters
- emit observability counters for reviewed hit

If no reviewed match is found:

- continue with current behavior unchanged
- emit observability counters for reviewed miss

## Operator And Dashboard Surface

### Minimum operator visibility in B26

Add enough visibility so operators can trust the feature.

Minimum surface:

- draft rows indicate when a reviewed reply influenced the text
- drill-through or detail view shows the reviewed source entry
- ability to disable an active reviewed entry

### Suggested first dashboard surface

Keep it small in `B26`.

Recommended shape:

- a reviewed-reply section under the existing draft or conversations workflow
- list active reviewed entries
- show intent, role, scope, created-by, usage count, last-used
- basic actions: disable, inspect, maybe reactivate

## API And Command Surface

### Command behavior

Keep the existing `EDIT` syntax unchanged in `B26`.

Internal behavior changes only:

- `EDIT` becomes both a draft update and a reviewed-memory candidate writer

### HTTP surface

Recommended minimal internal endpoints:

- `GET /admin/reviewed-replies`
- `POST /admin/reviewed-replies/{id}/disable`
- optional `POST /admin/reviewed-replies/{id}/reactivate`

These should use the same protected internal-key and RBAC model as other
admin endpoints.

## Observability

Add counters first, not heavy analytics.

Suggested metrics:

- `reviewed_reply_lookup_total{result}` where result is `hit`, `miss`, `blocked`
- `reviewed_reply_created_total`
- `reviewed_reply_updated_total`
- `reviewed_reply_disabled_total`
- `reviewed_reply_used_total{scope}`

Suggested structured logging fields:

- `intent`
- `role`
- `draft_type`
- `reviewed_reply_id`
- `match_scope`
- `decision`

## Rollout Strategy

### Phase 1

- add schema and module
- wire `EDIT` write path
- add read path with conservative exact matching only
- add draft `meta` markers and counters

### Phase 2

- add minimal reviewed entry inspection UI
- add disable and reactivate controls
- monitor hit quality and operator trust

### Kill switch

Add env-driven disable path, proposed name:

- `REVIEWED_REPLY_MEMORY_ENABLED=true`

When disabled:

- write path may still record entries if desired for audit, or be fully disabled
- read path must bypass reviewed lookup entirely

## Testing Plan

### Unit tests

- normalization of lookup keys
- matching specificity order
- blocked reuse for wrong role or unsafe scope
- upsert behavior for repeated same-scope edits

### Integration tests

- `EDIT` creates reviewed entry when eligible
- same-intent future draft reuses reviewed text
- no-match case preserves current generation path
- disabled entry is not reused

### Regression checks

- finance and attendance workflows still behave as before when not eligible
- draft quality gate still rejects bad reviewed text
- existing draft list behavior remains stable

## Risks And Mitigations

### Risk: one reviewed reply becomes too broad

Mitigation:

- exact scope matching only in `B26`
- phone-scoped entries allowed before wider reuse
- operator-visible disable path

### Risk: reviewed replies hide why text changed

Mitigation:

- explicit draft badges and `meta` markers
- minimal inspectable reviewed list

### Risk: low-quality edits get preserved as memory

Mitigation:

- pass edited text through existing quality checks
- require non-empty intent and eligible draft types

## Open Decisions

These should be settled before implementation starts:

1. Should reviewed memory be created automatically on every eligible `EDIT`, or only when an operator explicitly marks it reusable?
2. Should phone-scoped entries be the default for the first rollout, with broader `intent + role` reuse enabled later?
3. Should reviewed entries live only in the dashboard, or also support lightweight WhatsApp admin commands for disable and inspect?

## Recommended First Cut

The safest first cut is:

1. new `fazle_reviewed_replies` table
2. automatic reviewed entry creation on eligible `EDIT`
3. exact `intent + role + draft_type + last10_phone` matching only
4. draft `meta` markers plus counters
5. minimal dashboard inspection and disable path

That version is small enough to ship, conservative enough to trust, and
useful enough to reduce repeated manual editing quickly.