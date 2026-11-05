#!/usr/bin/env python3
"""Start the ASGI lifespan in a process with no database configuration."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DATABASE_MODE"] = "disabled"
os.environ.pop("DATABASE_URL", None)
os.environ.setdefault("AUTO_REPLY_ENABLED", "false")
os.environ.setdefault("OUTBOUND_ENABLED", "false")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


def main() -> int:
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200, health.text
        assert health.json()["runtime_mode"] == "code_only"
        capabilities = client.get("/api/runtime/capabilities")
        assert capabilities.status_code == 200, capabilities.text
        payload = capabilities.json()
        assert payload["runtime_mode"] == "code_only"
        assert payload["capabilities"]["business_writes"] is False
        assert client.get("/").status_code == 200
    print("code-only smoke: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
