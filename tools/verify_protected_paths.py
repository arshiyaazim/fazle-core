#!/usr/bin/env python3
"""
Prove that the HARD-CONSTRAINT protected areas are functionally unchanged.

For each protected file this compares the PRE-change content (taken from
git) with the CURRENT content, after applying the ONLY permitted
substitution: the 7 table names and the dependent DB object names.

If a protected file differs by anything else, the refactor broke a
constraint and this tool fails.

Protected areas
  * bridge poller + bridge SQLite path handling   (HARD CONSTRAINT #1)
  * canonical ledger write path                    (HARD CONSTRAINT #2)
  * 4-layer duplicate prevention                   (HARD CONSTRAINT #2)
  * OCR pipeline + identity resolver              (HARD CONSTRAINT #2)

Usage:
    python tools/verify_protected_paths.py [--base <git-ref>]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from prefix_unification_map import (  # noqa: E402
    IMPORT_PATH_MAP,
    MODULE_PATH_MAP,
    TABLE_MAP,
    rename_db_object,
)

# (pre-change path, post-change path)
PROTECTED: list[tuple[str, str]] = [
    # HARD CONSTRAINT #1 — bridge storage / polling / media download logic.
    ("modules/bridge_poller/__init__.py", "modules/fazle_bridge_poller/__init__.py"),
    ("shared/media_text.py", "shared/media_text.py"),
    ("shared/bridge_orchestrator.py", "shared/bridge_orchestrator.py"),
    # HARD CONSTRAINT #2 — canonical ledger write path.
    ("modules/fazle_payroll_engine/accounting.py", "modules/fazle_payroll_engine/accounting.py"),
    ("modules/fazle_payroll_engine/employee.py", "modules/fazle_payroll_engine/employee.py"),
    ("modules/fazle_payroll_engine/models.py", "modules/fazle_payroll_engine/models.py"),
    ("modules/fazle_payroll_engine/payment_event.py", "modules/fazle_payroll_engine/payment_event.py"),
    ("modules/fazle_payroll_engine/normalizer.py", "modules/fazle_payroll_engine/normalizer.py"),
    # HARD CONSTRAINT #2 — OCR pipeline + identity resolver.
    ("modules/ocr_processor/__init__.py", "modules/ocr_processor/__init__.py"),
    ("modules/identity_resolver.py", "modules/fazle_identity_resolver.py"),
    ("modules/image_hash/__init__.py", "modules/fazle_image_hash/__init__.py"),
    ("modules/identity_brain/__init__.py", "modules/fazle_identity_brain/__init__.py"),
    ("modules/identity_brain/claim_verification.py", "modules/fazle_identity_brain/claim_verification.py"),
    # Duplicate-prevention layers.
    ("modules/fazle_payroll_engine/validation.py", "modules/fazle_payroll_engine/validation.py"),
    ("shared/queue.py", "shared/queue.py"),
]


def git_show(ref: str, path: str) -> str | None:
    r = subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    if r.returncode != 0:
        return None
    return r.stdout


def build_substitutions(objects: dict) -> list[tuple[str, str]]:
    subs: list[tuple[str, str]] = []
    for old, new in TABLE_MAP.items():
        subs.append((old, new))
    # Module path renames (dotted + slash forms) are also permitted.
    for old, new in IMPORT_PATH_MAP.items():
        subs.append((old, new))
    for old, new in MODULE_PATH_MAP.items():
        subs.append((old, new))
    for key in ("indexes", "constraints", "sequences", "triggers"):
        for row in objects.get(key, []):
            name = (row.get("index_name") or row.get("constraint_name")
                    or row.get("sequence_name") or row.get("trigger_name"))
            if not name:
                continue
            new = rename_db_object(name)
            if new != name:
                subs.append((name, new))
    for t in objects.get("triggers", []):
        fn = t.get("function_name") or ""
        if fn:
            new = rename_db_object(fn)
            if new != fn:
                subs.append((fn, new))
    # Longest first so the longest token is substituted first.
    subs.sort(key=lambda kv: -len(kv[0]))
    return subs


def apply_subs(text: str, subs: list[tuple[str, str]]) -> str:
    for old, new in subs:
        text = re.sub(re.escape(old) + r"(?![A-Za-z0-9_])", new, text)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--objects", default=str(ROOT / "tools" / "prefix_objects.json"))
    args = ap.parse_args()

    objects = {}
    op = Path(args.objects)
    if op.exists():
        objects = json.loads(op.read_text(encoding="utf-8"))
    subs = build_substitutions(objects)

    failures = []
    for old_path, new_path in PROTECTED:
        before = git_show(args.base, old_path)
        after_p = ROOT / new_path
        if before is None:
            print(f"  SKIP  {old_path} (not in {args.base})")
            continue
        if not after_p.exists():
            print(f"  FAIL  {new_path} (missing after refactor)")
            failures.append(new_path)
            continue
        after = after_p.read_text(encoding="utf-8")
        expected = apply_subs(before, subs)
        if expected == after:
            print(f"  PASS  {new_path}  (identical modulo table/object renames)")
        else:
            print(f"  FAIL  {new_path}  (differs beyond the permitted renames)")
            import difflib
            diff = list(difflib.unified_diff(
                expected.splitlines(), after.splitlines(),
                fromfile="expected", tofile="actual", lineterm="", n=1,
            ))
            for line in diff[:40]:
                print("        " + line)
            failures.append(new_path)

    print()
    if failures:
        print(f"FAILED: {len(failures)} protected file(s) changed beyond the permitted renames")
        return 1
    print("ALL PROTECTED FILES OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
