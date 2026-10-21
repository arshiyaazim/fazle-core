# Workspace Review — April 29, 2026

> **Pre-unification schema note.** Table names in this document refer to the
> pre-unification schema. See `audits/prefix_unification_2026-10-21.md` for the
> current table names.
This document captures a read-only review of the active `/home/azim`
workspace, with focus on the live Fazle Core runtime, its supporting
services, and the operator workflows around message routing, media,
escort duty, attendance, and payments.

Follow-up planning document:
[WORKSPACE_IMPLEMENTATION_PLAN_2026-04-29.md](WORKSPACE_IMPLEMENTATION_PLAN_2026-04-29.md)

## Scope

The workspace contains multiple repos, backups, scripts, and archived
systems. The operational center of gravity is:

- `fazle-core/` — primary FastAPI runtime and dashboard
- `whatsapp-mcp/` — Bridge1 stack
- `whatsapp2/` — Bridge2 stack
- `system-agent/` — shadow admin path, not the main engine
- `scripts/`, `secure-env-backup/`, `backups/` — ops support and recovery

This review treats `fazle-core/` as the primary production system and
reads the rest of the workspace in that context.

## Executive Summary

The workspace is not a loose prototype. It contains a real production
operations engine with strong routing structure, explicit admin approval
loops, escort lifecycle handling, payment drafting, observability, and a
single-dashboard direction.

The strongest areas are:

- role-first inbound routing
- escort release to attendance to payment chaining
- draft-first control for risky actions
- practical operational tooling and backups

The weakest areas are:

- no learning loop from admin-edited drafts
- fragmented first-class media handling
- vessel and lighter data richer at extraction time than at downstream use
- finance correction and reversal workflow not clearly present
- performance tuned for safety on one node, not for horizontal scale

## Review Findings

### 1. Admin draft edits do not teach future replies

This is the highest-value functional gap.

The current `EDIT` command updates a single draft row in
[`../modules/admin_commands/__init__.py`](../modules/admin_commands/__init__.py).
That change fixes one message, but it does not update any reusable reply
template, knowledge base rule, prompt memory, or intent-specific example
store. New messages with the same intent still go back through the normal
generation and approval path.

Operationally, this means owner corrections are not compounding into a
smarter system. The system is supervised, but it is not learning.

### 2. Media capability exists, but the inbound path is split

The codebase has meaningful media infrastructure:

- escort-slip OCR via
  [`../modules/escort_slip_extractor/__init__.py`](../modules/escort_slip_extractor/__init__.py)
- voice transcription via
  [`../modules/voice_processor/__init__.py`](../modules/voice_processor/__init__.py)
- media-oriented endpoints in
  [`../app/main.py`](../app/main.py)

But the generic inbound webhook flow currently reduces image, audio,
document, and video messages to placeholder text before the rest of the
normal business workflow sees them. That means the system has media
processing capability, but it does not yet behave like media is a clean,
first-class input across the whole runtime.

Practical reading:

- OCR for escort/release flows is real
- voice processing exists
- general inbound media normalization is still incomplete

### 3. Performance is tuned for controlled reliability, not high parallelism

The performance posture is cautious and sensible for the current VPS.

Observed characteristics:

- single-process uvicorn launch in [`../run.py`](../run.py)
- explicit single-worker assumption in
  [`../modules/admin_commands/__init__.py`](../modules/admin_commands/__init__.py)
- serialized Ollama access in [`../app/ollama.py`](../app/ollama.py)
- semaphores around OCR and bulk compute in [`../app/main.py`](../app/main.py)

This is good engineering for a resource-constrained deployment because it
reduces duplicate command races, CPU spikes, and AI timeout storms.

The tradeoff is clear: under heavier concurrency, work will queue rather
than scale out. The system appears optimized for correctness and uptime,
not peak throughput.

### 4. Escort-duty workflow is one of the strongest parts of the system

Escort operations are better integrated than most other domains.

The active flow is roughly:

1. inbound escort message or release evidence arrives
2. routing hands off into escort-specific logic
3. release handling closes the active program
4. attendance is backfilled for the duty window
5. payment draft is created for admin review

That chain is visible across:

- [`../modules/message_router/__init__.py`](../modules/message_router/__init__.py)
- [`../modules/escort_lifecycle/__init__.py`](../modules/escort_lifecycle/__init__.py)
- [`../modules/payment_workflow/__init__.py`](../modules/payment_workflow/__init__.py)

This is a strong operational design because the system does not treat
escort duty as just chat classification. It treats it as a stateful
business lifecycle.

### 5. Vessel and lighter data are extracted better than they are consumed

The extractor expects structured vessel information, including mother and
lighter vessel fields. That is good. The limitation is downstream use.

Current state:

- vessel and lighter terms are recognized during slip extraction
- escort lifecycle and payment drafting can reference vessel data
- attendance backfill uses vessel context

But I did not find equally strong vessel-aware behavior for:

- matching incoming evidence back to the correct existing program
- reporting by mother vessel versus lighter vessel
- conflict handling when names vary in spelling or shorthand
- operational analytics centered on vessel or lighter identity

So the system is vessel-aware at capture time, but not yet fully
vessel-native in its downstream decision model.

### 6. Attendance is real, but still closer to controlled intake than a full attendance operations system

Attendance support is present and legitimate.

It can:

- detect attendance-like messages
- create approval-gated drafts
- save attendance rows after admin confirmation
- provide inline summaries
- backfill attendance from escort lifecycle events

The limitation is operator depth. In the reviewed code, attendance feels
like a reliable sub-workflow inside the chat engine rather than a full
first-class operations area with richer review, correction, and analysis
surfaces.

### 7. Cash payment workflow is operational, but correction paths look thin

The payment design is good in its forward path.

It supports draft creation, admin approval, and multiple methods such as
cash, bkash, and nagad. Finalization writes a ledger-style transaction
record and generates accountant-facing instruction text.

The main weakness is what happens after a mistake:

- I did not find a clear reversal command
- I did not find a visible adjustment workflow tied to the same operator path
- I did not find a strong operator-facing reconciliation surface in the
  current reviewed runtime

That makes the workflow usable, but more fragile during correction,
partial payment, or operator error scenarios.

## Workflow Map

### Primary live workflow

The actual primary engine is Fazle Core, not the shadow system-agent.

High-level runtime shape:

1. WhatsApp messages arrive from Meta or local bridge stacks
2. Fazle Core stores the inbound event
3. identity logic assigns a role or confidence-backed identity
4. the unified router decides the business path
5. modules either reply directly, create drafts, or notify admin
6. approved actions flow back out through protected send endpoints
7. observability, reports, backups, and dashboard endpoints expose runtime state

### Why the workflow is strong

The important architectural choice is that the system is role-first and
workflow-first, not only prompt-first. The LLM is part of the system,
but it is not the entire system. Business rules, approval gates,
structured admin commands, and background jobs carry a large share of the
real workload.

That is the right design for payroll, escort, and audit-sensitive use
cases.

## Performance Assessment

### What looks healthy

- async FastAPI runtime instead of synchronous request chaining
- bounded concurrency around expensive compute
- background workers for outbound and scheduler duties
- Prometheus-style observability support
- practical ops scripts and service controls around the repo

### What will limit growth first

- single-worker assumptions
- serialized AI generation path
- in-process dedup logic
- likely operator dependence for final approvals and corrections

### Practical conclusion

For the current environment, the system appears tuned for stable daily
production use. For larger throughput or more simultaneous admin and
bridge activity, the first pain will likely be latency and queueing
rather than immediate correctness failure.

## Domain Notes

### Media capability

Current capability level: medium.

Strong for domain-specific OCR, weaker for generalized media-first
conversation handling.

### Escort duty, vessel, lighter

Current capability level: medium to high.

The lifecycle logic is strong. The missing layer is deeper downstream use
of vessel identity for matching, reporting, and conflict handling.

### Attendance

Current capability level: medium.

Reliable enough for intake and admin-controlled recording. Less mature as
its own analytical operations domain.

### Cash payment

Current capability level: medium.

The approval and posting path is present. Correction, reversal, and
reconciliation visibility need more depth.

## Recommendations

### Near-term priorities

1. Promote admin-edited drafts into reusable supervised knowledge.
2. Make inbound media routing first-class instead of placeholder-based.
3. Carry vessel and lighter identity deeper into lifecycle matching and reporting.
4. Add explicit payment reversal and adjustment workflows.
5. Strengthen operator surfaces for attendance and reconciliation.

### Architecture priorities

1. Preserve the current role-first router and approval-first workflow model.
2. Keep Fazle Core as the single primary engine and avoid splitting authority across shadow systems.
3. If throughput needs rise, move dedup and coordination assumptions out of one process before increasing worker count.

### Workspace hygiene priorities

1. Keep active runtime, backups, and archives clearly separated.
2. Continue documenting the real runtime rather than aspirational side systems.
3. Maintain dashboard work as the main operator surface instead of reviving parallel webapp directions.

## Bottom Line

This workspace contains a serious operations platform, not just a chatbot.

Its core strengths are workflow structure, admin control, escort
lifecycle handling, and operational discipline. Its main next-step value
is not more raw AI generation. The highest return will come from making
owner corrections reusable, tightening media integration, deepening
vessel-aware workflow, and improving payment correction and attendance
operations.