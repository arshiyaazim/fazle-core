# Vessel Register read-only Core contract

Status: local/preview implementation only. No Site publication or production
configuration is performed by this document.

The Site's server-side `/api/core` proxy should call Fazle Core using HTTPS and
the `X-Internal-Key` header. Configure the same private value as
`FAZLE_CORE_READ_KEY` on Core and `FAZLE_CORE_READ_KEY` in the Site server
environment. Do not put the value in browser JavaScript, Site D1 data, or
client-visible responses.

## Allowed read routes

| Site view | Core route | Purpose |
|---|---|---|
| `status` | `GET /api/fpe/health` | sanitized FPE health/counts |
| `transactions` | `GET /api/fpe/transactions` | canonical finalized cash transactions with bounded filters/pagination |
| `employees` | `GET /api/fpe/employees/search?q=...` | bounded employee search |
| `reviews` | `GET /api/fpe/unmatched?reviewed=false&limit=50` | unmatched/review queue read |
| `stats` | `GET /api/fpe/stats` | pipeline statistics |

The read key is accepted only on these explicitly scoped GET routes. It is not
accepted by ingest, manual transaction, reversal, employee mutation, draft
approval, outbound send, admin, or maintenance routes. Existing local/admin
RBAC viewer access remains available when `FAZLE_CORE_READ_KEY` is blank.

## Data rules

- `fpe_cash_transactions.amount` is a BDT numeric amount, not integer cents.
- `txn_date` is the business date; `created_at` is ingestion/record time.
- A blank `transaction_status` must not be interpreted as paid or confirmed.
- Employee identity is resolved from Core's canonical employee linkage; payout
  phone is not an employee merge key.
- The Site must preserve `employee_id`, `txn_ref`, `id`, and source references.
- Pagination and filters must be passed through with bounded limits.

## Message context boundary

Core's WhatsApp router reads operational vessel context from its own canonical
`wbom_escort_programs` records. The context helper is read-only and returns
only program/vessel/destination/date/shift/status fields. It does not call the
Site, write a draft, enqueue a WhatsApp message, send, post a ledger entry, or
infer an assignment when the match is ambiguous.

## Draft preview boundary

`modules.vessel_register_context.render_draft_preview()` produces a preview
with `draft_only=true`, `approved=false`, `sent=false`, and `posted=false`.
It is not an approval or outbound operation. Any future Site UI integration
must preserve these flags and use the existing Core approval/outbound flow.

## Site-side handoff checklist

1. Use the existing Site `/api/core` proxy; do not expose the Core key to the
   browser.
2. Set `FAZLE_CORE_URL` to the private HTTPS Core origin.
3. Set `FAZLE_CORE_READ_KEY` privately on the Site server and Core.
4. Reject redirects, arbitrary upstream paths, non-HTTPS production URLs, and
   non-JSON responses.
5. Show a stale/unavailable state when Core times out; do not fabricate data.
6. Keep Site writes and Core writes disabled for this phase.
