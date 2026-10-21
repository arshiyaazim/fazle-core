-- Backfill ALL skipped/failed messages into fpe_unmatched_messages so they
-- appear in /payroll/review for admin verification.
--
-- Safe to re-run: WHERE NOT EXISTS guard prevents duplicate review rows for
-- the same fpe_wa_message_id. Ledger (fazle_cash_transactions) is NEVER touched.

INSERT INTO fpe_unmatched_messages (
    fpe_wa_message_id,
    reason,
    raw_content,
    detected_amount,
    detected_payout_phone,
    detected_employee_name,
    detected_payout_method,
    detected_txn_date,
    parser_confidence,
    review_status
)
SELECT
    mps.fpe_wa_message_id,
    CASE
        WHEN mps.status = 'failed' THEN 'parser_failed'
        WHEN pr.message_type IS NULL THEN
            CASE WHEN m.is_from_me THEN 'admin_unparsed' ELSE 'accountant_unparsed' END
        WHEN pr.message_type = 'payment' AND NOT m.is_from_me THEN 'accountant_reported_payment'
        WHEN pr.message_type = 'balance_summary' THEN 'balance_summary'
        WHEN pr.message_type = 'other' THEN
            CASE WHEN m.is_from_me THEN 'admin_other' ELSE 'accountant_other' END
        ELSE 'skipped_other'
    END                                                AS reason,
    m.raw_content,
    NULLIF(pr.parsed_data->>'amount','')::numeric(12,2)        AS detected_amount,
    NULLIF(pr.parsed_data->>'payout_phone','')                 AS detected_payout_phone,
    NULLIF(pr.parsed_data->>'employee_name_raw','')            AS detected_employee_name,
    NULLIF(pr.parsed_data->>'payout_method','')                AS detected_payout_method,
    NULLIF(pr.parsed_data->>'txn_date','')::date               AS detected_txn_date,
    pr.confidence                                              AS parser_confidence,
    'pending'                                                  AS review_status
FROM fpe_message_processing_state mps
JOIN fpe_wa_messages       m  ON m.id  = mps.fpe_wa_message_id
LEFT JOIN fpe_parser_results pr ON pr.fpe_wa_message_id = mps.fpe_wa_message_id
WHERE mps.status IN ('skipped','failed')
  AND NOT EXISTS (
      SELECT 1 FROM fpe_unmatched_messages u
      WHERE u.fpe_wa_message_id = mps.fpe_wa_message_id
  );

-- Show outcome
SELECT review_status, reason, COUNT(*) AS n
FROM fpe_unmatched_messages
GROUP BY review_status, reason
ORDER BY review_status, n DESC;
