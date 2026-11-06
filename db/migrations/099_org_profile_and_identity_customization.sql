-- 099 — Org Profile + Identity Customization (Universal Installer Phase 3)
-- Lets a new organisation override admin numbers, contacts, and domain routing
-- without hardcoding .env ADMIN_NUMBERS.

CREATE TABLE IF NOT EXISTS org_profiles (
    id              BIGSERIAL PRIMARY KEY,
    org_name        TEXT NOT NULL DEFAULT 'My Organisation',
    company_name    TEXT NOT NULL DEFAULT 'My Company',
    admin_numbers   TEXT NOT NULL DEFAULT '',          -- comma-separated 8801...
    accountant_phone TEXT NOT NULL DEFAULT '',
    bridge_owner_map JSONB NOT NULL DEFAULT '{}'::jsonb, -- {bridge_id: phone_880}
    domain_rules    JSONB NOT NULL DEFAULT '{}'::jsonb, -- {recruitment:true, escort:true, payment:true, attendance:true, rag:true}
    contact_csv_sha TEXT NOT NULL DEFAULT '',          -- sha of last imported contacts CSV
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- singleton: only one row per install (enforced in app, not DB)
    CONSTRAINT org_profiles_singleton CHECK (id = 1)
);
CREATE INDEX IF NOT EXISTS idx_org_profiles_updated ON org_profiles (updated_at DESC);

CREATE OR REPLACE FUNCTION _touch_org_profiles_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_org_profiles_touch ON org_profiles;
CREATE TRIGGER trg_org_profiles_touch BEFORE UPDATE ON org_profiles
    FOR EACH ROW EXECUTE FUNCTION _touch_org_profiles_updated_at();

-- Ensure singleton row exists (id=1) — defaults mirror .env.example
INSERT INTO org_profiles (id, org_name, company_name, admin_numbers, domain_rules)
VALUES (1, 'My Organisation', 'My Company', '', '{"recruitment": true, "escort": true, "payment": true, "attendance": true, "rag": true}'::jsonb)
ON CONFLICT (id) DO NOTHING;

-- Extend contact_roles with org-specific source tracking (if not exists)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fazle_contacts' AND column_name='source_org') THEN
        ALTER TABLE fazle_contacts ADD COLUMN source_org TEXT NOT NULL DEFAULT 'seed';
    END IF;
END $$;

COMMENT ON TABLE org_profiles IS 'Singleton org identity — customizes fazle_identity_brain without touching .env (migration 099)';
