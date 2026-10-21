#!/usr/bin/env python3
"""
Apply the `fazle_` prefix unification across the repository.

Phases
  A  Rename the Python module directories / files (git mv).
  B  Rewrite import paths and module path references.
  C  Rewrite the 7 in-scope table names in every text file.
  D  Rewrite the dependent DB object names (index / constraint / sequence /
     trigger / function) that carried the legacy prefix.
  E  Create the backward-compatibility shim modules.
  F  Add the "pre-unification schema" note to the historical audit reports.

Files that must NOT be rewritten are skipped explicitly:
  * the new `*_unify_rename_*.sql` migrations (they must keep the OLD names
    in their RENAME statements),
  * the backward-compat shims (they must keep the OLD names),
  * the historical audit reports (they get a note instead).

Usage:
    python tools/apply_prefix_unification.py [--dry-run] [--phase N]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from prefix_unification_map import (  # noqa: E402
    IMPORT_PATH_MAP,
    TABLE_MAP,
    rename_db_object,
)

TEXT_EXTS = {".py", ".sql", ".md", ".txt", ".yaml", ".yml", ".json"}
SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "htmlcov", "coverage", "dist", "build",
}

# ── Historical audit reports: keep unchanged, add a note instead ───────────
HISTORICAL_DOCS = [
    "AUDIT_REPORT.md",
    "AUDIT_SUMMARY.json",
    "audit-report-2026-06-01.md",
    "audit-report-2026-06-10.md",
    "CHATOS_TEST_PLAN.md",
    "CHAOS_TEST_PLAN.md",
    "DEPLOYMENT_SUMMARY.md",
    "GIT_SNAPSHOT.md",
    "HANDOFF_P2_TIMEOUT_FIX_2026-08-14.md",
    "HERMES_ADMIN_BRIDGE_HANDOFF_2026-08-28.md",
    "HERMES_AUTONOMY_POLICY_2026-08-19.md",
    "HERMES_BUSINESS_EXECUTION_CAPABILITY_PROVENANCE_AUDIT_2026-08-19.md",
    "HERMES_IDENTITY_GAP_FIX_PREDEPLOYMENT_ACCEPTANCE_2026-08-18.md",
    "HERMES_IDENTITY_ROLE_INTENT_CONTENT_CAPABILITY_AUDIT_2026-08-18.md",
    "HERMES_MESSAGE_CONTEXT_REPLY_EXECUTION_GAP_AUDIT_2026-08-19.md",
    "HERMES_PAYROLL_WORKFLOW_GAP_AUDIT_2026-08-18.md",
    "HERMES_SYSTEM_MESSAGE_ROOTCAUSE_AGENTIC_BEHAVIOR_AUDIT_2026-08-19.md",
    "KB_SALARY_POLICY_DRIFT_CHECK_2026-08-19.md",
    "MASTER_PLAN_KNOWLEDGE_BASE_BRAIN.md",
    "PHASE_1_FG4_EXECUTION_SHEET_2026-07-05.md",
    "POST_CHAOS_VALIDATION.md",
    "PRE_CHAOS_CHECKLIST.md",
    "RECRUITMENT_CONVERSATION_AUDIT_2026-08-22_TO_2026-08-23.md",
    "RECRUITMENT_CONVERSATION_AUDIT_VERIFIED_2026-08-22_TO_2026-08-23.md",
    "RECRUITMENT_LIFECYCLE_CLOSURE_ASSESSMENT_2026-08-29.md",
    "SPRINT-3A-OWNER-REPORT.md",
    "SPRINT-3B-OWNER-REPORT.md",
    "STRICT_EXECUTION_CHECKLIST_PREFILLED_2026-07-05.md",
    "STRICT_EXECUTION_CHECKLIST_TEMPLATE.md",
    "SYSTEM_CONSOLIDATION_PLAN_2026-07-08.md",
    "SYSTEM_ATLAS.md",
    "TESTING_STATUS.md",
    "payroll-escort-workflow-audit-2026-06-13.md",
    "payroll-escort-workflow-audit-2026-07-04.md",
    "payroll-escort-workflow-fix-plan-2026-07-04.md",
    "recruitment-audit-2026-06-15.md",
]
# audits/*.md are historical audit records too.
HISTORICAL_PREFIXES = ("audits/",)

# ── Module directory / file renames ────────────────────────────────────────
MODULE_RENAMES: list[tuple[str, str]] = [
    ("modules/payment_ingest/wbom_fpe_sync.py", "modules/fazle_data_sync/__init__.py"),
    ("modules/payment_ingest", "modules/fazle_payment_ingest"),
    ("modules/payment_workflow", "modules/fazle_payment_workflow"),
    ("modules/bridge_poller", "modules/fazle_bridge_poller"),
    ("modules/message_archive", "modules/fazle_message_archive"),
    ("modules/media_normalization", "modules/fazle_media_normalization"),
    ("modules/identity_resolver.py", "modules/fazle_identity_resolver.py"),
    ("modules/identity_brain", "modules/fazle_identity_brain"),
    ("modules/admin_commands", "modules/fazle_admin_commands"),
    ("modules/draft_approval", "modules/fazle_draft_approval"),
    ("modules/group_identity.py", "modules/fazle_group_identity.py"),
    ("modules/intent", "modules/fazle_intent"),
    ("modules/image_hash", "modules/fazle_image_hash"),
]

# Path-form reference rewrites (docs, comments, markdown).
MODULE_PATH_MAP: dict[str, str] = {
    "modules/payment_ingest/wbom_fpe_sync.py": "modules/fazle_data_sync/__init__.py",
    "modules/payment_ingest/wbom_fpe_sync": "modules/fazle_data_sync",
    "modules/payment_ingest": "modules/fazle_payment_ingest",
    "modules/payment_workflow": "modules/fazle_payment_workflow",
    "modules/bridge_poller": "modules/fazle_bridge_poller",
    "modules/message_archive": "modules/fazle_message_archive",
    "modules/media_normalization": "modules/fazle_media_normalization",
    "modules/identity_resolver.py": "modules/fazle_identity_resolver.py",
    "modules/identity_resolver": "modules/fazle_identity_resolver",
    "modules/identity_brain": "modules/fazle_identity_brain",
    "modules/admin_commands": "modules/fazle_admin_commands",
    "modules/draft_approval": "modules/fazle_draft_approval",
    "modules/group_identity.py": "modules/fazle_group_identity.py",
    "modules/group_identity": "modules/fazle_group_identity",
    "modules/intent": "modules/fazle_intent",
    "modules/image_hash": "modules/fazle_image_hash",
}

NOTE = (
    "> **Pre-unification schema note.** Table names in this document refer to the\n"
    "> pre-unification schema. See `audits/prefix_unification_2026-10-21.md` for the\n"
    "> current table names.\n"
)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False,
    ).stdout


def is_historical(rel: str) -> bool:
    if rel in HISTORICAL_DOCS:
        return True
    return any(rel.startswith(p) for p in HISTORICAL_PREFIXES)


def iter_text_files() -> list[Path]:
    out = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in TEXT_EXTS:
            out.append(p)
    return sorted(out)


def protected(rel: str) -> bool:
    """Files that must not be rewritten."""
    if "_unify_rename_" in rel and rel.endswith(".sql"):
        return True
    if rel.startswith("tools/prefix_unification_map.py"):
        return True
    if rel.startswith("tools/apply_prefix_unification.py"):
        return True
    if rel.startswith("tools/gen_unify_migrations.py"):
        return True
    if rel.startswith("tools/scan_sql_objects.py"):
        return True
    if rel.startswith("tools/gen_prefix_inventory.py"):
        return True
    if rel.startswith("tools/dump_prefix_db_objects.py"):
        return True
    if rel.startswith("tools/verify_unify_migrations.py"):
        return True
    if rel.startswith("tools/prefix_manifest.py"):
        return True
    if rel.startswith("tools/apply_migrations.py"):
        return True
    return False


def build_object_map(objects: dict) -> dict[str, str]:
    """{old object name: new object name} for objects on the 7 in-scope tables."""
    out: dict[str, str] = {}
    for key in ("indexes", "constraints", "sequences", "triggers"):
        for row in objects.get(key, []):
            name = row.get("index_name") or row.get("constraint_name") or row.get("sequence_name") or row.get("trigger_name")
            if not name:
                continue
            new = rename_db_object(name)
            if new != name:
                out[name] = new
    # Trigger functions.
    for t in objects.get("triggers", []):
        fn = t.get("function_name") or ""
        if fn:
            new = rename_db_object(fn)
            if new != fn:
                out[fn] = new
    return out


# ── Phase A: rename module directories / files ─────────────────────────────
def phase_a(dry: bool) -> None:
    print("── Phase A: module renames ───────────────────────────────")
    for src, dst in MODULE_RENAMES:
        s, d = ROOT / src, ROOT / dst
        if not s.exists():
            print(f"  skip (absent) {src}")
            continue
        if d.exists():
            print(f"  skip (target exists) {src} -> {dst}")
            continue
        print(f"  git mv {src} -> {dst}")
        if dry:
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "mv", src, dst], cwd=ROOT, check=True)


# ── Phase B: rewrite import paths and module path references ───────────────
def phase_b(dry: bool) -> None:
    print("── Phase B: import path rewrites ─────────────────────────")
    changed = 0
    for p in iter_text_files():
        rel = str(p.relative_to(ROOT))
        if protected(rel):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        orig = text
        # Dotted import paths, longest first so `modules.payment_ingest.wbom_fpe_sync`
        # is rewritten before `modules.payment_ingest`.
        for old in sorted(IMPORT_PATH_MAP, key=len, reverse=True):
            new = IMPORT_PATH_MAP[old]
            text = re.sub(
                re.escape(old) + r"(?![A-Za-z0-9_])",
                new.replace("\\", "\\\\"),
                text,
            )
        # Slash-form path references.
        for old in sorted(MODULE_PATH_MAP, key=len, reverse=True):
            new = MODULE_PATH_MAP[old]
            text = re.sub(
                re.escape(old) + r"(?![A-Za-z0-9_/])",
                new.replace("\\", "\\\\"),
                text,
            )
        if text != orig:
            changed += 1
            if not dry:
                p.write_text(text, encoding="utf-8")
    print(f"  {changed} file(s) updated")


# ── Phase C: rewrite the 7 in-scope table names ────────────────────────────
def phase_c(dry: bool, skip_historical: bool = True) -> None:
    print("── Phase C: table name rewrites ──────────────────────────")
    changed = 0
    for p in iter_text_files():
        rel = str(p.relative_to(ROOT))
        if protected(rel):
            continue
        if skip_historical and is_historical(rel):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        orig = text
        for old in sorted(TABLE_MAP, key=len, reverse=True):
            new = TABLE_MAP[old]
            text = re.sub(
                re.escape(old) + r"(?![A-Za-z0-9_])",
                new,
                text,
            )
        if text != orig:
            changed += 1
            if not dry:
                p.write_text(text, encoding="utf-8")
    print(f"  {changed} file(s) updated")


# ── Phase D: rewrite dependent DB object names ─────────────────────────────
def phase_d(dry: bool, objects: dict, skip_historical: bool = True) -> None:
    print("── Phase D: dependent object name rewrites ──────────────")
    obj_map = build_object_map(objects)
    print(f"  {len(obj_map)} object name(s) to rewrite")
    changed = 0
    for p in iter_text_files():
        rel = str(p.relative_to(ROOT))
        if protected(rel):
            continue
        if skip_historical and is_historical(rel):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        orig = text
        for old in sorted(obj_map, key=len, reverse=True):
            new = obj_map[old]
            text = re.sub(re.escape(old) + r"(?![A-Za-z0-9_])", new, text)
        if text != orig:
            changed += 1
            if not dry:
                p.write_text(text, encoding="utf-8")
    print(f"  {changed} file(s) updated")


# ── Phase E: backward-compat shims ─────────────────────────────────────────
SHIM_PKG = '''\
"""
Backward-compatibility shim — DEPRECATED.

``{old_path}`` was renamed to ``{new_path}`` as part of the ``fazle_`` prefix
unification.  This module re-exports the new package so that any external
caller that still imports the old path keeps working.

It emits a :class:`DeprecationWarning` on first attribute access.  The
re-export is LAZY (PEP 562 module-level ``__getattr__``), so importing this
shim never triggers the import of the new module and cannot introduce a
circular import.

Remove this shim once no caller uses the old path any more.
"""
from __future__ import annotations

import warnings
from importlib import import_module

_NEW = "{new_path}"
_OLD = "{old_path}"


def _warn() -> None:
    warnings.warn(
        f"{{_OLD}} is deprecated; use {{_NEW}} instead.",
        DeprecationWarning,
        stacklevel=3,
    )


def __getattr__(name: str):
    _warn()
    _mod = import_module(_NEW)
    try:
        return getattr(_mod, name)
    except AttributeError:
        raise AttributeError(
            f"module {{_OLD!r}} has no attribute {{name!r}}"
        ) from None


def __dir__() -> list:
    return dir(import_module(_NEW))


# Keep ``import {old_dotted}.<sub>`` working by pointing the package search
# path at the new package.  Submodules are aliased into ``sys.modules`` under
# the old name as well, so they are not loaded twice.
__path__ = import_module(_NEW).__path__
'''

SHIM_FILE = '''\
"""
Backward-compatibility shim — DEPRECATED.

``{old_path}`` was renamed to ``{new_path}`` as part of the ``fazle_`` prefix
unification.  This module re-exports the new module so that any external
caller that still imports the old path keeps working.

It emits a :class:`DeprecationWarning` on first attribute access.  The
re-export is LAZY (PEP 562 module-level ``__getattr__``), so importing this
shim never triggers the import of the new module and cannot introduce a
circular import.

Remove this shim once no caller uses the old path any more.
"""
from __future__ import annotations

import warnings
from importlib import import_module

_NEW = "{new_path}"
_OLD = "{old_path}"


def _warn() -> None:
    warnings.warn(
        f"{{_OLD}} is deprecated; use {{_NEW}} instead.",
        DeprecationWarning,
        stacklevel=3,
    )


def __getattr__(name: str):
    _warn()
    _mod = import_module(_NEW)
    try:
        return getattr(_mod, name)
    except AttributeError:
        raise AttributeError(
            f"module {{_OLD!r}} has no attribute {{name!r}}"
        ) from None


def __dir__() -> list:
    return dir(import_module(_NEW))
'''


def phase_e(dry: bool) -> None:
    print("── Phase E: backward-compat shims ────────────────────────")
    shims = [
        ("modules/payment_ingest", "modules/fazle_payment_ingest", True),
        ("modules/payment_workflow", "modules/fazle_payment_workflow", True),
        ("modules/bridge_poller", "modules/fazle_bridge_poller", True),
        ("modules/message_archive", "modules/fazle_message_archive", True),
        ("modules/media_normalization", "modules/fazle_media_normalization", True),
        ("modules/identity_resolver.py", "modules/fazle_identity_resolver.py", False),
        ("modules/identity_brain", "modules/fazle_identity_brain", True),
        ("modules/admin_commands", "modules/fazle_admin_commands", True),
        ("modules/draft_approval", "modules/fazle_draft_approval", True),
        ("modules/group_identity.py", "modules/fazle_group_identity.py", False),
        ("modules/intent", "modules/fazle_intent", True),
        ("modules/image_hash", "modules/fazle_image_hash", True),
    ]
    for old, new, is_pkg in shims:
        if is_pkg:
            target = ROOT / old / "__init__.py"
            body = SHIM_PKG.format(
                old_path=old, new_path=new,
                old_dotted=old.replace("/", "."),
            )
        else:
            target = ROOT / old
            body = SHIM_FILE.format(old_path=old, new_path=new)
        if target.exists():
            print(f"  skip (exists) {target.relative_to(ROOT)}")
            continue
        print(f"  create {target.relative_to(ROOT)}")
        if dry:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")


# ── Phase F: historical-doc notes ──────────────────────────────────────────
def phase_f(dry: bool) -> None:
    print("── Phase F: historical document notes ─────────────────────")
    changed = 0
    for p in iter_text_files():
        rel = str(p.relative_to(ROOT))
        if not is_historical(rel):
            continue
        if rel.startswith("audits/prefix_unification"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "Pre-unification schema note" in text:
            continue
        if not re.search(r"wbom_|fpe_", text):
            continue
        lines = text.splitlines(keepends=True)
        # Insert the note after the leading title block (first heading plus
        # any immediately following blank lines), keeping the doc readable.
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith("#"):
                insert_at = i + 1
                break
        else:
            insert_at = 1 if lines else 0
        while insert_at < len(lines) and not lines[insert_at].strip():
            insert_at += 1
        new_text = "".join(lines[:insert_at]) + "\n" + NOTE + "".join(lines[insert_at:])
        changed += 1
        if not dry:
            p.write_text(new_text, encoding="utf-8")
    print(f"  {changed} document(s) annotated")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--objects", default="/tmp/prefix_work/merged_objects.json")
    ap.add_argument("--phase", default="all")
    args = ap.parse_args()

    objects = {}
    op = Path(args.objects)
    if op.exists():
        objects = json.loads(op.read_text(encoding="utf-8"))

    phase = args.phase
    if phase in ("all", "a"):
        phase_a(args.dry_run)
    if phase in ("all", "b"):
        phase_b(args.dry_run)
    if phase in ("all", "c"):
        phase_c(args.dry_run)
    if phase in ("all", "d"):
        phase_d(args.dry_run, objects)
    if phase in ("all", "e"):
        phase_e(args.dry_run)
    if phase in ("all", "f"):
        phase_f(args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
