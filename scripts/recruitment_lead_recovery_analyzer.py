#!/usr/bin/env python3
"""Read-only recruitment conversation audit and lead recovery analyzer.

Reads synced WhatsApp messages from Postgres, analyzes full last-7-day timelines,
and writes JSON/CSV/Markdown exports for human review. It never sends messages,
updates sessions, changes schema, or calls operational workflows.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CORE = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "recruitment_lead_recovery_last7d_2026_05_15.json"
CSV_PATH = ROOT / "recruitment_lead_recovery_last7d_2026_05_15.csv"
REPORT_PATH = ROOT / "PHASE_RECRUITMENT_CONVERSATION_AUDIT_LEAD_RECOVERY_2026_05_15.md"

if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

RECRUITMENT_PATTERNS = (
    "চাকরি", "চাকরির", "চাকরী", "চাকুরি", "কাজ চাই", "কাজ আছে", "লোক নিচ্ছেন",
    "নিয়োগ", "নিয়োগ", "আবেদন", "apply", "vacancy", "job", "interested",
    "joining", "join", "জয়েন", "জয়েন", "salary", "বেতন", "qualification",
    "যোগ্যতা", "requirements", "কি কি লাগবে", "কী কী লাগবে", "office", "অফিস",
    "location", "ঠিকানা", "survey scout", "সার্ভে", "security guard",
)

STRONG_RECRUITMENT_PATTERNS = (
    "চাকরি", "চাকরির", "চাকরী", "চাকুরি", "কাজ চাই", "কাজ আছে", "লোক নিচ্ছেন",
    "নিয়োগ", "নিয়োগ", "আবেদন", "apply", "vacancy", "job", "interested",
    "joining", "join", "জয়েন", "জয়েন", "qualification", "যোগ্যতা", "requirements",
    "কি কি লাগবে", "কী কী লাগবে", "survey scout", "সার্ভে", "security guard",
)

CANDIDATE_INTENT_PATTERNS = (
    "চাকরি", "চাকরির", "চাকরী", "চাকুরি", "job", "apply", "আবেদন", "vacancy",
    "নিয়োগ", "নিয়োগ", "লোক নিচ্ছেন", "কাজ চাই", "কাজ আছে", "i need a job",
    "office kotai", "অফিস কোথায়", "অফিস কোথায়", "কি কি লাগবে", "কী কী লাগবে",
    "সার্টিফিকেট", "qualification", "requirements", "security guard job",
)

FRUSTRATION_PATTERNS = (
    "বুঝতে পারছেন", "বুঝেন না", "একই কথা", "বার বার", "আগের প্রশ্ন", "উত্তর দেন",
    "উত্তর পরে", "কি বলেন", "কথাই বুঝেন না", "রাগ", "বিরক্ত", "সমস্যা", "complain",
    "don't understand", "same reply", "answer my question", "why", "কেন",
)

GENERIC_REPLY_PATTERNS = (
    "আপনার বয়স কত বছর", "দয়া করে সঠিক বয়স লিখুন", "আপনার পুরো নাম কি",
    "স্বাগতম! আমাদের কাছে আবেদন", "ধন্যবাদ আমাদের সাথে যোগাযোগ", "আপনার তথ্য সফলভাবে সংগ্রহ",
    "আপনার আবেদন ইতিমধ্যে প্রক্রিয়াধীন", "কীভাবে সাহায্য করতে পারি",
)

QUESTION_PATTERNS = (
    "কি", "কী", "কেন", "কিভাবে", "কোথায়", "কোথায়", "কত", "কখন", "কোন", "?",
    "what", "why", "how", "where", "when", "which",
)

OPERATIONAL_NOISE_PATTERNS = (
    "escort name", "escort mobile", "lighter:", "master nmbr", "mv ", "m/v",
    "রিলিজ", "হাজিরা", "খরচের টাকা", "টাকা পাবো", "id:", "paid", "advance",
    "টোটাল বাকি", "অগ্রিম জমা", "হিসাব", "বিল", "দিউটি", "ডিউটি", "program",
    "জাহাজ", "স্টাফ", "হাত খরচ", "খরচ", "দার দেনা", "প্রোগ্রাম", "রিলিজ",
    "release", "cash", "bkash", "nagad", "public group", "anonymous member",
    "pending admin approval", "like comment share", "write something", "feeling", "poll",
)

OCR_SOCIAL_NOISE_PATTERNS = (
    "public group", "anonymous member", "pending admin", "pastelpomelo", "write something",
    "feeling", "poll", "photos events files", "like", "comment", "share", "joined +",
)

DIRECT_HUMAN_LEAD_PATTERNS = (
    "job dorkar", "i need a job", "চাকরি প্রয়োজন", "চাকরি প্রয়োজন", "চাকরি করতে চাই",
    "job.কি.আছে", "job ki ache", "security guard job", "security job", "office kotai",
    "অফিসে লোক নিচ্ছেন", "আপনার অফিসে লোক নিচ্ছেন", "চাকরি করতে কি কি লাগবে",
    "কিন্ত. আমার. সাটি", "kajer bistarit", "কাজের বিস্তারিত", "লোক নিচ্ছেন",
)

STOPPED_REPLY_HOURS = 8


@dataclass
class Message:
    timestamp: str
    direction: str
    platform: str
    text: str
    classification: str | None = None
    status: str | None = None


@dataclass
class LeadAnalysis:
    phone_number: str
    platforms: list[str]
    first_interaction_date: str
    last_interaction_date: str
    message_count: int
    inbound_count: int
    outbound_count: int
    classification: str
    frustration_score: int
    repetition_score: int
    recruitment_interest_score: int
    recovery_probability: int
    frustration_level: str
    recruitment_interest_level: str
    conversation_summary: str
    detected_issues: list[str]
    weak_ai_replies: list[str]
    unanswered_questions: list[str]
    user_intention_evolution: str
    suggested_recovery_reply: str
    recommended_action: str
    recent_timeline: list[Message]


def load_core_env() -> None:
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


def configured_internal_numbers() -> set[str]:
    keys = (
        "BRIDGE1_NUMBER", "BRIDGE2_NUMBER", "ADMIN_META_NUMBER", "ADMIN_BRIDGE1_NUMBER",
        "ADMIN_BRIDGE2_NUMBER", "ACCOUNTANT_PHONE", "META_PHONE_NUMBER_ID",
    )
    numbers: set[str] = set()
    for key in keys:
        value = os.environ.get(key, "")
        for token in value.split(","):
            digits = re.sub(r"\D", "", token)
            if digits:
                numbers.add(digits)
    for key in ("ADMIN_NUMBERS", "DRAFT_ALWAYS_PHONES", "FPE_CASH_AUTHORIZED_PHONES", "FPE_INCOME_AUTHORIZED_PHONES"):
        for token in os.environ.get(key, "").split(","):
            digits = re.sub(r"\D", "", token)
            if digits:
                numbers.add(digits)
    return numbers


def normalize_text(text: str | None) -> str:
    return " ".join((text or "").split())


def lower_text(text: str | None) -> str:
    return normalize_text(text).lower()


def contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def count_any(text: str, patterns: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for pattern in patterns if pattern.lower() in lowered)


def is_question(text: str) -> bool:
    lowered = text.lower()
    return any(pattern.lower() in lowered for pattern in QUESTION_PATTERNS)


def is_operational_noise(text: str) -> bool:
    lowered = text.lower()
    if any(pattern in lowered for pattern in OPERATIONAL_NOISE_PATTERNS):
        return True
    return bool(re.search(r"\b\d{3,}\s*/-", lowered))


def is_ocr_social_noise(text: str) -> bool:
    lowered = text.lower()
    hits = sum(1 for pattern in OCR_SOCIAL_NOISE_PATTERNS if pattern in lowered)
    return hits >= 2 or "orarcer" in lowered or "pastelpome" in lowered


def has_direct_human_lead_signal(text: str) -> bool:
    lowered = text.lower()
    return any(pattern.lower() in lowered for pattern in DIRECT_HUMAN_LEAD_PATTERNS)


def is_recruitment_related(messages: list[Message]) -> bool:
    inbound_text = " ".join(m.text for m in messages if m.direction == "inbound")
    all_text = " ".join(m.text for m in messages)
    platform_set = {m.platform for m in messages if m.platform}
    strong_hits = count_any(inbound_text, STRONG_RECRUITMENT_PATTERNS)
    weak_hits = count_any(inbound_text, RECRUITMENT_PATTERNS)
    noise = is_operational_noise(inbound_text)
    direct_human = has_direct_human_lead_signal(inbound_text)
    if is_ocr_social_noise(inbound_text):
        return False
    if noise and not direct_human:
        return False
    if strong_hits >= 1 and not noise:
        return True
    if direct_human and ("meta" in platform_set or "bridge1" in platform_set):
        return True
    if weak_hits >= 2 and not noise and ("meta" in platform_set or "bridge1" in platform_set):
        return True
    return count_any(all_text, CANDIDATE_INTENT_PATTERNS) >= 2 and not noise


def level(score: int, low: int, high: int) -> str:
    if score >= high:
        return "high"
    if score >= low:
        return "medium"
    return "low"


def short(text: str, limit: int = 220) -> str:
    text = normalize_text(text)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def detect_topic(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("বেতন", "salary", "কত পাব", "মাসে")):
        return "salary"
    if any(token in lowered for token in ("কাগজ", "document", "nid", "ছবি", "কি কি লাগবে", "কী কী লাগবে", "requirements")):
        return "requirements"
    if any(token in lowered for token in ("অফিস", "ঠিকানা", "location", "কোথায়", "কোথায়")):
        return "office_location"
    if any(token in lowered for token in ("লোক নিচ্ছেন", "vacancy", "কোন কোন পদ", "পদ", "নিয়োগ", "নিয়োগ")):
        return "vacancy"
    if any(token in lowered for token in ("apply", "আবেদন", "জয়েন", "জয়েন", "joining")):
        return "application"
    if any(token in lowered for token in ("বুঝ", "একই কথা", "আগের প্রশ্ন", "উত্তর")):
        return "frustration"
    return "general"


def repeated_replies(outbound_texts: list[str]) -> tuple[int, list[str]]:
    cleaned = [normalize_text(text) for text in outbound_texts if normalize_text(text)]
    counts = Counter(cleaned)
    repeated = [text for text, count in counts.items() if count >= 2]
    if not cleaned:
        return 0, []
    max_repeat = max(counts.values(), default=0)
    repeated_generic = sum(1 for text in cleaned if contains_any(text, GENERIC_REPLY_PATTERNS))
    score = min(100, max_repeat * 18 + repeated_generic * 8 + len(repeated) * 10)
    return score, repeated[:5]


def find_unanswered_questions(messages: list[Message]) -> list[str]:
    unanswered: list[str] = []
    for index, message in enumerate(messages):
        if message.direction != "inbound" or not is_question(message.text):
            continue
        topic = detect_topic(message.text)
        following = messages[index + 1:index + 4]
        outbound_after = [m.text for m in following if m.direction == "outbound"]
        joined = " ".join(outbound_after).lower()
        if not outbound_after:
            unanswered.append(message.text)
            continue
        if topic == "salary" and not any(token in joined for token in ("বেতন", "salary", "১০", "১২", "১৫", "১৮")):
            unanswered.append(message.text)
        elif topic == "requirements" and not any(token in joined for token in ("nid", "ছবি", "কাগজ", "সার্টিফিকেট", "নাম", "বয়স")):
            unanswered.append(message.text)
        elif topic == "office_location" and not any(token in joined for token in ("অফিস", "ভিক্টোরিয়া", "পাহাড়তলী", "একে খান", "চট্টগ্রাম")):
            unanswered.append(message.text)
        elif topic == "vacancy" and not any(token in joined for token in ("পদ", "নিয়োগ", "লোক", "survey", "guard", "আবেদন")):
            unanswered.append(message.text)
        elif topic == "frustration" and contains_any(joined, GENERIC_REPLY_PATTERNS):
            unanswered.append(message.text)
    return [short(text, 180) for text in unanswered[:5]]


def summarize_intention(inbound_texts: list[str]) -> str:
    topics = [detect_topic(text) for text in inbound_texts]
    first_topic = next((topic for topic in topics if topic != "general"), "general recruitment inquiry")
    latest_topic = next((topic for topic in reversed(topics) if topic != "general"), first_topic)
    if first_topic == latest_topic:
        return f"Started and remained around {first_topic}."
    return f"Started around {first_topic}, later shifted toward {latest_topic}."


def build_summary(messages: list[Message], issues: list[str]) -> str:
    inbound = [m.text for m in messages if m.direction == "inbound"]
    first = short(inbound[0] if inbound else messages[0].text, 120)
    last_in = short(inbound[-1] if inbound else "", 120)
    if issues:
        return f"User first said: {first}. Latest inbound: {last_in}. Main issues: {', '.join(issues[:3])}."
    return f"User first said: {first}. Latest inbound: {last_in}. Conversation appears handled but may benefit from follow-up."


def build_recovery_reply(messages: list[Message], issues: list[str], interest_score: int, frustration_score: int) -> str:
    inbound_texts = [m.text for m in messages if m.direction == "inbound"]
    topic = detect_topic(" ".join(inbound_texts[-3:]))

    prefix = "ভাই, আগের কথায় যদি ঠিকমতো উত্তর না পেয়ে থাকেন তাহলে দুঃখিত।"
    if frustration_score >= 45:
        prefix = "ভাই, আপনাকে একই ধরনের উত্তর বারবার যাওয়ায় দুঃখিত। আপনার কথাটা এবার পরিষ্কারভাবে বলছি।"

    if topic == "salary":
        body = "এই কাজের বেতন সাধারণত কাজের ধরন, অভিজ্ঞতা ও ডিউটির উপর নির্ভর করে। প্রশিক্ষণ/শুরুর পর্যায়ে আনুমানিক ১০-১৫ হাজার, পরে দক্ষতা অনুযায়ী ১২-১৮ হাজার+ হতে পারে।"
        next_step = "আপনি আগ্রহী থাকলে নাম, বয়স, জেলা, অভিজ্ঞতা আর মোবাইল নম্বর পাঠান।"
    elif topic == "requirements":
        body = "চাকরির জন্য সাধারণত NID/জন্ম নিবন্ধন, ছবি, সার্টিফিকেট থাকলে সেটি, ঠিকানা/জেলা ও যোগাযোগ নম্বর দরকার হয়। অভিজ্ঞতা না থাকলেও আবেদন করা যায়।"
        next_step = "আপনি চাইলে শুধু নাম, বয়স আর জেলা পাঠালেই আমরা পরের ধাপ জানাব।"
    elif topic == "office_location":
        body = "অফিস চট্টগ্রামের পাহাড়তলী/একে খান এলাকার দিকে। সরাসরি এসে কথা বললে যাচাই করে পরিষ্কার সিদ্ধান্ত নিতে পারবেন।"
        next_step = "আসার আগে নাম ও কোন পদে আগ্রহী সেটা পাঠালে সুবিধা হবে।"
    elif topic == "vacancy":
        body = "বর্তমানে Survey Scout/Escort/Security Guard ধরনের কাজে আগ্রহী প্রার্থীদের তথ্য নেওয়া হচ্ছে। নতুন হলেও আবেদন করা যায়।"
        next_step = "কোন পদে আগ্রহী, আপনার বয়স, জেলা ও অভিজ্ঞতা লিখে পাঠান।"
    elif topic == "application" or interest_score >= 70:
        body = "আপনার আবেদন শুরু করতে আমাদের কয়েকটা তথ্য দরকার: নাম, বয়স, শিক্ষা, জেলা/বর্তমান ঠিকানা, অভিজ্ঞতা ও মোবাইল নম্বর।"
        next_step = "এই তথ্যগুলো পাঠালে অফিস থেকে পরের ধাপ জানানো হবে।"
    else:
        body = "চাকরির বিষয়ে আপনার প্রশ্ন থাকলে সরাসরি উত্তর দেব। নতুনদের জন্যও সুযোগ আছে, তবে অফিস যাচাইয়ের পর পরের ধাপ ঠিক হয়।"
        next_step = "আপনি কোন বিষয়ে জানতে চান: বেতন, কাজের ধরন, কাগজপত্র, নাকি অফিসের ঠিকানা?"

    if "user_stopped_after_bad_reply" in issues:
        next_step += " আগ্রহ থাকলে শুধু 'আছি' লিখলেও হবে, আমরা আবার শুরু করব।"

    return f"{prefix}\n{body}\n{next_step}"


def classify_conversation(issues: list[str], interest_score: int, frustration_score: int, repetition_score: int, inbound_count: int, outbound_count: int) -> str:
    issue_set = set(issues)
    if "user_stopped_after_bad_reply" in issue_set and interest_score >= 45:
        return "LOST_LEAD"
    if frustration_score >= 60 or repetition_score >= 70 or "repeated_reply_loop" in issue_set:
        return "FAILED"
    if "unanswered_question" in issue_set and outbound_count == 0:
        return "UNANSWERED"
    if "unanswered_question" in issue_set or "application_flow_stuck" in issue_set or "misunderstood_user" in issue_set:
        return "NEEDS_HUMAN_FOLLOWUP"
    if issues or (interest_score >= 55 and inbound_count > outbound_count):
        return "WEAK"
    return "GOOD"


def recommended_action(classification: str, recovery_probability: int) -> str:
    if classification in ("FAILED", "LOST_LEAD"):
        return "Human review urgently; send personalized recovery reply after owner approval."
    if classification == "NEEDS_HUMAN_FOLLOWUP":
        return "Human follow-up recommended; answer the ignored question first."
    if classification == "UNANSWERED":
        return "Reply manually; no automated send."
    if recovery_probability >= 60:
        return "Add to human-review recovery queue."
    return "Monitor; no immediate recovery message required."


def analyze_one(phone: str, messages: list[Message]) -> LeadAnalysis:
    inbound_texts = [m.text for m in messages if m.direction == "inbound"]
    outbound_texts = [m.text for m in messages if m.direction == "outbound"]
    all_text = " ".join(m.text for m in messages)
    inbound_joined = " ".join(inbound_texts)

    interest_hits = count_any(inbound_joined, RECRUITMENT_PATTERNS)
    explicit_questions = sum(1 for text in inbound_texts if is_question(text))
    interest_score = min(100, interest_hits * 18 + explicit_questions * 7 + min(len(inbound_texts), 5) * 5)

    frustration_hits = count_any(inbound_joined, FRUSTRATION_PATTERNS)
    frustration_score = min(100, frustration_hits * 22 + sum(text.count("!") for text in inbound_texts) * 5)

    repetition_score, repeated = repeated_replies(outbound_texts)
    unanswered = find_unanswered_questions(messages)

    issues: list[str] = []
    weak_replies: list[str] = []
    if repeated:
        issues.append("repeated_reply_loop")
        weak_replies.extend(short(text, 180) for text in repeated)
    if frustration_score >= 30:
        issues.append("user_frustration_detected")
    if unanswered:
        issues.append("unanswered_question")
    if repetition_score >= 45 and frustration_score >= 30:
        issues.append("application_flow_stuck")
    if inbound_texts and outbound_texts and contains_any(outbound_texts[-1], GENERIC_REPLY_PATTERNS) and contains_any(inbound_texts[-1], FRUSTRATION_PATTERNS):
        issues.append("ai_misunderstood_user")
    if outbound_texts and len(outbound_texts) >= 3:
        generic_count = sum(1 for text in outbound_texts if contains_any(text, GENERIC_REPLY_PATTERNS))
        if generic_count / max(len(outbound_texts), 1) >= 0.5:
            issues.append("generic_autoreplies_overused")
            weak_replies.extend(short(text, 180) for text in outbound_texts if contains_any(text, GENERIC_REPLY_PATTERNS))
    if inbound_texts and (not outbound_texts or messages[-1].direction == "inbound"):
        issues.append("recruitment_inquiry_unresolved")
    if messages[-1].direction == "outbound" and contains_any(messages[-1].text, GENERIC_REPLY_PATTERNS) and interest_score >= 40:
        issues.append("user_stopped_after_bad_reply")
    if "আমি তো আবেদন করিনি" in all_text or "আগের প্রশ্ন" in all_text:
        issues.append("misunderstood_user")

    issues = sorted(set(issues))
    weak_replies = list(dict.fromkeys(weak_replies))[:5]

    recovery_probability = min(
        100,
        interest_score * 0.55 + frustration_score * 0.15 + repetition_score * 0.1 + (25 if issues else 0),
    )
    classification = classify_conversation(
        issues,
        interest_score,
        frustration_score,
        repetition_score,
        len(inbound_texts),
        len(outbound_texts),
    )

    return LeadAnalysis(
        phone_number=phone,
        platforms=sorted({m.platform for m in messages if m.platform}),
        first_interaction_date=messages[0].timestamp,
        last_interaction_date=messages[-1].timestamp,
        message_count=len(messages),
        inbound_count=len(inbound_texts),
        outbound_count=len(outbound_texts),
        classification=classification,
        frustration_score=int(frustration_score),
        repetition_score=int(repetition_score),
        recruitment_interest_score=int(interest_score),
        recovery_probability=int(recovery_probability),
        frustration_level=level(int(frustration_score), 30, 60),
        recruitment_interest_level=level(int(interest_score), 35, 70),
        conversation_summary=build_summary(messages, issues),
        detected_issues=issues,
        weak_ai_replies=weak_replies,
        unanswered_questions=unanswered,
        user_intention_evolution=summarize_intention(inbound_texts),
        suggested_recovery_reply=build_recovery_reply(messages, issues, int(interest_score), int(frustration_score)),
        recommended_action=recommended_action(classification, int(recovery_probability)),
        recent_timeline=messages[-12:],
    )


async def fetch_recent_messages(days: int, excluded_numbers: set[str]) -> list[dict[str, Any]]:
    from app.database import db_conn, init_db

    await init_db()
    async with db_conn() as conn:
        rows = [
            dict(row)
            for row in await conn.fetch(
                """
                SELECT
                    COALESCE(NULLIF(canonical_phone, ''), NULLIF(sender_number, ''), NULLIF(contact_identifier, ''), 'unknown') AS phone,
                    COALESCE(direction, '') AS direction,
                    COALESCE(platform, '') AS platform,
                    COALESCE(message_body, '') AS text,
                    received_at,
                    classification,
                    status
                FROM fazle_whatsapp_messages
                WHERE received_at >= NOW() - ($1::int * INTERVAL '1 day')
                  AND message_body IS NOT NULL
                  AND COALESCE(message_body, '') <> ''
                ORDER BY phone, received_at ASC, message_id ASC
                """,
                days,
            )
        ]
    return [row for row in rows if re.sub(r"\D", "", str(row.get("phone") or "")) not in excluded_numbers]


def build_analyses(rows: list[dict[str, Any]]) -> list[LeadAnalysis]:
    grouped: dict[str, list[Message]] = defaultdict(list)
    for row in rows:
        text = normalize_text(row.get("text"))
        if not text:
            continue
        direction = (row.get("direction") or "").lower()
        if direction not in ("inbound", "outbound", "incoming", "received", "sent"):
            direction = "inbound" if direction in ("", "unknown") else direction
        if direction in ("incoming", "received"):
            direction = "inbound"
        if direction == "sent":
            direction = "outbound"
        ts = row["received_at"]
        if isinstance(ts, datetime):
            ts_text = ts.astimezone(timezone.utc).isoformat()
        else:
            ts_text = str(ts)
        grouped[str(row["phone"])].append(
            Message(
                timestamp=ts_text,
                direction=direction,
                platform=row.get("platform") or "",
                text=text,
                classification=row.get("classification"),
                status=row.get("status"),
            )
        )

    analyses = []
    for phone, messages in grouped.items():
        if not messages:
            continue
        if is_recruitment_related(messages):
            analyses.append(analyze_one(phone, messages))
    analyses.sort(
        key=lambda item: (
            item.classification not in ("FAILED", "LOST_LEAD", "NEEDS_HUMAN_FOLLOWUP", "UNANSWERED"),
            -item.recovery_probability,
            -item.frustration_score,
            item.phone_number,
        )
    )
    return analyses


def write_json(analyses: list[LeadAnalysis], path: Path, days: int, total_rows: int) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only_shadow_analysis",
        "date_range_days": days,
        "source_table": "fazle_whatsapp_messages",
        "total_rows_scanned": total_rows,
        "detected_recruitment_leads": len(analyses),
        "summary_counts": dict(Counter(a.classification for a in analyses)),
        "leads": [asdict(item) for item in analyses],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(analyses: list[LeadAnalysis], path: Path) -> None:
    fields = [
        "phone_number", "classification", "frustration_score", "repetition_score",
        "recruitment_interest_score", "recovery_probability", "frustration_level",
        "recruitment_interest_level", "last_interaction_date", "conversation_summary",
        "detected_issues", "weak_ai_replies", "unanswered_questions",
        "suggested_recovery_reply", "recommended_action",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in analyses:
            row = asdict(item)
            row["detected_issues"] = "; ".join(item.detected_issues)
            row["weak_ai_replies"] = " | ".join(item.weak_ai_replies)
            row["unanswered_questions"] = " | ".join(item.unanswered_questions)
            writer.writerow({field: row.get(field, "") for field in fields})


def render_report(analyses: list[LeadAnalysis], days: int, total_rows: int) -> str:
    counts = Counter(a.classification for a in analyses)
    weak = [a for a in analyses if a.classification in ("WEAK", "FAILED", "LOST_LEAD", "NEEDS_HUMAN_FOLLOWUP", "UNANSWERED")]
    lines = [
        "# PHASE - RECRUITMENT CONVERSATION AUDIT + LEAD RECOVERY ANALYZER",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "Mode: read-only shadow analysis. No sends, no DB mutations, no schema changes, no operational workflow calls.",
        f"Date range: last {days} days from `fazle_whatsapp_messages.received_at`.",
        f"Rows scanned: {total_rows}",
        f"Detected recruitment leads: {len(analyses)}",
        "",
        "## Classification Counts",
    ]
    for key in ("GOOD", "WEAK", "FAILED", "LOST_LEAD", "NEEDS_HUMAN_FOLLOWUP", "UNANSWERED"):
        lines.append(f"- {key}: {counts.get(key, 0)}")

    lines.extend([
        "",
        "## Detected Failed / Weak Conversations",
    ])
    if not weak:
        lines.append("No weak or failed recruitment conversations detected in the current range.")
    for item in weak[:20]:
        lines.extend([
            "",
            f"### {item.phone_number} - {item.classification}",
            f"Last interaction: {item.last_interaction_date}",
            f"Scores: frustration={item.frustration_score}, repetition={item.repetition_score}, interest={item.recruitment_interest_score}, recovery={item.recovery_probability}",
            f"Issues: {', '.join(item.detected_issues) if item.detected_issues else 'none'}",
            f"Summary: {item.conversation_summary}",
        ])
        if item.weak_ai_replies:
            lines.append(f"Weak AI replies: {' | '.join(item.weak_ai_replies[:3])}")
        if item.unanswered_questions:
            lines.append(f"Unanswered questions: {' | '.join(item.unanswered_questions[:3])}")
        lines.extend([
            "Suggested recovery reply:",
            item.suggested_recovery_reply,
            f"Recommended action: {item.recommended_action}",
        ])

    top_recovery = sorted(analyses, key=lambda a: a.recovery_probability, reverse=True)[:10]
    lines.extend(["", "## Recovery Opportunities"])
    for item in top_recovery:
        lines.append(
            f"- {item.phone_number}: {item.classification}, recovery={item.recovery_probability}, "
            f"interest={item.recruitment_interest_level}, frustration={item.frustration_level}"
        )

    lines.extend([
        "",
        "## Safety Confirmation",
        "This analyzer only reads synced WhatsApp rows and writes local export files for human review. It does not send WhatsApp messages, modify recruitment sessions, modify payroll, modify escort programs, change schema, or call operational mutation modules.",
    ])
    return "\n".join(lines) + "\n"


def write_report(analyses: list[LeadAnalysis], path: Path, days: int, total_rows: int) -> None:
    path.write_text(render_report(analyses, days, total_rows), encoding="utf-8")


async def main() -> None:
    load_core_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", type=Path, default=JSON_PATH)
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()

    rows = await fetch_recent_messages(args.days, configured_internal_numbers())
    analyses = build_analyses(rows)
    write_json(analyses, args.json, args.days, len(rows))
    write_csv(analyses, args.csv)
    write_report(analyses, args.report, args.days, len(rows))
    print(json.dumps({
        "mode": "read_only_shadow_analysis",
        "rows_scanned": len(rows),
        "detected_recruitment_leads": len(analyses),
        "classification_counts": dict(Counter(a.classification for a in analyses)),
        "json": str(args.json),
        "csv": str(args.csv),
        "report": str(args.report),
    }, ensure_ascii=False))


if __name__ == "__main__":
    os.chdir(CORE)
    asyncio.run(main())
