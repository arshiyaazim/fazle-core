#!/usr/bin/env python3
"""Run a read-only shadow comparison for recruitment/general inquiry replies."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CORE = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "PHASE_UNIFIED_RECRUITMENT_CONVERSATION_LAYER_REPORT_2026_05_15.md"
JSON_PATH = ROOT / "phase_unified_recruitment_shadow_results_2026_05_15.json"

if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))


def load_core_env() -> None:
    """Load simple KEY=VALUE entries from /home/azim/core/.env without shell sourcing."""
    env_path = CORE / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    if "DATABASE_URL" not in os.environ and os.environ.get("DATABASE_URL_TEMPLATE"):
        host = os.environ.get("POSTGRES_HOST") or os.environ.get("DB_HOST") or "127.0.0.1"
        os.environ["DATABASE_URL"] = os.environ["DATABASE_URL_TEMPLATE"].replace("__HOST__", host)

RECRUITMENT_RE = re.compile(
    r"(চাকরি|চাকরির|চাকরী|চাকুরি|কাজ চাই|কাজ আছে|আবেদন|বেতন কত|বেতন কাঠামো|নিয়োগ|আগ্রহী|জয়েন|সার্ভে|\bjob\b|\bapply\b|\bsalary\b|\bvacancy\b|\binterested\b|\bjoining\b|survey scout)",
    re.IGNORECASE,
)

OPERATIONAL_EXCLUDE_RE = re.compile(
    r"(^\s*(mv|m/v|id\s*:)|escort\s+name|escort\s+mobile|lighter\s*:|master\s+nmbr|\b[bnc]\)\s*\d+\s*/?-|\d+\s*/-|স্বাগতম! আমাদের কাছে আবেদন|ধন্যবাদ আমাদের সাথে যোগাযোগ|^\s*📌\s*আবেদনের জন্য যা লাগবে|like\s+comment\s+share|orarcer|anonymous participant|রিলিজ|খরচের টাকা|টাকা পাবো|হাজিরা)",
    re.IGNORECASE,
)


def is_recruitment_sample(text: str) -> bool:
    compact = " ".join((text or "").split())
    if not compact or OPERATIONAL_EXCLUDE_RE.search(compact):
        return False
    return bool(RECRUITMENT_RE.search(compact))


def _short(text: str, limit: int = 240) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


async def _get_columns(conn, table: str) -> set[str]:
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1
        """,
        table,
    )
    return {row["column_name"] for row in rows}


async def _fetch_from_db(limit: int) -> list[dict[str, Any]]:
    from app.database import db_conn, init_db

    await init_db()
    async with db_conn() as conn:
        samples: list[dict[str, Any]] = []
        table_specs = [
            ("fazle_whatsapp_messages", ("message_body", "body", "content", "message_text"), ("sender_number", "phone", "contact_identifier"), ("received_at", "created_at", "timestamp")),
            ("wbom_inbound_messages", ("message_text", "message_body", "body", "content"), ("sender_number", "phone", "from_number"), ("received_at", "created_at", "timestamp")),
            ("fazle_message_archive", ("message_text", "message_body", "body", "content"), ("sender", "sender_number", "phone"), ("created_at", "received_at", "timestamp")),
        ]
        for table, text_candidates, sender_candidates, time_candidates in table_specs:
            columns = await _get_columns(conn, table)
            if not columns:
                continue
            text_col = next((col for col in text_candidates if col in columns), None)
            sender_col = next((col for col in sender_candidates if col in columns), None)
            time_col = next((col for col in time_candidates if col in columns), None)
            if not text_col or not sender_col:
                continue
            order = f"ORDER BY {time_col} DESC" if time_col else ""
            direction_filter = ""
            if "direction" in columns:
                direction_filter = "AND COALESCE(direction, '') IN ('inbound', 'incoming', 'received')"
            sql = f"""
                SELECT {sender_col}::text AS sender, {text_col}::text AS text
                FROM {table}
                WHERE {text_col} IS NOT NULL
                  AND {text_col} ~* $1
                  {direction_filter}
                {order}
                LIMIT $2
            """
            rows = await conn.fetch(sql, RECRUITMENT_RE.pattern, max(limit * 5, 20))
            for row in rows:
                text = (row["text"] or "").strip()
                sender = (row["sender"] or "shadow-db").strip()
                if is_recruitment_sample(text):
                    samples.append({"sender": sender, "text": text, "source": f"db:{table}"})
            if len(samples) >= limit:
                break
        return samples[:limit]


def _fetch_from_exports(limit: int) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for path in sorted(ROOT.glob("wa_conversation_*.txt")):
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeError):
            continue
        current: list[str] = []

        for line in content.splitlines():
            if line.startswith("["):
                if current:
                    text = " ".join(" ".join(current).split())
                    current = []
                    if is_recruitment_sample(text):
                        samples.append({"sender": path.stem.rsplit("_", 1)[-1], "text": text, "source": f"export:{path.name}"})
                        if len(samples) >= limit:
                            return samples
                if "←" not in line:
                    continue
                after_arrow = line.split("←", 1)[1].strip()
                parts = after_arrow.split(None, 1)
                if len(parts) == 2:
                    current.append(parts[1])
                continue
            if current and (line.startswith(" ") or line.startswith("\t")):
                current.append(line.strip())
        if current:
            text = " ".join(" ".join(current).split())
            if is_recruitment_sample(text):
                samples.append({"sender": path.stem.rsplit("_", 1)[-1], "text": text, "source": f"export:{path.name}"})
                if len(samples) >= limit:
                    return samples
    return samples


async def collect_real_samples(limit: int) -> tuple[list[dict[str, Any]], str]:
    try:
        samples = await _fetch_from_db(limit)
        if samples:
            return samples, "database"
    except (RuntimeError, OSError, ValueError, ImportError) as exc:
        db_error = f"database unavailable: {type(exc).__name__}: {exc}"
    else:
        db_error = "database returned no recruitment-like messages"

    samples = _fetch_from_exports(limit)
    if samples:
        return samples, f"conversation exports after {db_error}"
    return [], db_error


async def run_shadow(limit: int, use_llm: bool) -> dict[str, Any]:
    from modules.conversation_layer import generate_recruitment_reply_shadow, simulate_current_core_reply

    samples, source_note = await collect_real_samples(limit)
    results = []
    for idx, sample in enumerate(samples, 1):
        sender = sample.get("sender") or f"shadow-{idx}"
        text = sample["text"]
        current = await simulate_current_core_reply(sender=sender, text=text, source="shadow-test")
        unified = await generate_recruitment_reply_shadow(
            sender=sender,
            text=text,
            source="shadow-test",
            use_llm=use_llm,
        )
        results.append({"sample": sample, "current_core": current, "unified_layer": unified})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "limit": limit,
        "use_llm": use_llm,
        "source_note": source_note,
        "results": results,
    }


def render_report(payload: dict[str, Any]) -> str:
    results = payload["results"]
    lines = [
        "# PHASE - UNIFIED RECRUITMENT CONVERSATION LAYER AUDIT + SAFE INTEGRATION",
        "",
        f"Generated: {payload['generated_at']}",
        f"Shadow mode: no sends, no DB schema changes, no operational mutations. LLM used: {payload['use_llm']}",
        f"Sample source: {payload['source_note']}",
        "",
        "## 1. current fazle-system conversational capabilities",
        "Old fazle-system had a richer recruitment/social brain: route-based social prompts, job-seeker playbooks, confusion escalation, owner feedback capture, OCR/audio intake, reply safety classification, anti-repetition memory, and canonical recruitment knowledge. Its weakness is that conversation, sending, drafting, training, and contact mutation were close together in the webhook flow.",
        "",
        "## 2. full message processing flow",
        "Old flow: WhatsApp webhook parse -> dedup/lock -> media OCR or transcription -> store/forward -> owner command handling -> brain /chat or /chat/multimodal -> safety classify -> auto-send safe replies or save draft for owner approval -> optional owner feedback/training memory. Current core flow: bridge/webhook -> message_router -> identity -> intent -> deterministic recruitment/KB/templates/RAG/LLM -> caller sends reply; admin and operational workflows are separated by role and intent gates.",
        "",
        "## 3. recruitment AI workflow map",
        "Recommended recruitment-only map: inbound text/media transcript -> read-only identity/intent -> recruitment signal analysis -> current KB/RAG/templates -> playbook prompt -> optional Ollama phrasing -> safety gate -> shadow result or owner-reviewed draft. Live recruitment session mutation stays exclusively inside recruitment_flow after owner approval or explicit router integration.",
        "",
        "## 4. reusable conversational resources",
        "Reusable: recruitment_canonical.md facts, prompt_router social rules, response_playbooks job_seeker/unknown playbooks, confusion-handling policy, safety keyword gates, interest hot/warm/risk classification, and owner feedback quality loop. Do not reuse old direct Meta send or webhook mutation code in core.",
        "",
        "## 5. missing resources in fazle-core",
        "Core has strong deterministic routing, KB, RAG, templates, and a recruitment funnel, but lacks a unified recruitment prompt context, explicit trust/fee/document/playbook focus detection, multi-question answer composition, candidate temperature metadata, and a shadow comparison harness. The current KB also contains a fee-policy inconsistency versus old canonical notes, so fee answers should remain review-safe until owner resolves policy.",
        "",
        "## 6. safe integration feasibility",
        "Feasible if kept as a read-only layer first. The new module can enrich wording and clarification while recruitment_flow remains the only writer for candidate collection state. It must never call payroll, escort lifecycle, payment, roster, admin approval, or outbound modules.",
        "",
        "## 7. operational risk assessment",
        "Low risk in current state because the layer is inert and shadow-only. Medium risk if wired before resolving fee policy and LLM quality gates. High risk if connected directly to live sends or DB mutations without owner review, because old-style social automation could expose sensitive or contradictory operational information.",
        "",
        "## 8. exact modules/files involved",
        "Current core: core/modules/message_router, core/modules/recruitment_flow, core/modules/fazle_intent, core/modules/knowledge_base, core/modules/reply_templates, core/modules/rag, core/app/ollama. New shadow files: core/modules/conversation_layer and core/scripts/shadow_recruitment_conversation_layer.py. Old reference files: ai-call-platform/fazle-system/brain/prompt_router.py, brain/owner_control/response_playbooks.py, brain/knowledge/recruitment_canonical.md, social-engine/webhooks.py, social-engine/whatsapp.py.",
        "",
        "## 9. recommended architecture",
        "Keep message_router authoritative. Add conversation_layer as a read-only adapter: it receives sender/text/history, reads KB/RAG/templates, generates a candidate reply, classifies safety, and returns metadata. A future integration should place it only after recruitment intent is confirmed and before outbound delivery, with feature flags, audit logging, and owner review for uncertain replies.",
        "",
        "## 10. safest implementation order",
        "1. Run shadow tests only. 2. Resolve fee/joining-cost policy contradiction. 3. Add owner-reviewed draft mode for recruitment only. 4. Enable for low-risk FAQ intents like documents/location/training. 5. Later consider live auto-send only for replies marked safe with deterministic fallback and rollback switch.",
        "",
        "## 11. live shadow-test comparison results",
    ]

    if not results:
        lines.append("No real recruitment-like messages were found from DB or local exports, so no live comparison was produced.")
    else:
        for idx, item in enumerate(results, 1):
            sample = item["sample"]
            current = item["current_core"]
            unified = item["unified_layer"]
            signals = unified.get("signals") or {}
            lines.extend([
                "",
                f"### Sample {idx} ({sample['source']})",
                f"Inbound: {_short(sample['text'])}",
                f"A. current fazle-core reply [{current.get('path')}]: {_short(current.get('reply', ''))}",
                f"B. simulated unified AI-layer reply [{unified.get('path')}, safety={unified.get('safety')}]: {_short(unified.get('reply', ''))}",
                f"Signals: focus={signals.get('focus')}, temperature={signals.get('temperature')}, risk={signals.get('risk')}",
            ])

    lines.extend([
        "",
        "## 12. estimated improvement potential",
        "Expected improvement is moderate to high for recruitment conversations: better multi-question handling, warmer Bengali phrasing, trust repair, document/salary/training specificity, and lower robotic repetition. Operational safety stays intact only while this remains read-only or draft-only with clear feature flags.",
        "",
        "## Integration status",
        "Implemented as shadow-only code. It is not imported by the live router and does not send messages, write recruitment sessions, alter schema, or touch operational workflows.",
    ])
    return "\n".join(lines) + "\n"


async def main() -> None:
    load_core_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--json", type=Path, default=JSON_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()

    payload = await run_shadow(limit=args.limit, use_llm=args.use_llm)
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.report.write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({"report": str(args.report), "json": str(args.json), "samples": len(payload["results"]), "source": payload["source_note"]}, ensure_ascii=False))


if __name__ == "__main__":
    os.chdir(CORE)
    asyncio.run(main())
