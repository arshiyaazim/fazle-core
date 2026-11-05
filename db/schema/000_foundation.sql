-- Fazle Core portable PostgreSQL bootstrap foundation.
-- Source: production-derived/test-certified baseline formerly embedded only in
-- tests/conftest.py. Apply before numbered migrations on a NEW EMPTY database.
-- Existing databases must use db/migrate.py, not replay this foundation.

-- Recruitment candidate tables — pre-date db/migrations/ (production tables
-- since before the numbered migration era; no CREATE TABLE anywhere in the
-- repo until this stub). Column set + CHECK constraints mirror the live
-- `postgres` DB as captured 2026-08-29. `post_intake_status` (migration
-- 072) and `linked_employee_id` (migration 077) are deliberately NOT here
-- so those migrations actually apply against this schema in tests.
CREATE TABLE IF NOT EXISTS wbom_candidates (
    candidate_id        BIGSERIAL PRIMARY KEY,
    phone               VARCHAR(20) NOT NULL,
    full_name           VARCHAR(100),
    age                 INTEGER,
    area                VARCHAR(100),
    job_preference      VARCHAR(50),
    experience_years    INTEGER,
    available_join_date DATE,
    funnel_stage        VARCHAR(30) NOT NULL DEFAULT 'new'
        CHECK (funnel_stage IN ('new','collecting','scored','assigned','contacted','interviewed','hired','rejected','dropped')),
    collection_step     VARCHAR(30) DEFAULT 'name',
    score               INTEGER NOT NULL DEFAULT 0 CHECK (score >= 0 AND score <= 100),
    score_bucket        VARCHAR(10) NOT NULL DEFAULT 'cold' CHECK (score_bucket IN ('hot','warm','cold')),
    assigned_recruiter  VARCHAR(80),
    assigned_at         TIMESTAMPTZ,
    last_contact_at     TIMESTAMPTZ,
    next_follow_up_at   TIMESTAMPTZ,
    source              VARCHAR(30) DEFAULT 'whatsapp',
    source_message      TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_phone ON wbom_candidates(phone);

CREATE TABLE IF NOT EXISTS wbom_candidate_conversations (
    conv_id       BIGSERIAL PRIMARY KEY,
    candidate_id  BIGINT NOT NULL REFERENCES wbom_candidates(candidate_id) ON DELETE CASCADE,
    step          VARCHAR(30) NOT NULL,
    direction     VARCHAR(10) NOT NULL DEFAULT 'inbound',
    message_text  TEXT NOT NULL,
    collected_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_bridge TEXT,
    message_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_conv_candidate ON wbom_candidate_conversations(candidate_id);

CREATE TABLE IF NOT EXISTS wbom_recruitment_reminders (
    reminder_id  BIGSERIAL PRIMARY KEY,
    candidate_id BIGINT NOT NULL REFERENCES wbom_candidates(candidate_id) ON DELETE CASCADE,
    due_at       TIMESTAMPTZ NOT NULL,
    reason       VARCHAR(100) NOT NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','dismissed')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- WBOM core tables (pre-date all migrations)
CREATE TABLE IF NOT EXISTS fazle_employees_legacy (
    employee_id   SERIAL PRIMARY KEY,
    employee_mobile VARCHAR(20) UNIQUE NOT NULL,
    employee_name VARCHAR(100) NOT NULL,
    designation   VARCHAR(30) DEFAULT 'Security Guard',
    joining_date  DATE,
    status        VARCHAR(20) DEFAULT 'Active',
    basic_salary  DECIMAL(10,2) DEFAULT 0,
    bkash_number  VARCHAR(20),
    nagad_number  VARCHAR(20),
    nid_number    VARCHAR(20),
    bank_account  VARCHAR(50),
    emergency_contact VARCHAR(20),
    address       TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Matches db/migrations/029's real production schema (contact_name/
-- contact_type never existed in production -- this stub previously guessed
-- wrong column names, the same class of bug fixed in identity_brain's
-- _lookup_contact() on 2026-07-11; it shadows 029's CREATE TABLE IF NOT
-- EXISTS since this bootstrap runs first, so keeping it wrong here means
-- every test silently ran against a schema production never had).
CREATE TABLE IF NOT EXISTS fazle_contacts (
    contact_id      SERIAL PRIMARY KEY,
    whatsapp_number VARCHAR(50) NOT NULL,
    display_name    VARCHAR(200) NOT NULL DEFAULT '',
    company_name    VARCHAR(300),
    relation_type_id INT,
    business_type_id INT,
    is_active       BOOLEAN DEFAULT TRUE,
    relation        VARCHAR(100) DEFAULT 'unknown',
    platform        VARCHAR(20) DEFAULT 'whatsapp',
    notes           TEXT,
    personality_hint VARCHAR(200) DEFAULT '',
    interaction_count INTEGER DEFAULT 0,
    interest_level VARCHAR(20) DEFAULT 'unknown',
    last_seen      TIMESTAMPTZ DEFAULT NOW(),
    keep_reason    TEXT,
    triage_at      TIMESTAMPTZ DEFAULT NOW(),
    keep_tier      TEXT,
    marked_for_delete_at TIMESTAMPTZ,
    is_protected   BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wbom_escort_programs (
    program_id    SERIAL PRIMARY KEY,
    mother_vessel VARCHAR(100),
    lighter_vessel VARCHAR(100),
    master_mobile VARCHAR(20),
    destination   VARCHAR(100),
    cargo_type    VARCHAR(100),
    importer      VARCHAR(100),
    escort_name   VARCHAR(100),
    escort_employee_id INT REFERENCES fazle_employees_legacy(employee_id),
    escort_mobile VARCHAR(20),
    program_date  DATE,
    shift         VARCHAR(1) DEFAULT 'D',
    status        VARCHAR(20) DEFAULT 'Assigned',
    is_historical BOOLEAN DEFAULT FALSE,
    start_date    DATE,
    assignment_time TIMESTAMPTZ DEFAULT NOW(),
    end_date      DATE,
    end_shift     VARCHAR(1),
    release_point VARCHAR(100),
    day_count     FLOAT,
    conveyance    DECIMAL(10,2) DEFAULT 0,
    food_bill     DECIMAL(10,2) DEFAULT 0,
    capacity      VARCHAR(20),
    completion_time TIMESTAMPTZ,
    total_payment DECIMAL(10,2) DEFAULT 0,
    release_location VARCHAR(100),
    contact_id    INT REFERENCES fazle_contacts(contact_id),
    remarks       TEXT,
    whatsapp_message_id INT,
    created_at    TIMESTAMPTZ DEFAULT NOW()
    -- NOTE (found 2026-07-19, Dispatch Phase 2A.3 Stage 6): production's
    -- real wbom_escort_programs has NO created_at column (confirmed via
    -- information_schema.columns) -- this stub column is stale test-only
    -- drift in the OPPOSITE direction of the escort_shift_logs/
    -- escort_release_matches gaps above. Do not write application code
    -- that relies on wbom_escort_programs.created_at existing -- use
    -- assignment_time (present in both environments) instead.
);

CREATE TABLE IF NOT EXISTS wbom_attendance (
    attendance_id SERIAL PRIMARY KEY,
    employee_id   INT REFERENCES fazle_employees_legacy(employee_id) ON DELETE CASCADE,
    attendance_date DATE NOT NULL,
    status        VARCHAR(20) DEFAULT 'Present',
    location      VARCHAR(100),
    check_in_time TIMESTAMPTZ,
    check_out_time TIMESTAMPTZ,
    remarks       TEXT,
    recorded_by   VARCHAR(50),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (employee_id, attendance_date)
);

CREATE TABLE IF NOT EXISTS fazle_cash_transactions_archive (
    transaction_id SERIAL PRIMARY KEY,
    employee_id   INT REFERENCES fazle_employees_legacy(employee_id) ON DELETE CASCADE,
    program_id    INT REFERENCES wbom_escort_programs(program_id),
    transaction_type VARCHAR(20) NOT NULL,
    amount        DECIMAL(10,2) NOT NULL,
    payment_method VARCHAR(10),
    payment_mobile VARCHAR(20),
    employee_phone TEXT,
    payment_number TEXT,
    transaction_date DATE DEFAULT CURRENT_DATE,
    transaction_time TIMESTAMPTZ DEFAULT NOW(),
    status        VARCHAR(20) DEFAULT 'Completed',
    reference_number VARCHAR(50),
    remarks       TEXT,
    created_by    VARCHAR(50),
    source        TEXT,
    idempotency_key TEXT,
    whatsapp_message_id VARCHAR(100),
    approved_by   TEXT,
    approved_at   TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_test_txn_idempotency
    ON fazle_cash_transactions_archive (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS wbom_staging_payments (
    staging_id      SERIAL PRIMARY KEY,
    message_id      INT,
    sender_number   VARCHAR(20),
    extracted_name  VARCHAR(100),
    extracted_mobile VARCHAR(20),
    amount          DECIMAL(12,2),
    payment_method  VARCHAR(20),
    transaction_type VARCHAR(30),
    matched_employee_id INT REFERENCES fazle_employees_legacy(employee_id),
    name_match_ratio NUMERIC(4,2),
    status          VARCHAR(20) DEFAULT 'pending',
    approved_by     VARCHAR(100),
    approved_at     TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    final_transaction_id INT REFERENCES fazle_cash_transactions_archive(transaction_id),
    idempotency_key VARCHAR(64)
);
CREATE INDEX IF NOT EXISTS idx_staging_payments_status
    ON wbom_staging_payments (status);

CREATE TABLE IF NOT EXISTS wbom_payroll_runs (
    run_id        SERIAL PRIMARY KEY,
    employee_id   INT REFERENCES fazle_employees_legacy(employee_id),
    period_year   INT,
    period_month  INT,
    status        VARCHAR(20) DEFAULT 'draft',
    basic_salary  DECIMAL(10,2) DEFAULT 0,
    total_programs INT DEFAULT 0,
    per_program_rate DECIMAL(10,2) DEFAULT 0,
    program_allowance DECIMAL(10,2) DEFAULT 0,
    other_allowance DECIMAL(10,2) DEFAULT 0,
    total_advances DECIMAL(10,2) DEFAULT 0,
    total_deductions DECIMAL(10,2) DEFAULT 0,
    gross_salary  DECIMAL(10,2) DEFAULT 0,
    net_salary    DECIMAL(10,2) DEFAULT 0,
    computed_by   VARCHAR(50),
    submitted_by  VARCHAR(50),
    approved_by   VARCHAR(50),
    locked_by     VARCHAR(50),
    paid_by       VARCHAR(50),
    paid_at       TIMESTAMPTZ,
    payment_method        VARCHAR(20),
    payment_reference     TEXT,
    payout_idempotency_key TEXT UNIQUE,
    correction_reason     TEXT,
    computed_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wbom_payroll_run_items (
    item_id       SERIAL PRIMARY KEY,
    run_id        INT REFERENCES wbom_payroll_runs(run_id) ON DELETE CASCADE,
    component_type VARCHAR(50),
    component_label VARCHAR(200),
    amount        DECIMAL(10,2),
    sign          VARCHAR(1) DEFAULT '+',
    source_table  VARCHAR(50),
    source_id     INT,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS wbom_payroll_approval_log (
    log_id        SERIAL PRIMARY KEY,
    run_id        INT REFERENCES wbom_payroll_runs(run_id),
    action        VARCHAR(50),
    from_status   VARCHAR(20),
    to_status     VARCHAR(20),
    actor         VARCHAR(50),
    reason        TEXT,
    note          TEXT,
    payload_json  JSONB,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wbom_salary_records (
    record_id     SERIAL PRIMARY KEY,
    employee_id   INT REFERENCES fazle_employees_legacy(employee_id),
    salary_month  VARCHAR(7),
    amount        DECIMAL(10,2),
    status        VARCHAR(20) DEFAULT 'Pending',
    payment_date  DATE,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wbom_employee_requests (
    request_id    SERIAL PRIMARY KEY,
    employee_id   INT REFERENCES fazle_employees_legacy(employee_id),
    request_type  VARCHAR(30),
    amount        DECIMAL(10,2),
    status        VARCHAR(20) DEFAULT 'pending',
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wbom_cases (
    case_id       SERIAL PRIMARY KEY,
    employee_id   INT REFERENCES fazle_employees_legacy(employee_id),
    case_type     VARCHAR(30),
    description   TEXT,
    status        VARCHAR(20) DEFAULT 'open',
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fazle_whatsapp_messages (
    message_id          SERIAL PRIMARY KEY,
    sender_number       TEXT,
    message_body        TEXT,
    message_type        TEXT DEFAULT 'text',
    direction           TEXT,
    platform            TEXT,
    is_processed        BOOLEAN DEFAULT TRUE,
    contact_identifier  TEXT,
    contact_id          INT,
    identity_role       TEXT,
    identity_confidence FLOAT DEFAULT 0,
    workflow_triggered  TEXT,
    received_at         TIMESTAMPTZ DEFAULT NOW(),
    metadata_json       JSONB,
    canonical_phone     TEXT,
    phone_last10        TEXT,
    source_message_ref  TEXT,
    source_timestamp    TIMESTAMPTZ,
    source_context      TEXT,
    message_hash        TEXT UNIQUE,
    critical_contact    BOOLEAN DEFAULT FALSE,
    original_sender_number TEXT,
    critical_log_path   TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- fazle_contact_roles (pre-migration: migration 004 ALTERs it, but we pre-add
-- the columns so they survive even if migration 004's BEGIN/COMMIT transaction
-- rolls back due to seed INSERT failures)
--
-- SCHEMA DRIFT FIX (2026-07-18, Phase 1D): this stub previously defined a
-- shape (id SERIAL, a 'label' column, no sub_role/language_pref/is_active/
-- metadata) that never matched production and never matched migration
-- 029_bootstrap_core_tables_schema_record.sql's own CREATE TABLE IF NOT
-- EXISTS for this table either — because this stub runs first, migration
-- 029's version silently no-op'd against an already-existing (wrong) table
-- every time the test schema was built. Corrected to match migration 029
-- (and live production) exactly. See knowledge_base/00_governance/
-- management_decisions.md, Phase 1D, for the full drift table.
CREATE TABLE IF NOT EXISTS fazle_contact_roles (
    id              uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    phone           character varying(20) NOT NULL,
    name            character varying(200) DEFAULT ''::character varying NOT NULL,
    role            character varying(30) DEFAULT 'unknown'::character varying NOT NULL,
    sub_role        character varying(30) DEFAULT ''::character varying NOT NULL,
    language_pref   character varying(10) DEFAULT ''::character varying NOT NULL,
    platform        character varying(20) DEFAULT 'whatsapp'::character varying NOT NULL,
    is_active       boolean DEFAULT true,
    metadata        jsonb DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    confidence      INTEGER NOT NULL DEFAULT 0,
    source          TEXT    NOT NULL DEFAULT 'seed_rule',
    priority        INTEGER NOT NULL DEFAULT 50,
    notes           TEXT    NOT NULL DEFAULT '',
    UNIQUE (phone),
    UNIQUE (phone, platform)
);

-- Admin tables (pre-migration)
CREATE TABLE IF NOT EXISTS fazle_roles (
    id            SERIAL PRIMARY KEY,
    name          TEXT UNIQUE,
    level         INT,
    description   TEXT
);

CREATE TABLE IF NOT EXISTS fazle_admins (
    id            SERIAL PRIMARY KEY,
    phone         TEXT UNIQUE,
    name          TEXT,
    username      TEXT,
    status        TEXT DEFAULT 'active',
    notes         TEXT,
    api_key_hash  TEXT,
    password_hash TEXT,
    login_token_hash TEXT,
    last_seen_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fazle_admin_roles (
    id            SERIAL PRIMARY KEY,
    admin_id      INT REFERENCES fazle_admins(id) ON DELETE CASCADE,
    role_name     TEXT REFERENCES fazle_roles(name),
    granted_by    TEXT,
    UNIQUE (admin_id, role_name)
);

CREATE TABLE IF NOT EXISTS fazle_admin_audit (
    id                SERIAL PRIMARY KEY,
    actor_phone       TEXT,
    actor_user_id     INT,
    actor_label       TEXT,
    channel           TEXT,
    command           TEXT,
    args              TEXT,
    allowed           BOOLEAN,
    required_role     TEXT,
    denied_reason     TEXT,
    result_summary    TEXT,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Misc runtime tables that pre-date migrations
CREATE TABLE IF NOT EXISTS fazle_report_cache (
    cache_key     TEXT PRIMARY KEY,
    payload       JSONB,
    expires_at    TIMESTAMPTZ
);

-- Column is `service`, not `service_name`: every reader/writer uses `service`
-- (app/main.py::_probe_heartbeat, modules/scheduler, modules/fazle_bridge_poller,
-- modules/social_auto_reply/daemon_worker) and so does the production table
-- declared in db/migrations/029. This stub previously said `service_name`, which
-- made every heartbeat probe and every heartbeat-dependent test fail with
-- `column "service" does not exist` on a test database. Fixed 2026-10-27.
CREATE TABLE IF NOT EXISTS fazle_service_heartbeats (
    service           TEXT PRIMARY KEY,
    last_seen         TIMESTAMPTZ DEFAULT NOW(),
    last_message_id   TEXT,
    queue_depth       INT DEFAULT 0,
    meta_json         JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS fazle_db_backups (
    id            BIGSERIAL PRIMARY KEY,
    filename      VARCHAR(200),
    path          TEXT,
    size_bytes    BIGINT,
    sha256        VARCHAR(64),
    status        VARCHAR(20) DEFAULT 'ok',
    duration_ms   INT,
    error         TEXT,
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    rotated_at    TIMESTAMPTZ
);

-- escort_roster_entries (referenced by migration 008 FK)
CREATE TABLE IF NOT EXISTS escort_roster_entries (
    id SERIAL PRIMARY KEY,
    program_id INT UNIQUE NOT NULL,
    mother_vessel TEXT, lighter_vessel TEXT, master_mobile TEXT,
    escort_name TEXT, escort_mobile TEXT, destination TEXT,
    start_date DATE, start_shift CHAR(1), end_date DATE, end_shift CHAR(1),
    total_shifts INT, total_days NUMERIC(6,2), salary NUMERIC(10,2),
    conveyance NUMERIC(10,2) DEFAULT 0, food_bill NUMERIC(10,2) DEFAULT 0,
    advance_deduction NUMERIC(12,2) DEFAULT 0, net_payable NUMERIC(12,2) DEFAULT 0,
    total NUMERIC(12,2), release_point TEXT, roster_status TEXT DEFAULT 'draft',
    calc_version INT DEFAULT 1, notes TEXT, last_synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- escort_calculation_config / escort_roster_audit_logs: defined in the
-- separate, non-db/migrations/ file migrations/escort_roster_schema.sql
-- (production has both, confirmed live via GET /api/escort-roster/config
-- and the "[audit] log_audit failed: relation ... does not exist" warning
-- seen in test runs) -- never ported into the db/migrations/ set this
-- fixture's _run_all_migrations() scans, so they were missing from every
-- test DB. Added here 2026-07-18 (Phase 1I) after this gap blocked a
-- concurrency reproduction from exercising sync_program_to_roster()'s real
-- pay-calculation code path. Column shapes copied verbatim from that file.
CREATE TABLE IF NOT EXISTS escort_calculation_config (
    id SERIAL PRIMARY KEY,
    destination VARCHAR(120) NOT NULL,
    destination_key VARCHAR(120) NOT NULL UNIQUE,
    conveyance_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
    shift_rate NUMERIC(10,2) NOT NULL DEFAULT 200,
    notes TEXT, updated_by TEXT, updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO escort_calculation_config
    (destination, destination_key, conveyance_amount, shift_rate)
VALUES
    ('Narayanganj', 'narayanganj', 600,  200),
    ('Noapara',     'noapara',     1000, 200),
    ('Nagarbari',   'nagarbari',   900,  200),
    ('Aricha',      'aricha',      900,  200),
    ('Bhairab',     'bhairab',     800,  200),
    ('Ashuganj',    'ashuganj',    800,  200),
    ('Chandpur',    'chandpur',    700,  200),
    ('Barishal',    'barishal',    1200, 200),
    ('Mongla',      'mongla',      1500, 200)
ON CONFLICT (destination_key) DO NOTHING;

CREATE TABLE IF NOT EXISTS escort_roster_audit_logs (
    id SERIAL PRIMARY KEY,
    program_id INTEGER NOT NULL,
    roster_entry_id INTEGER,
    action VARCHAR(60) NOT NULL,
    old_data JSONB, new_data JSONB,
    performed_by TEXT, source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- escort_shift_logs: same gap as escort_calculation_config/
-- escort_roster_audit_logs above (defined only in migrations/
-- escort_roster_schema.sql, never ported into db/migrations/). Found
-- 2026-07-19 (Dispatch Phase 2A.3 Stage 3): _write_shift_log()
-- (modules/escort_roster/db.py) swallows the resulting UndefinedTableError
-- internally, but that does not undo Postgres's transaction-abort state --
-- every subsequent statement in the same transaction then fails with
-- "current transaction is aborted", masking the real cause. Column shapes
-- copied verbatim from that file.
CREATE TABLE IF NOT EXISTS escort_shift_logs (
    id SERIAL PRIMARY KEY,
    program_id INTEGER NOT NULL,
    shift_date DATE NOT NULL,
    shift CHAR(1) NOT NULL CHECK (shift IN ('D', 'N')),
    log_type VARCHAR(20) NOT NULL,
    notes TEXT, recorded_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- escort_release_matches: same gap as escort_shift_logs above (defined
-- only in migrations/escort_roster_schema.sql, never ported into
-- db/migrations/ -- confirmed present in production, 0 rows, via direct
-- to_regclass() check). Found 2026-07-19 (Dispatch Phase 2A.3 Stage 5)
-- before it could repeat the same transaction-abort masking failure mode.
-- Column shapes copied verbatim from that file.
CREATE TABLE IF NOT EXISTS escort_release_matches (
    id SERIAL PRIMARY KEY,
    extraction_id INTEGER,
    program_id INTEGER,
    match_confidence NUMERIC(5,4) DEFAULT 0,
    match_reason TEXT,
    matched_fields JSONB DEFAULT '{}',
    admin_action VARCHAR(20),
    admin_phone TEXT,
    acted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
