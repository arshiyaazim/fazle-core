"""
whatsapp_mcp.org_profile — Org Identity Customization

Singleton org_profiles (id=1) overrides .env for new installs.
- get_org_profile() → {org_name, admin_numbers[], accountant_phone, bridge_owner_map, domain_rules}
- upsert_org_profile(payload) → validates + writes + clears cache
- list_contacts() / import_contacts_csv() / set_contact_role()
- get_effective_admin_numbers() → org_profiles.admin_numbers || settings.ADMIN_NUMBERS

Used by fazle_identity_brain: if org_profiles has admin_numbers, those are the admins
for this install (not hardcoded Al-Rifa'i numbers). Falls back to .env when empty.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any, Optional

log = logging.getLogger("fazle.whatsapp_mcp.org")

# ── DB helpers ────────────────────────────────────────────────────────────────

async def get_org_profile() -> dict[str, Any]:
    """Fetch singleton org profile; returns defaults if table not yet migrated."""
    try:
        from app.database import fetch_one
        row = await fetch_one("SELECT * FROM org_profiles WHERE id=1 LIMIT 1")
        if not row:
            return _defaults()
        out = dict(row)
        # parse JSONB fields
        for k in ("bridge_owner_map", "domain_rules"):
            val = out.get(k)
            if isinstance(val, str):
                try: out[k] = json.loads(val)
                except Exception: out[k] = {}
        # admin_numbers as list
        raw = out.get("admin_numbers") or ""
        out["admin_numbers_list"] = [n.strip() for n in str(raw).split(",") if n.strip()]
        return out
    except Exception as e:
        log.debug("[org] get_org_profile fallback: %s", e)
        return _defaults()

def _defaults() -> dict[str, Any]:
    return {
        "id": 1,
        "org_name": "My Organisation",
        "company_name": "My Company",
        "admin_numbers": "",
        "admin_numbers_list": [],
        "accountant_phone": "",
        "bridge_owner_map": {},
        "domain_rules": {"recruitment": True, "escort": True, "payment": True, "attendance": True, "rag": True},
        "contact_csv_sha": "",
    }

async def upsert_org_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate + upsert org_profiles id=1. Returns saved row."""
    # Validate admin_numbers (comma-separated 880...)
    admin_numbers = str(payload.get("admin_numbers") or payload.get("adminNumbers") or "").strip()
    # basic normalize: strip spaces, ensure digits
    if admin_numbers:
        parts = [p.strip() for p in admin_numbers.split(",") if p.strip()]
        # allow 01 or 880
        for p in parts:
            digits = "".join(c for c in p if c.isdigit())
            if len(digits) < 10:
                raise ValueError(f"invalid admin number: {p}")
        admin_numbers = ",".join(parts)

    org_name = str(payload.get("org_name") or payload.get("orgName") or "My Organisation").strip()[:200]
    company_name = str(payload.get("company_name") or payload.get("companyName") or payload.get("company_name") or "My Company").strip()[:200]
    accountant_phone = str(payload.get("accountant_phone") or payload.get("accountantPhone") or "").strip()
    bridge_owner_map = payload.get("bridge_owner_map") or payload.get("bridgeOwnerMap") or {}
    domain_rules = payload.get("domain_rules") or payload.get("domainRules") or {"recruitment": True, "escort": True, "payment": True, "attendance": True, "rag": True}
    if isinstance(bridge_owner_map, str):
        try: bridge_owner_map = json.loads(bridge_owner_map)
        except Exception: bridge_owner_map = {}
    if isinstance(domain_rules, str):
        try: domain_rules = json.loads(domain_rules)
        except Exception: domain_rules = {}

    try:
        from app.database import execute, fetch_one
        await execute(
            """
            INSERT INTO org_profiles (id, org_name, company_name, admin_numbers, accountant_phone, bridge_owner_map, domain_rules)
            VALUES (1, $1, $2, $3, $4, $5::jsonb, $6::jsonb)
            ON CONFLICT (id) DO UPDATE SET
                org_name=EXCLUDED.org_name,
                company_name=EXCLUDED.company_name,
                admin_numbers=EXCLUDED.admin_numbers,
                accountant_phone=EXCLUDED.accountant_phone,
                bridge_owner_map=EXCLUDED.bridge_owner_map,
                domain_rules=EXCLUDED.domain_rules
            """,
            org_name, company_name, admin_numbers, accountant_phone,
            json.dumps(bridge_owner_map, ensure_ascii=False),
            json.dumps(domain_rules, ensure_ascii=False),
        )
        row = await fetch_one("SELECT * FROM org_profiles WHERE id=1")
        out = dict(row) if row else payload
        for k in ("bridge_owner_map","domain_rules"):
            if isinstance(out.get(k), str):
                try: out[k] = json.loads(out[k])
                except Exception: pass
        log.info("[org] upsert org_name=%s admins=%s", org_name, admin_numbers)
        return out
    except Exception as e:
        # Table not migrated yet → return payload as if saved (non-fatal)
        if "does not exist" in str(e).lower():
            log.warning("[org] org_profiles table not yet migrated: %s", e)
            return {"id":1, "org_name": org_name, "company_name": company_name, "admin_numbers": admin_numbers, "accountant_phone": accountant_phone, "bridge_owner_map": bridge_owner_map, "domain_rules": domain_rules}
        raise

async def get_effective_admin_numbers() -> list[str]:
    """Org profile wins; fallback to settings.ADMIN_NUMBERS."""
    try:
        prof = await get_org_profile()
        if prof.get("admin_numbers_list"):
            return prof["admin_numbers_list"]
    except Exception:
        pass
    try:
        from app.config import get_settings
        s = get_settings()
        return [n.strip() for n in (s.admin_numbers or "").split(",") if n.strip()]
    except Exception:
        return []

# ── Contacts import ───────────────────────────────────────────────────────────

async def import_contacts_csv(csv_text: str, source_org: str = "org_import") -> dict[str, Any]:
    """Import contacts from CSV text (phone,name,role). Upserts fazle_contacts."""
    reader = csv.DictReader(io.StringIO(csv_text))
    # Normalize header case
    rows = list(reader)
    if not rows:
        # try without header: phone,name
        reader2 = csv.reader(io.StringIO(csv_text))
        rows2 = []
        for line in reader2:
            if not line or not line[0].strip():
                continue
            rows2.append({"phone": line[0].strip(), "name": (line[1].strip() if len(line)>1 else ""), "role": (line[2].strip() if len(line)>2 else "unknown")})
        rows = rows2
        if not rows:
            raise ValueError("empty CSV")

    imported = 0
    errors = []
    for idx, r in enumerate(rows):
        # Support both header styles
        phone = str(r.get("phone") or r.get("Phone") or r.get("whatsapp_number") or r.get("number") or "").strip()
        name = str(r.get("name") or r.get("Name") or r.get("display_name") or "").strip()
        role = str(r.get("role") or r.get("Role") or "unknown").strip().lower() or "unknown"
        if not phone:
            errors.append(f"row {idx}: missing phone")
            continue
        # Normalize phone to 880
        try:
            from modules.phone_normalizer import normalize_phone as norm
            canon = norm(phone)
            phone_norm = canon if canon else phone
        except Exception:
            phone_norm = "".join(c for c in phone if c.isdigit())
            if phone_norm.startswith("0"):
                phone_norm = "880" + phone_norm[1:]
        try:
            from app.database import execute
            await execute(
                """
                INSERT INTO fazle_contacts (whatsapp_number, display_name, phone, platform, source_org)
                VALUES ($1,$2,$3,'whatsapp',$4)
                ON CONFLICT (whatsapp_number) DO UPDATE SET display_name=EXCLUDED.display_name, phone=EXCLUDED.phone, source_org=EXCLUDED.source_org
                """,
                phone_norm, name or phone_norm, phone_norm, source_org,
            )
            # Also upsert contact_roles for identity_brain
            try:
                await execute(
                    """
                    INSERT INTO fazle_contact_roles (phone, name, role, platform, source, priority)
                    VALUES ($1,$2,$3,'whatsapp','org_import', 60)
                    ON CONFLICT (phone) DO UPDATE SET name=EXCLUDED.name, role=EXCLUDED.role, source=EXCLUDED.source
                    """,
                    phone_norm, name or phone_norm, role,
                )
            except Exception:
                pass
            imported += 1
        except Exception as e:
            errors.append(f"row {idx} {phone}: {e}"[:200])

    return {"imported": imported, "errors": errors[:20], "source_org": source_org}
