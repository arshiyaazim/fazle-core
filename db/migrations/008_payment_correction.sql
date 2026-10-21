-- Batch 28 — Payment Correction & Reversal
-- Immutable ledger approach: never delete/modify original transactions.
-- Reversals write a counter-row; adjustments link to the original draft.

-- ── Extend fazle_cash_transactions_archive ─────────────────────────────────────────────
ALTER TABLE fazle_cash_transactions_archive
    ADD COLUMN IF NOT EXISTS is_reversed    BOOLEAN   DEFAULT false,
    ADD COLUMN IF NOT EXISTS reversal_of    INTEGER   REFERENCES fazle_cash_transactions_archive(transaction_id),
    ADD COLUMN IF NOT EXISTS correction_note TEXT;

-- ── Extend fazle_payment_drafts ───────────────────────────────────────────────
ALTER TABLE fazle_payment_drafts
    ADD COLUMN IF NOT EXISTS correction_of   INTEGER   REFERENCES fazle_payment_drafts(id),
    ADD COLUMN IF NOT EXISTS correction_type TEXT,      -- reversal | adjustment
    ADD COLUMN IF NOT EXISTS correction_note TEXT,
    ADD COLUMN IF NOT EXISTS corrected_by    TEXT,
    ADD COLUMN IF NOT EXISTS corrected_at    TIMESTAMPTZ;

-- ── Audit log for every correction decision ───────────────────────────────────
CREATE TABLE IF NOT EXISTS fazle_payment_correction_log (
    id               SERIAL PRIMARY KEY,
    action           TEXT        NOT NULL,    -- reversed | adjusted
    payment_draft_id INTEGER     NOT NULL REFERENCES fazle_payment_drafts(id),
    transaction_id   INTEGER,                 -- original transaction that was reversed
    counter_tx_id    INTEGER,                 -- reversal counter-transaction id, if any
    original_amount  FLOAT,
    correction_amount FLOAT,
    method           TEXT,
    note             TEXT,
    performed_by     TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pay_correction_log_draft
    ON fazle_payment_correction_log(payment_draft_id);
