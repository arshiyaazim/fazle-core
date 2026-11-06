"""
whatsapp_mcp.identifier — Canonical WhatsApp Identifiers

Every inbound/outbound message must be self-describing:

  wa_jid       → canonical WhatsApp JID (8801…@s.whatsapp.net or …@g.us)
  wa_lid       → linked device LID (may differ from JID; used for LID→PN map)
  wa_pn        → phone number as stored by bridge (PN — may be LID-mapped)
  phone_880    → normalized 8801XXXXXXXXX
  phone_01     → normalized 01XXXXXXXXX
  group_jid    → if @g.us, group JID else None
  wa_message_id→ bridge message id (e.g. 3EB0… or mock-00001)
  media_type   → text|image|video|audio|document|sticker|call|missed_call|location|contact|unknown
  call_status  → for call events: call|missed_call|rejected (else None)
  direction    → inbound|outbound
  bridge_id    → which bridge observed it

This module is pure (no DB, no I/O) — easy to test.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional

# ── Helpers ───────────────────────────────────────────────────────────────────

_JID_RE = re.compile(r"^(\+?8801\d{9}|01\d{9}|\d+)@([sg]\.whatsapp\.net|g\.us|newsletter|broadcast)$", re.I)

def _norm_880(raw: str) -> str:
    """Best-effort 880 normalize without DB; full validation via phone_normalizer elsewhere."""
    if not raw:
        return ""
    if raw.startswith("unresolved:"):
        return raw
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("880") and len(digits) >= 13:
        return digits[:13]  # 8801XXXXXXXXX
    if digits.startswith("01") and len(digits) == 11:
        return "880" + digits[1:]
    if len(digits) == 10 and digits.startswith("1"):
        return "880" + digits
    return digits

def _norm_01(n880: str) -> str:
    if n880.startswith("880") and len(n880) == 13:
        return "0" + n880[3:]
    return n880

def _detect_media_type(content: str | None, raw: dict | None = None) -> str:
    """Heuristic + raw_json hint."""
    raw = raw or {}
    # explicit from bridge raw
    t = (raw.get("media_type") or raw.get("type") or "").lower()
    if t in ("image","video","audio","document","sticker","call","missed_call","location","contact","ptt","voice"):
        if t == "ptt":
            return "audio"
        return t
    # call signals in content
    c = (content or "").lower()
    if "missed call" in c or "missed_call" in c:
        return "missed_call"
    if c.strip().startswith("call") and len(c) < 30:
        return "call"
    # media placeholders from bridge
    if not c or c.strip() in ("", "[media]", "[image]", "[video]", "[audio]"):
        # if we have media_path, it's media
        if raw.get("media_path") or raw.get("media_url"):
            return "image"  # default; poller refines via extension
        return "text" if c else "unknown"
    return "text"

def _jid_from_phone(phone_880: str, group_jid: str | None = None) -> str:
    if group_jid and "@g.us" in group_jid:
        return group_jid
    if phone_880 and phone_880.startswith("880"):
        return f"{phone_880}@s.whatsapp.net"
    return phone_880 or ""

# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class WhatsAppIdentifier:
    # canonical normalized phones
    phone_880: str = ""          # 8801XXXXXXXXX
    phone_01: str = ""           # 01XXXXXXXXX
    # WhatsApp protocol ids
    wa_jid: str = ""             # 8801…@s.whatsapp.net or …@g.us
    wa_lid: str = ""             # LID (may equal JID or be different)
    wa_pn: str = ""              # PN as stored by bridge (often == JID)
    group_jid: Optional[str] = None
    is_group: bool = False
    # message identity
    wa_message_id: str = ""      # bridge message id
    # content
    media_type: str = "text"     # see _detect_media_type
    media_path: Optional[str] = None
    call_status: Optional[str] = None  # call|missed_call|rejected
    direction: str = "inbound"   # inbound|outbound
    bridge_id: str = ""          # which bridge
    timestamp: Optional[datetime] = None
    push_name: Optional[str] = None     # sender push name if available
    full_name: Optional[str] = None     # resolved display name
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.timestamp:
            d["timestamp"] = self.timestamp.isoformat()
        return d

    @property
    def target_jid(self) -> str:
        """JID to use for sending a reply (group → group_jid, DM → wa_jid)."""
        if self.is_group and self.group_jid:
            return self.group_jid
        return self.wa_jid or _jid_from_phone(self.phone_880, self.group_jid)

    @property
    def is_media(self) -> bool:
        return self.media_type in ("image","video","audio","document","sticker")

    @property
    def is_call(self) -> bool:
        return self.media_type in ("call","missed_call") or self.call_status is not None

# ── Parser ────────────────────────────────────────────────────────────────────

def parse_identifier(
    row: dict,
    *,
    bridge_id: str = "",
    lid_map: dict | None = None,
) -> WhatsAppIdentifier:
    """
    Build canonical identifier from a bridge SQLite row or API payload.

    Accepts snake/kebab/camel keys:
      id/messageId/wa_message_id, chat_jid/chatJid/jid, sender_jid/sender_lid,
      timestamp/ts, content/text/message, media_type/type, is_from_me/direction
    """
    raw = dict(row or {})
    # message id
    wa_message_id = str(raw.get("wa_message_id") or raw.get("messageId") or raw.get("id") or raw.get("message_id") or "")
    # jid / group
    wa_jid = str(raw.get("wa_jid") or raw.get("chat_jid") or raw.get("chatJid") or raw.get("jid") or raw.get("sender_jid") or "")
    wa_lid = str(raw.get("wa_lid") or raw.get("sender_lid") or raw.get("lid") or "")
    wa_pn = str(raw.get("wa_pn") or raw.get("pn") or raw.get("phone") or "")
    group_jid = raw.get("group_jid") or raw.get("groupJid")
    # phone normalization: prefer explicit phone, else derive from JID
    phone_raw = raw.get("phone_880") or raw.get("phone") or wa_jid.split("@")[0] if wa_jid else ""
    phone_880 = _norm_880(str(phone_raw or ""))
    phone_01 = _norm_01(phone_880)

    # LID→PN resolve if map provided (bridge whatsapp.db lid_map)
    if lid_map and wa_lid and not phone_880:
        mapped = lid_map.get(wa_lid) or lid_map.get(wa_jid)
        if mapped:
            wa_pn = str(mapped.get("phone") or mapped.get("pn") or "")
            phone_880 = _norm_880(wa_pn)
            phone_01 = _norm_01(phone_880)

    # group detection
    is_group = bool(group_jid) or ("@g.us" in wa_jid) or ("@g.us" in str(group_jid or ""))
    if not group_jid and "@g.us" in wa_jid:
        group_jid = wa_jid
        # for group, wa_jid should stay as group JID, phone is participant if available
        # we keep as is; caller can set participant JID separately

    media_type = (raw.get("media_type") or raw.get("type") or _detect_media_type(raw.get("content") or raw.get("text") or raw.get("message"), raw)).lower()
    media_path = raw.get("media_path") or raw.get("mediaPath")
    call_status = raw.get("call_status") or raw.get("callStatus")
    if media_type == "missed_call":
        call_status = "missed_call"

    direction = raw.get("direction") or ("outbound" if raw.get("is_from_me") in (1, True, "1", "true") else "inbound")
    ts = raw.get("timestamp") or raw.get("ts") or raw.get("created_at")
    timestamp = None
    if isinstance(ts, datetime):
        timestamp = ts
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
    elif isinstance(ts, str) and ts:
        try:
            # SQLite datetime string
            timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
        except Exception:
            timestamp = None

    return WhatsAppIdentifier(
        phone_880=phone_880,
        phone_01=phone_01,
        wa_jid=wa_jid or _jid_from_phone(phone_880, group_jid),
        wa_lid=wa_lid,
        wa_pn=wa_pn or wa_jid,
        group_jid=group_jid,
        is_group=is_group,
        wa_message_id=wa_message_id,
        media_type=media_type,
        media_path=str(media_path) if media_path else None,
        call_status=call_status,
        direction=direction if direction in ("inbound","outbound") else "inbound",
        bridge_id=bridge_id or str(raw.get("bridge_id") or raw.get("source_bridge") or ""),
        timestamp=timestamp,
        push_name=raw.get("push_name") or raw.get("pushName"),
        full_name=raw.get("full_name") or raw.get("display_name"),
        raw=raw,
    )

# ── Auto-JID builder (for Python send) ──────────────────────────────────────

def build_jid(phone_or_jid: str, *, is_group: bool = False) -> str:
    """
    Build a WhatsApp JID from loose input:
      "01710000001" → "8801710000001@s.whatsapp.net"
      "8801710000001" → "8801710000001@s.whatsapp.net"
      "8801710000001@s.whatsapp.net" → as-is
      "1203630…@g.us" → as-is (group)
    """
    s = (phone_or_jid or "").strip()
    if not s:
        return ""
    if "@" in s:
        return s  # already JID
    # group heuristic: long digits (>13) or caller says is_group
    if is_group:
        return f"{s}@g.us" if "@" not in s else s
    n880 = _norm_880(s)
    if n880.startswith("880"):
        return f"{n880}@s.whatsapp.net"
    # fallback: treat as JID local part
    return f"{s}@s.whatsapp.net"

def is_valid_jid(jid: str) -> bool:
    if not jid or "@" not in jid:
        return False
    return jid.endswith("@s.whatsapp.net") or jid.endswith("@g.us") or jid.endswith("@newsletter") or jid.endswith("@broadcast")
