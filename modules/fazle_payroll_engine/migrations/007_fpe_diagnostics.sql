-- Migration 007: FPE processing diagnostics table
--
-- Records per-message-type processing outcomes (status, failure reason, latency)
-- from the accounting and parser workers.  Used for:
--   • latency tracking (avg_ms, p95_ms per message type)
--   • failure analysis (top failure_reason codes)
--   • bridge health dashboard (see diagnostics.get_processing_stats())
--
-- This table is append-only.  Rows are never updated.
-- Old rows can be purged by a scheduled job (e.g. keep 90 days).

CREATE TABLE IF NOT EXISTS fpe_processing_diagnostics (
    id                  BIGSERIAL    PRIMARY KEY,
    fpe_wa_message_id   BIGINT       REFERENCES fpe_wa_messages(id) ON DELETE SET NULL,
    message_type        TEXT         NOT NULL DEFAULT 'unknown',
    worker_name         TEXT         NOT NULL,          -- 'accounting' | 'parser'
    processing_status   TEXT         NOT NULL,          -- 'done' | 'skipped' | 'failed'
    failure_reason      TEXT,                           -- skip/fail code; NULL on 'done'
    processing_ms       NUMERIC(10,2),                  -- wall-clock ms for this message
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Fast lookups for the dashboard and health stats queries
CREATE INDEX IF NOT EXISTS idx_fazle_diag_created
    ON fpe_processing_diagnostics (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_fazle_diag_type_status
    ON fpe_processing_diagnostics (message_type, processing_status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_fazle_diag_worker
    ON fpe_processing_diagnostics (worker_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_fazle_diag_failure
    ON fpe_processing_diagnostics (failure_reason, created_at DESC)
    WHERE failure_reason IS NOT NULL;

-- Comment describing the table contract
COMMENT ON TABLE fpe_processing_diagnostics IS
    'Append-only per-message processing outcomes for FPE workers. '
    'Used for latency tracking, failure analysis, and bridge health monitoring. '
    'Safe to purge rows older than 90 days.';
