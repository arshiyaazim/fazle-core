#!/usr/bin/env python3
"""
examples/whatsapp_mcp_send.py — Auto Python coding এ WhatsApp মেসেজ পাঠানো

Requirement: এক লাইনে যে কোনো ব্রিজ দিয়ে মেসেজ পাঠানো, JID/LID/PN auto-resolve,
media + group + call trace সহ।

Usage:
  # 1) MCP API via HTTP (needs INTERNAL_API_KEY):
  python examples/whatsapp_mcp_send.py --to 01710000001 --text "হ্যালো, টেস্ট" --bridge wa-hr

  # 2) Direct Python (inside fazle-core venv, needs BRIDGE_REGISTRY_JSON or legacy env):
  python examples/whatsapp_mcp_send.py --to 8801710000001@s.whatsapp.net --text "hello"

  # 3) Media:
  python examples/whatsapp_mcp_send.py --to 01710000001 --text "ছবি দেখুন" --media ./photo.jpg

  # 4) Group:
  python examples/whatsapp_mcp_send.py --to 120363...@g.us --text "গ্রুপে হ্যালো"

Env:
  INTERNAL_API_KEY — for HTTP mode
  BRIDGE_REGISTRY_JSON or BRIDGE1_URL etc. — for direct mode
  FAZLE_CORE_URL (default http://127.0.0.1:8200)

This script demonstrates what the MCP tool `whatsapp.send_message` does under the hood.
"""
from __future__ import annotations
import argparse
import asyncio
import os
import sys

FAZLE_URL = os.getenv("FAZLE_CORE_URL", "http://127.0.0.1:8200")
API_KEY = os.getenv("INTERNAL_API_KEY", "")

async def send_via_http(to: str, text: str, bridge_id: str = "", media_path: str = "") -> dict:
    import httpx
    payload = {"to": to, "message": text}
    if bridge_id: payload["bridge_id"] = bridge_id
    if media_path: payload["media_path"] = media_path
    headers = {"X-Internal-Key": API_KEY}
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.post(f"{FAZLE_URL}/mcp/call", headers=headers, json={"name": "whatsapp.send_message", "arguments": payload})
        r.raise_for_status()
        return r.json()

async def send_direct(to: str, text: str, bridge_id: str = "", media_path: str = "") -> dict:
    from modules.whatsapp_mcp.mcp_server import call_tool
    return await call_tool("whatsapp.send_message", {"to": to, "message": text, "bridge_id": bridge_id, "media_path": media_path})

async def demo_identifiers():
    """Show how every field is extracted."""
    from modules.whatsapp_mcp.identifier import parse_identifier, build_jid
    samples = [
        {"chat_jid": "8801710000001@s.whatsapp.net", "sender": "8801710000001:12@s.whatsapp.net", "id": "3EB0ABC", "content": "হ্যালো", "media_type": "text", "timestamp": "2026-11-06T10:00:00+06:00"},
        {"chat_jid": "120363040000000000@g.us", "sender": "8801710000001@s.whatsapp.net", "id": "GRP123", "content": "গ্রুপ মেসেজ", "media_type": "text"},
        {"chat_jid": "8801710000001@s.whatsapp.net", "id": "MED123", "content": "[media:image]", "media_type": "image", "filename": "photo.jpg", "url": "http://..."},
        {"chat_jid": "8801710000001@s.whatsapp.net", "id": "CALL123", "content": "missed call", "media_type": "call"},
    ]
    for row in samples:
        ident = parse_identifier(row, bridge_id="bridge1")
        print(f"  → wa_jid={ident.wa_jid} | wa_lid={ident.wa_lid} | wa_pn={ident.wa_pn} | phone={ident.phone_880}/{ident.phone_01} | group={ident.group_jid} | media={ident.media_type} | call={ident.call_status} | jid={ident.target_jid}")
    print(f"  build_jid('01710000001') = {build_jid('01710000001')}")
    print(f"  build_jid('120363...','group') = {build_jid('120363040000000000', is_group=True)}")

async def main():
    p = argparse.ArgumentParser(description="WhatsApp MCP send demo")
    p.add_argument("--to", help="Recipient phone/JID")
    p.add_argument("--text", default="", help="Message text")
    p.add_argument("--bridge", default="", dest="bridge_id", help="Bridge id (optional, auto picks priority)")
    p.add_argument("--media", default="", dest="media_path", help="Media file path")
    p.add_argument("--demo-identifiers", action="store_true", help="Show identifier extraction demo and exit")
    args = p.parse_args()

    if args.demo_identifiers or not args.to:
        print("=== Identifier extraction demo (JID/LID/PN/phone/group/media/call) ===")
        await demo_identifiers()
        if not args.to:
            print("\nGive --to to actually send. Example: --to 01710000001 --text 'হ্যালো'")
            return

    if args.to:
        print(f"Sending to={args.to!r} via bridge={args.bridge_id or '(auto)'} text={args.text[:60]!r}")
        if API_KEY and FAZLE_URL:
            print(f"  → via HTTP {FAZLE_URL}/mcp/call")
            try:
                res = await send_via_http(args.to, args.text, args.bridge_id, args.media_path)
                print("Result:", res)
                return
            except Exception as e:
                print(f"HTTP failed ({e}), trying direct mode…")
        # fallback direct
        res = await send_direct(args.to, args.text, args.bridge_id, args.media_path)
        print("Direct result:", res)

if __name__ == "__main__":
    asyncio.run(main())
