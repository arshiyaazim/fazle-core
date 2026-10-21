#!/usr/bin/env python3
"""
Capture / compare a manifest of hashes for the files that HARD CONSTRAINTS
protect from functional change.

Protected areas:
  * Bridge poller + bridge SQLite path handling  (HARD CONSTRAINT #1)
  * Canonical ledger write path                   (HARD CONSTRAINT #2)
  * Duplicate-prevention layers                   (HARD CONSTRAINT #2)
  * OCR pipeline + identity resolver             (HARD CONSTRAINT #2)

Usage:
    python tools/prefix_manifest.py capture <outfile.json>
    python tools/prefix_manifest.py compare <outfile.json>

`capture` writes a JSON manifest of {path: sha256}.
`compare` re-hashes the same paths and reports per-path CHANGED / SAME.

Paths are recorded relative to the repo root so the manifest is portable.
A path that does not exist at compare time is reported as MISSING.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── Protected path groups ───────────────────────────────────────────────────
GROUPS: dict[str, list[str]] = {
    # HARD CONSTRAINT #1 — bridge storage / polling / media download logic.
    "bridge": [
        "modules/bridge_poller/__init__.py",
        "modules/bridge_poller",
        "app/config.py",
        "shared/media_text.py",
        "shared/bridge_orchestrator.py",
    ],
    # HARD CONSTRAINT #2 — canonical ledger write path.
    "canonical_ledger": [
        "modules/fazle_payroll_engine/accounting.py",
        "modules/fazle_payroll_engine/employee.py",
        "modules/fazle_payroll_engine/models.py",
        "modules/fazle_payroll_engine/payment_event.py",
        "modules/fazle_payroll_engine/normalizer.py",
        "modules/fazle_payroll_engine/normalization.py",
    ],
    # HARD CONSTRAINT #2 — OCR pipeline + identity resolver rules.
    "ocr_and_identity": [
        "modules/ocr_processor",
        "modules/identity_resolver.py",
        "modules/identity_brain",
        "modules/image_hash",
    ],
}

# Files whose *content* must be byte-identical (path may change).
BYTE_IDENTICAL = [
    "modules/bridge_poller/__init__.py",
    "modules/fazle_payroll_engine/accounting.py",
    "modules/fazle_payroll_engine/employee.py",
    "modules/fazle_payroll_engine/models.py",
    "modules/fazle_payroll_engine/payment_event.py",
    "modules/fazle_payroll_engine/normalizer.py",
    "modules/identity_resolver.py",
    "modules/ocr_processor/__init__.py",
    "modules/image_hash/__init__.py",
]


def _hash_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_tree(p: Path) -> str:
    """Hash a directory: sorted (relpath, filehash) pairs."""
    h = hashlib.sha256()
    for f in sorted(x for x in p.rglob("*") if x.is_file()):
        if "__pycache__" in f.parts:
            continue
        h.update(str(f.relative_to(p)).encode())
        h.update(_hash_file(f).encode())
    return h.hexdigest()


def collect() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for group, paths in GROUPS.items():
        for rel in paths:
            p = ROOT / rel
            key = f"{group}::{rel}"
            if p.is_file():
                out[key] = {"kind": "file", "sha256": _hash_file(p)}
            elif p.is_dir():
                out[key] = {"kind": "dir", "sha256": _hash_tree(p)}
            else:
                out[key] = {"kind": "missing", "sha256": ""}
    return out


def capture(dest: Path) -> int:
    data = collect()
    dest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"captured {len(data)} protected paths -> {dest}")
    return 0


def compare(src: Path) -> int:
    before = json.loads(src.read_text(encoding="utf-8"))
    after = collect()
    changed, same, missing = [], [], []
    for key, b in sorted(before.items()):
        a = after.get(key, {"kind": "missing", "sha256": ""})
        if a["kind"] == "missing":
            missing.append(key)
        elif a["sha256"] == b["sha256"]:
            same.append(key)
        else:
            changed.append(key)
    print(f"protected paths: {len(before)}")
    print(f"  SAME     : {len(same)}")
    print(f"  CHANGED  : {len(changed)}")
    print(f"  MISSING  : {len(missing)}")
    for k in changed:
        print(f"  [CHANGED] {k}")
    for k in missing:
        print(f"  [MISSING] {k}")
    return 1 if (changed or missing) else 0


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    cmd, target = sys.argv[1], Path(sys.argv[2])
    if cmd == "capture":
        return capture(target)
    if cmd == "compare":
        return compare(target)
    print(f"unknown command {cmd!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
