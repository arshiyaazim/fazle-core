"""
whatsapp_mcp.registry — Universal N-Bridge Registry

Loads bridge configs from (in priority):
  1. whatsapp_bridges DB table (when DB available)
  2. BRIDGE_REGISTRY_JSON env (JSON array) — for universal installs
  3. Legacy bridge1/2/3 env vars (backward compat)

Provides:
  - BridgeConfig dataclass (all fields needed by poller + sender)
  - BridgeRegistry with CRUD + health probe
  - get_registry() singleton
  - seed_from_legacy() — auto-seed DB from legacy env on first boot

No FastAPI dependency here — pure logic, testable.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from typing import Optional, List

log = logging.getLogger("fazle.whatsapp_mcp.registry")

# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class BridgeConfig:
    bridge_id: str                  # slug: bridge1, bridge2, wa-hr-01
    label: str = ""                 # HR, OPS, REC2
    base_url: str = ""              # http://localhost:8082
    messages_db_path: str = ""      # /home/.../messages.db
    whatsapp_db_path: str = ""      # /home/.../whatsapp.db
    phone_number: str = ""          # 8801XXXXXXXXX
    phone_number_jid: str = ""      # 8801…@s.whatsapp.net
    direction: str = "both"         # both|inbound|outbound
    enabled: bool = True
    priority: int = 100
    webhook_secret: str = ""
    extra_json: dict = field(default_factory=dict)
    # runtime health (not persisted)
    health_status: str = "unknown"  # ok|degraded|down|unknown
    last_probe_at: Optional[str] = None

    def to_dict(self, include_secret: bool = False) -> dict:
        d = asdict(self)
        if not include_secret:
            d.pop("webhook_secret", None)
        # keep extra_json as dict
        return d

    @property
    def is_inbound(self) -> bool:
        return self.direction in ("both", "inbound")

    @property
    def is_outbound(self) -> bool:
        return self.direction in ("both", "outbound")

    def validate(self) -> list[str]:
        errs = []
        if not self.bridge_id or not self.bridge_id.strip():
            errs.append("bridge_id required")
        if self.base_url and not (self.base_url.startswith("http://") or self.base_url.startswith("https://")):
            errs.append("base_url must be http(s)")
        if self.direction not in ("both","inbound","outbound"):
            errs.append("direction must be both|inbound|outbound")
        return errs

# ── Legacy env loader ─────────────────────────────────────────────────────────

def _load_legacy_configs() -> List[BridgeConfig]:
    """Build BridgeConfig list from legacy bridge1/2/3 env vars."""
    from app.config import get_settings
    try:
        s = get_settings()
    except Exception:
        # during early import before .env loaded
        return []
    out = []
    for idx, prefix in enumerate(("bridge1","bridge2","bridge3"), start=1):
        base_url = getattr(s, f"{prefix}_url", "") or ""
        # skip empty legacy bridge (not configured)
        if not base_url and idx > 2:
            # bridge3 often empty; skip silently
            messages_db = getattr(s, f"{prefix}_db_path", "")
            whatsapp_db = getattr(s, f"{prefix}_whatsapp_db_path", "")
            if not messages_db and not whatsapp_db:
                continue
        cfg = BridgeConfig(
            bridge_id=prefix,
            label=getattr(s, f"{prefix}_label", prefix) or prefix,
            base_url=base_url or f"http://localhost:{8080+idx}",
            messages_db_path=getattr(s, f"{prefix}_db_path", "") or "",
            whatsapp_db_path=getattr(s, f"{prefix}_whatsapp_db_path", "") or "",
            phone_number=getattr(s, f"{prefix}_number", "") or "",
            phone_number_jid=f"{getattr(s, f'{prefix}_number','')}@s.whatsapp.net" if getattr(s, f"{prefix}_number","") else "",
            direction="both",
            enabled=True,
            priority=idx*10,
        )
        # Only add if at least base_url or db path present
        if cfg.base_url or cfg.messages_db_path:
            out.append(cfg)
    return out

def _load_json_registry() -> Optional[List[BridgeConfig]]:
    """BRIDGE_REGISTRY_JSON env → List[BridgeConfig]. Returns None if not set."""
    raw = os.getenv("BRIDGE_REGISTRY_JSON") or ""
    raw = raw.strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            log.warning("[registry] BRIDGE_REGISTRY_JSON is not a list")
            return None
        cfgs = []
        for item in data:
            if not isinstance(item, dict):
                continue
            cfg = BridgeConfig(
                bridge_id=str(item.get("bridge_id") or item.get("id") or ""),
                label=str(item.get("label") or item.get("bridge_id") or ""),
                base_url=str(item.get("base_url") or item.get("url") or ""),
                messages_db_path=str(item.get("messages_db_path") or item.get("messages_db") or ""),
                whatsapp_db_path=str(item.get("whatsapp_db_path") or item.get("whatsapp_db") or ""),
                phone_number=str(item.get("phone_number") or item.get("phone") or ""),
                phone_number_jid=str(item.get("phone_number_jid") or ""),
                direction=str(item.get("direction") or "both"),
                enabled=bool(item.get("enabled", True)),
                priority=int(item.get("priority", 100)),
                webhook_secret=str(item.get("webhook_secret") or ""),
                extra_json=dict(item.get("extra_json") or item.get("extra") or {}),
            )
            if not cfg.phone_number_jid and cfg.phone_number:
                cfg.phone_number_jid = f"{cfg.phone_number}@s.whatsapp.net"
            if cfg.validate():
                log.warning("[registry] skip invalid JSON bridge %s: %s", cfg.bridge_id, cfg.validate())
                continue
            cfgs.append(cfg)
        return cfgs
    except json.JSONDecodeError as e:
        log.warning("[registry] BRIDGE_REGISTRY_JSON parse error: %s", e)
        return None

# ── Registry ──────────────────────────────────────────────────────────────────

class BridgeRegistry:
    """
    N-bridge registry — DB-backed with env fallback.

    Usage:
      registry = BridgeRegistry()
      await registry.load()  # try DB, fallback to env
      bridges = await registry.all_enabled()

    For startup seeding:
      await registry.seed_from_legacy_if_empty()
    """
    def __init__(self):
        self._bridges: List[BridgeConfig] = []
        self._loaded_from: str = "none"  # db|json_env|legacy_env|none
        self._loaded = False

    async def load(self, force_reload: bool = False) -> List[BridgeConfig]:
        if self._loaded and not force_reload:
            return self._bridges
        # 1) Try DB
        db_bridges = await self._load_from_db()
        if db_bridges is not None:
            self._bridges = db_bridges
            self._loaded_from = "db"
            self._loaded = True
            log.info("[registry] loaded %d bridges from DB", len(db_bridges))
            # If DB empty, fallback to env so first boot works before seeding
            if not db_bridges:
                env_fallback = _load_json_registry()
                if env_fallback is not None:
                    self._bridges = env_fallback
                    self._loaded_from = "json_env"
                else:
                    self._bridges = _load_legacy_configs()
                    self._loaded_from = "legacy_env"
                log.info("[registry] DB empty → fallback %s (%d bridges)", self._loaded_from, len(self._bridges))
            return self._bridges

        # 2) JSON env
        json_cfg = _load_json_registry()
        if json_cfg is not None:
            self._bridges = json_cfg
            self._loaded_from = "json_env"
            self._loaded = True
            log.info("[registry] loaded %d bridges from BRIDGE_REGISTRY_JSON", len(json_cfg))
            return self._bridges

        # 3) Legacy env
        self._bridges = _load_legacy_configs()
        self._loaded_from = "legacy_env"
        self._loaded = True
        log.info("[registry] loaded %d bridges from legacy env", len(self._bridges))
        return self._bridges

    async def _load_from_db(self) -> Optional[List[BridgeConfig]]:
        """Return list or None if DB not reachable. Empty list = reachable but no rows."""
        try:
            from app.database import fetch_all
            rows = await fetch_all(
                "SELECT bridge_id, label, base_url, messages_db_path, whatsapp_db_path, "
                "phone_number, phone_number_jid, direction, enabled, priority, webhook_secret, extra_json "
                "FROM whatsapp_bridges ORDER BY priority ASC, bridge_id ASC"
            )
            # fetch_all returns [] if table missing? It raises if table not exists.
            cfgs = []
            for r in rows:
                extra = r.get("extra_json") or {}
                if isinstance(extra, str):
                    try:
                        extra = json.loads(extra)
                    except Exception:
                        extra = {}
                cfg = BridgeConfig(
                    bridge_id=r["bridge_id"],
                    label=r.get("label") or "",
                    base_url=r.get("base_url") or "",
                    messages_db_path=r.get("messages_db_path") or "",
                    whatsapp_db_path=r.get("whatsapp_db_path") or "",
                    phone_number=r.get("phone_number") or "",
                    phone_number_jid=r.get("phone_number_jid") or "",
                    direction=r.get("direction") or "both",
                    enabled=bool(r.get("enabled", True)),
                    priority=int(r.get("priority") or 100),
                    webhook_secret=r.get("webhook_secret") or "",
                    extra_json=dict(extra) if isinstance(extra, dict) else {},
                )
                cfgs.append(cfg)
            return cfgs
        except Exception as e:
            # DB not ready / table not migrated yet
            log.debug("[registry] DB load skip: %s", e)
            return None

    # ── In-memory ops (no DB write) ──────────────────────────────────────────

    def get(self, bridge_id: str) -> Optional[BridgeConfig]:
        for b in self._bridges:
            if b.bridge_id == bridge_id:
                return b
        return None

    async def all(self, include_disabled: bool = False) -> List[BridgeConfig]:
        await self.load()
        if include_disabled:
            return list(self._bridges)
        return [b for b in self._bridges if b.enabled]

    async def all_enabled(self) -> List[BridgeConfig]:
        return await self.all(include_disabled=False)

    @property
    def loaded_from(self) -> str:
        return self._loaded_from

    # ── DB CRUD (when DB available) ─────────────────────────────────────────

    async def upsert(self, cfg: BridgeConfig) -> BridgeConfig:
        errs = cfg.validate()
        if errs:
            raise ValueError(f"invalid bridge config: {errs}")
        try:
            from app.database import execute
            # extra_json as jsonb
            await execute(
                """
                INSERT INTO whatsapp_bridges
                    (bridge_id, label, base_url, messages_db_path, whatsapp_db_path,
                     phone_number, phone_number_jid, direction, enabled, priority, webhook_secret, extra_json)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb)
                ON CONFLICT (bridge_id) DO UPDATE SET
                    label=EXCLUDED.label,
                    base_url=EXCLUDED.base_url,
                    messages_db_path=EXCLUDED.messages_db_path,
                    whatsapp_db_path=EXCLUDED.whatsapp_db_path,
                    phone_number=EXCLUDED.phone_number,
                    phone_number_jid=EXCLUDED.phone_number_jid,
                    direction=EXCLUDED.direction,
                    enabled=EXCLUDED.enabled,
                    priority=EXCLUDED.priority,
                    webhook_secret=EXCLUDED.webhook_secret,
                    extra_json=EXCLUDED.extra_json
                """,
                cfg.bridge_id, cfg.label, cfg.base_url, cfg.messages_db_path, cfg.whatsapp_db_path,
                cfg.phone_number, cfg.phone_number_jid or (f"{cfg.phone_number}@s.whatsapp.net" if cfg.phone_number else ""),
                cfg.direction, cfg.enabled, cfg.priority, cfg.webhook_secret, json.dumps(cfg.extra_json),
            )
            # update in-memory
            existing = self.get(cfg.bridge_id)
            if existing:
                idx = self._bridges.index(existing)
                self._bridges[idx] = cfg
            else:
                self._bridges.append(cfg)
                self._bridges.sort(key=lambda b: b.priority)
            log.info("[registry] upsert bridge_id=%s", cfg.bridge_id)
            return cfg
        except Exception as e:
            log.warning("[registry] upsert DB failed (%s), keeping in-memory: %s", cfg.bridge_id, e)
            # in-memory fallback
            existing = self.get(cfg.bridge_id)
            if existing:
                idx = self._bridges.index(existing)
                self._bridges[idx] = cfg
            else:
                self._bridges.append(cfg)
            return cfg

    async def delete(self, bridge_id: str) -> bool:
        try:
            from app.database import execute
            await execute("DELETE FROM whatsapp_bridges WHERE bridge_id=$1", bridge_id)
        except Exception as e:
            log.debug("[registry] delete DB skip: %s", e)
        before = len(self._bridges)
        self._bridges = [b for b in self._bridges if b.bridge_id != bridge_id]
        return len(self._bridges) < before

    async def seed_from_legacy_if_empty(self) -> int:
        """If DB table empty, seed from legacy env configs. Returns seeded count."""
        try:
            from app.database import fetch_val
            cnt = await fetch_val("SELECT COUNT(*) FROM whatsapp_bridges")
            if cnt and int(cnt) > 0:
                return 0
        except Exception:
            return 0  # table not ready
        legacy = _load_legacy_configs()
        if not legacy:
            # try JSON env
            json_cfg = _load_json_registry()
            legacy = json_cfg or []
        seeded = 0
        for cfg in legacy:
            try:
                await self.upsert(cfg)
                seeded += 1
            except Exception as e:
                log.warning("[registry] seed failed %s: %s", cfg.bridge_id, e)
        if seeded:
            log.info("[registry] seeded %d bridges from legacy env", seeded)
        return seeded

    async def reload(self) -> List[BridgeConfig]:
        return await self.load(force_reload=True)

# ── Singleton ─────────────────────────────────────────────────────────────────

_registry: Optional[BridgeRegistry] = None

async def get_registry() -> BridgeRegistry:
    global _registry
    if _registry is None:
        _registry = BridgeRegistry()
        await _registry.load()
    return _registry

def get_registry_sync() -> BridgeRegistry:
    """Sync accessor for non-async call sites (uses cached loaded bridges)."""
    global _registry
    if _registry is None:
        _registry = BridgeRegistry()
        # load from env synchronously (no DB)
        json_cfg = _load_json_registry()
        if json_cfg is not None:
            _registry._bridges = json_cfg
            _registry._loaded_from = "json_env"
        else:
            _registry._bridges = _load_legacy_configs()
            _registry._loaded_from = "legacy_env"
        _registry._loaded = False
    return _registry
