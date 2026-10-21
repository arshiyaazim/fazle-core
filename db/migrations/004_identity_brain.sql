-- ============================================================
-- Migration 004: Identity Brain — contact role table upgrade
-- and seed data for known numbers.
-- Run: docker exec -i ai-postgres psql -U postgres -d postgres < db/migrations/004_identity_brain.sql
-- ============================================================

BEGIN;

-- ── 1. Extend fazle_contact_roles with identity brain columns ────────────────
ALTER TABLE fazle_contact_roles
    ADD COLUMN IF NOT EXISTS confidence INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS source     TEXT    NOT NULL DEFAULT 'seed_rule',
    ADD COLUMN IF NOT EXISTS priority   INTEGER NOT NULL DEFAULT 50,
    ADD COLUMN IF NOT EXISTS notes      TEXT    NOT NULL DEFAULT '';

-- ── 2. Extend fazle_whatsapp_messages with identity logging columns ───────────
ALTER TABLE fazle_whatsapp_messages
    ADD COLUMN IF NOT EXISTS identity_role       TEXT,
    ADD COLUMN IF NOT EXISTS identity_confidence INTEGER,
    ADD COLUMN IF NOT EXISTS workflow_triggered  TEXT;

-- ── 3. Seed static identity rules ────────────────────────────────────────────
-- On conflict: update role, confidence, priority, notes (phone+platform is unique)

-- Supervisors
INSERT INTO fazle_contact_roles (phone, name, role, confidence, source, priority, notes, platform)
VALUES
  ('01972694969', 'Supervisor 1', 'supervisor', 95, 'seed_rule', 80, 'Field supervisor', 'whatsapp'),
  ('01909956433', 'Supervisor 2', 'supervisor', 95, 'seed_rule', 80, 'Field supervisor', 'whatsapp'),
  ('01958122301', 'Supervisor 3', 'supervisor', 95, 'seed_rule', 80, 'Field supervisor', 'whatsapp'),
  ('01958122302', 'Supervisor 4', 'supervisor', 95, 'seed_rule', 80, 'Field supervisor', 'whatsapp'),
  ('01958122303', 'Supervisor 5', 'supervisor', 95, 'seed_rule', 80, 'Field supervisor', 'whatsapp')
ON CONFLICT (phone, platform) DO UPDATE SET
    role       = EXCLUDED.role,
    confidence = EXCLUDED.confidence,
    priority   = EXCLUDED.priority,
    notes      = EXCLUDED.notes,
    source     = EXCLUDED.source,
    updated_at = NOW();

-- Escort Buyers
INSERT INTO fazle_contact_roles (phone, name, role, confidence, source, priority, notes, platform)
VALUES
  ('01757622300', 'Escort Buyer 1', 'client_escort_buyer', 100, 'seed_rule', 90, 'Registered escort buyer', 'whatsapp'),
  ('01670535255', 'Escort Buyer 2', 'client_escort_buyer', 100, 'seed_rule', 90, 'Registered escort buyer', 'whatsapp'),
  ('01836743754', 'Escort Buyer 3', 'client_escort_buyer', 100, 'seed_rule', 90, 'Registered escort buyer', 'whatsapp')
ON CONFLICT (phone, platform) DO UPDATE SET
    role       = EXCLUDED.role,
    confidence = EXCLUDED.confidence,
    priority   = EXCLUDED.priority,
    notes      = EXCLUDED.notes,
    source     = EXCLUDED.source,
    updated_at = NOW();

-- Accountant
INSERT INTO fazle_contact_roles (phone, name, role, confidence, source, priority, notes, platform)
VALUES
  ('01844836824', 'Accountant', 'accountant', 100, 'seed_rule', 95, 'Company accountant', 'whatsapp')
ON CONFLICT (phone, platform) DO UPDATE SET
    role       = EXCLUDED.role,
    confidence = EXCLUDED.confidence,
    priority   = EXCLUDED.priority,
    notes      = EXCLUDED.notes,
    source     = EXCLUDED.source,
    updated_at = NOW();

-- Family
INSERT INTO fazle_contact_roles (phone, name, role, confidence, source, priority, notes, platform)
VALUES
  ('01848144841', 'Wife',     'family', 100, 'seed_rule', 100, 'Owner wife — no business workflow', 'whatsapp'),
  ('01772274173', 'Daughter', 'family', 100, 'seed_rule', 100, 'Owner daughter — no business workflow', 'whatsapp')
ON CONFLICT (phone, platform) DO UPDATE SET
    role       = EXCLUDED.role,
    confidence = EXCLUDED.confidence,
    priority   = EXCLUDED.priority,
    notes      = EXCLUDED.notes,
    source     = EXCLUDED.source,
    updated_at = NOW();

-- Vendor
INSERT INTO fazle_contact_roles (phone, name, role, confidence, source, priority, notes, platform)
VALUES
  ('01868591412', 'Vendor 1', 'vendor', 90, 'seed_rule', 70, 'Registered vendor', 'whatsapp')
ON CONFLICT (phone, platform) DO UPDATE SET
    role       = EXCLUDED.role,
    confidence = EXCLUDED.confidence,
    priority   = EXCLUDED.priority,
    notes      = EXCLUDED.notes,
    source     = EXCLUDED.source,
    updated_at = NOW();

-- VIP Clients (higher priority — overrides repeat_client)
INSERT INTO fazle_contact_roles (phone, name, role, confidence, source, priority, notes, platform)
VALUES
  ('01537443173', 'VIP Client 1', 'vip_client', 100, 'seed_rule', 92, 'VIP escort client', 'whatsapp'),
  ('01826532066', 'VIP Client 2', 'vip_client', 100, 'seed_rule', 92, 'VIP escort client', 'whatsapp')
ON CONFLICT (phone, platform) DO UPDATE SET
    role       = EXCLUDED.role,
    confidence = EXCLUDED.confidence,
    priority   = EXCLUDED.priority,
    notes      = EXCLUDED.notes,
    source     = EXCLUDED.source,
    updated_at = NOW();

-- Repeat Clients (lower priority than VIP — VIP rows already exist for overlap)
INSERT INTO fazle_contact_roles (phone, name, role, confidence, source, priority, notes, platform)
VALUES
  ('01995206164', 'Repeat Client 1', 'repeat_client', 85, 'seed_rule', 75, 'Repeat escort client', 'whatsapp'),
  ('01601509048', 'Repeat Client 2', 'repeat_client', 85, 'seed_rule', 75, 'Repeat escort client', 'whatsapp'),
  ('01760701010', 'Repeat Client 3', 'repeat_client', 85, 'seed_rule', 75, 'Repeat escort client', 'whatsapp'),
  ('01837747230', 'Repeat Client 4', 'repeat_client', 85, 'seed_rule', 75, 'Repeat escort client', 'whatsapp'),
  ('01819312640', 'Repeat Client 5', 'repeat_client', 85, 'seed_rule', 75, 'Repeat escort client', 'whatsapp'),
  ('01516115783', 'Repeat Client 6', 'repeat_client', 85, 'seed_rule', 75, 'Repeat escort client', 'whatsapp'),
  ('01735692001', 'Repeat Client 7', 'repeat_client', 85, 'seed_rule', 75, 'Repeat escort client', 'whatsapp'),
  ('01974008172', 'Repeat Client 8', 'repeat_client', 85, 'seed_rule', 75, 'Repeat escort client', 'whatsapp')
ON CONFLICT (phone, platform) DO UPDATE SET
    role       = EXCLUDED.role,
    confidence = EXCLUDED.confidence,
    priority   = EXCLUDED.priority,
    notes      = EXCLUDED.notes,
    source     = EXCLUDED.source,
    updated_at = NOW();

-- ── 4. Index on phone for fast identity lookups ───────────────────────────────
CREATE INDEX IF NOT EXISTS idx_fazle_contact_roles_phone
    ON fazle_contact_roles (phone);

CREATE INDEX IF NOT EXISTS idx_fazle_messages_identity
    ON fazle_whatsapp_messages (identity_role, received_at DESC)
    WHERE identity_role IS NOT NULL;

COMMIT;
