---
title: Cash Business Rules
owner: Fazle Core Admin
status: active
last_verified: 2026-06-24
runtime_index: true
---

# Cash Business Rules

## Purpose
Define cash ledger behavior and accountant handoff rules.

## Rules
- **Superseded 2026-10-17:** Accountant handoff is not proof of payment completion. This reference repo is not the AL-RIFA’I cash writer. The canonical AL-RIFA’I Owner → Accountant identity gate is in `docs/AL-RIFAI-CASH-PAYMENT-POLICY.md`.
- Only a message that passes the verified Owner sender, actual Accountant direct-chat recipient/JID, cash intent, reliable employee mobile, source/detail validation and idempotency gates may become an instruction record. Any uncertain condition means review only, no Cash Transaction.
- Multiple payment transactions may exist in one admin message.
- Ledger update must preserve transaction amount, method, employee/name, phone, purpose, and date.
- Duplicate prevention must run before final ledger update.

## Payment Methods
- bKash.
- Nagad.
- Cash.
- Conveyance marker may be included as conv.

## Cross References
- payment_business_rules.md
- ../05_workflows/cash_workflow.md
