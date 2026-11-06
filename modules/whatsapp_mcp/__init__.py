"""
whatsapp_mcp — Universal WhatsApp Bridge Connector + MCP Server

Phase 1 of Universal Installer (098):
  - registry.py  → N-bridge registry (DB + .env fallback)
  - identifier.py→ canonical WhatsApp identifiers (JID/LID/PN/phone/group/call/media)
  - mcp_server.py→ MCP tool surface (send, get_messages, get_contact, call_log, groups)
  - sync.py      → history sync (Phase 2)

Usage:
  from modules.whatsapp_mcp.registry import get_registry
  registry = await get_registry()
  bridges = await registry.all_enabled()

  from modules.whatsapp_mcp.identifier import parse_identifier
  ident = parse_identifier(row, bridge_id="bridge1")

Public re-exports:
"""
from .registry import BridgeConfig, BridgeRegistry, get_registry  # noqa: F401
from .identifier import WhatsAppIdentifier, parse_identifier  # noqa: F401
