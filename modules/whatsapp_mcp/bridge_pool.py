"""
whatsapp_mcp.bridge_pool — N-Bridge client pool

Wraps app.bridge.BridgeClient for dynamic N bridges.
Keeps one BridgeClient per bridge_id, with per-bridge circuit breaker.

Provides:
  - BridgeClientPool (singleton)
  - send_strict(bridge_id, jid, text, media_path?, media_type?) → result
  - send_via_any(jid, text) → failover over priority order
  - get_client(bridge_id) → BridgeClient
"""
from __future__ import annotations

import logging
import mimetypes
import os
from typing import Optional, Dict

log = logging.getLogger("fazle.whatsapp_mcp.pool")

# Reuse app.bridge.BridgeClient (has breaker + media_breaker)
try:
    from app.bridge import BridgeClient
except Exception:  # pragma: no cover
    BridgeClient = None  # type: ignore

class BridgeClientPool:
    def __init__(self):
        self._clients: Dict[str, object] = {}
        self._configs: Dict[str, object] = {}

    def _get_or_create(self, bridge_id: str) -> Optional[object]:
        if BridgeClient is None:
            return None
        if bridge_id in self._clients:
            return self._clients[bridge_id]
        # lazy load registry
        try:
            from .registry import get_registry_sync
            reg = get_registry_sync()
            cfg = reg.get(bridge_id)
            if not cfg:
                log.warning("[pool] bridge_id %s not in registry", bridge_id)
                return None
            client = BridgeClient(cfg.base_url, cfg.label or cfg.bridge_id)
            self._clients[bridge_id] = client
            self._configs[bridge_id] = cfg
            return client
        except Exception as e:
            log.warning("[pool] get_or_create %s failed: %s", bridge_id, e)
            return None

    async def send_strict(self, bridge_id: str, jid: str, text: str, media_path: Optional[str] = None, media_type: Optional[str] = None, authorization=None) -> dict:
        client = self._get_or_create(bridge_id)
        if not client:
            raise RuntimeError(f"bridge {bridge_id} client not available")
        # media send: if media_path, try /api/send with media
        if media_path:
            # detect mime
            mime, _ = mimetypes.guess_type(media_path)
            # bridge API expects recipient + message + optional media
            # fall back to text send if bridge doesn't support media endpoint
            try:
                # Try media endpoint first if exists
                if hasattr(client, "_client"):
                    # httpx client on BridgeClient
                    r = await client._client.post(
                        f"{client.base_url}/api/send",
                        json={"recipient": jid, "message": text or "", "media_path": media_path, "media_type": media_type or mime or "image"},
                        timeout=float(os.getenv("OUTBOUND_BRIDGE_TIMEOUT_S", "10")),
                    )
                    if r.status_code == 200:
                        return {"success": True, "via": "media", "bridge_id": bridge_id, "jid": jid}
            except Exception as e:
                log.debug("[pool] media send fallback: %s", e)
            # fallback text
        # text send
        await client.send_strict(jid, text, authorization=authorization)
        return {"success": True, "bridge_id": bridge_id, "jid": jid}

    async def send_via_any(self, jid: str, text: str, media_path: Optional[str] = None, authorization=None) -> dict:
        """Failover send: try enabled outbound bridges in priority order."""
        from .registry import get_registry
        reg = await get_registry()
        candidates = [b for b in await reg.all_enabled() if b.is_outbound]
        # sort by priority (already sorted, but ensure)
        candidates.sort(key=lambda b: b.priority)
        last_err = None
        for cfg in candidates:
            try:
                res = await self.send_strict(cfg.bridge_id, jid, text, media_path=media_path, authorization=authorization)
                if res.get("success"):
                    return res
            except Exception as e:
                last_err = e
                log.warning("[pool] send_via_any bridge %s failed: %s", cfg.bridge_id, e)
                continue
        raise RuntimeError(f"all bridges failed: {last_err}")

    def get_client(self, bridge_id: str):
        return self._get_or_create(bridge_id)

    async def close_all(self):
        for c in self._clients.values():
            try: await c.close()
            except Exception: pass
        self._clients.clear()

_pool: Optional[BridgeClientPool] = None

def get_pool() -> BridgeClientPool:
    global _pool
    if _pool is None:
        _pool = BridgeClientPool()
    return _pool
