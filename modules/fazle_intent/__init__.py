"""
Fazle Core — Bengali Intent Engine (Phase 4H)
Rule-first → role context → Ollama fallback.

Intent categories:
  recruitment     → চাকরি / job / apply
  salary_query    → বেতন / salary / my pay
  payment_due     → টাকা কবে / পাওনা / due payment
  escort_duty     → ডিউটি / duty / vessel / program
  attendance      → হাজিরা / check-in / উপস্থিত
  complaint       → অভিযোগ / problem / complaint
  client_order    → লোক লাগবে / escort needed
  leave           → ছুটি / leave / অসুস্থ
  join            → যোগদান / joining / start duty
  slip_submission → slip / স্লিপ / image of escort/payment doc
  voice_note      → audio transcription result
  greeting        → salam / hello / hi / menu
  unknown         → Ollama fallback
"""
import re
import logging
from typing import Optional
from rapidfuzz import fuzz

log = logging.getLogger("fazle.intent")


# ── Keyword map ────────────────────────────────────────────────────────────────
INTENT_KEYWORDS: dict[str, list[str]] = {
    "recruitment": [
        "চাকরি", "চাকরির", "চাকরী", "চাকুরি", "কাজ", "job", "jobs",
        "apply", "আবেদন", "নিয়োগ", "recruitment", "vacancy", "পদ",
        "survey scout", "এস্কর্ট পদ", "যোগ্যতা", "requirement",
        "কাজ পাব", "কাজ চাই", "কাজ আছে",
    ],
    "salary_query": [
        "বেতন", "salary", "মাসিক", "মাসে কত", "কত টাকা পাব", "আয়",
        "income", "pay", "বেতন কত", "বেতন পাইনি", "আমার বেতন",
        "বেতন হয়েছে", "বেতন দেয়", "my salary", "কত পাব",
    ],
    "payment_due": [
        "টাকা", "payment", "পেমেন্ট", "বিকাশ", "bkash", "নগদ", "nagad",
        "পাঠান", "পাওনা", "টাকা কবে", "পাওনা আছে", "দিবেন কবে",
        "টাকা দেন", "হিসাব", "balance", "due",
    ],
    "escort_duty": [
        "ডিউটি", "duty", "vessel", "mv ", "m/v", "mother vessel",
        "lighter", "এস্কর্ট ডিউটি", "cargo:", "b/l", "destination:",
        "loading point", "বাল্ক", "জাহাজ", "escort program",
        "প্রোগ্রাম", "program",
    ],
    "complaint": [
        "অভিযোগ", "complaint", "সমস্যা", "problem", "অভিযোগ করছি",
        "অভিযোগ দিচ্ছি", "বেআইনি", "ঠকানো", "প্রতারণা",
        "অন্যায়", "জালিয়াতি", "abuse",
    ],
    "client_order": [
        "লোক লাগবে", "লোক দরকার", "escort needed", "এস্কর্ট লাগবে",
        "লোক পাঠান", "লোক দিন", "escort required", "need escort",
        "program create", "নতুন প্রোগ্রাম", "লোক পাঠাও",
    ],
    "leave": [
        "ছুটি", "leave", "ছুটির আবেদন", "sick leave", "অসুস্থ",
        "হাসপাতাল", "বাড়ি যাব", "আসতে পারব না", "অফ দিন",
    ],
    "join": [
        "যোগদান", "joining", "join", "যোগ দিতে", "যোগ দেব",
        "কাল থেকে", "আজ থেকে", "শুরু করব", "রিপোর্ট করব",
        "জয়েন", "জয়েনিং", "কিভাবে জয়েন", "কিভাবে আবেদন",
        "join করব", "join করতে", "ভর্তি হব", "ভর্তি হতে",
    ],
    "attendance": [
        "হাজিরা", "attendance", "উপস্থিত", "অনুপস্থিত", "present",
        "absent", "check in", "check out", "হাজির",
    ],
    "slip_submission": [
        "slip", "স্লিপ", "এস্কর্ট স্লিপ", "রিলিজ স্লিপ",
        "পেমেন্ট স্লিপ", "escort slip", "release slip",
        "document", "ডকুমেন্ট", "কাগজ",
    ],
    "greeting": [
        "আস্সালামুয়ালাইকুম", "আসালামু", "সালাম", "salam",
        "hello", "hi", "হ্যালো", "হই", "menu", "মেনু",
        "#menu", "/menu", "start", "শুরু", "হ্যালো",
    ],
    "office_location": [
        "অফিস কোথায়", "কোথায় অফিস", "অফিসের ঠিকানা",
        "ঠিকানা দেন", "হেড অফিস কই", "হেড অপিশ কই",
        "office address", "office location",
        "কোথায় যেতে হবে", "কোথায় আসতে হবে",
        "আগ্রপাড়া", "পাহাড়তলী", "ভিক্টোরিয়া গেইট", "victoria gate",
        "অফিসে আসব", "অফিসে যাব", "অফিসে যাবো",
    ],
}

# Regex-based triggers (higher priority)
REGEX_INTENTS: list[tuple[str, re.Pattern]] = [
    ("payment_due",     re.compile(r"^id\s*:", re.IGNORECASE)),
    ("escort_duty",     re.compile(r"^(mv|m/v)\s+\w", re.IGNORECASE)),
    ("client_order",    re.compile(r"(লোক\s*লাগবে|need\s*escort|escort\s*required)", re.IGNORECASE)),
    ("join",            re.compile(r"(যোগদান|joining\s*date|join\s*\w)", re.IGNORECASE)),
    ("payment_due",     re.compile(r"টাকা\s*(কবে|কখন|দেন|পাব)", re.IGNORECASE)),
    ("salary_query",    re.compile(r"(আমার\s*বেতন|বেতন\s*কত|কত\s*বেতন)", re.IGNORECASE)),
    ("office_location", re.compile(
        r"(অফিস\s*কোথায়|কোথায়\s*অফিস|হেড\s*অফিস\s*কই|হেড\s*অপিশ\s*কই"
        r"|office\s*address|office\s*location"
        r"|কোথায়\s*(যেতে|আসতে)\s*হবে|victoria\s*gate|ভিক্টোরিয়া\s*গেইট)",
        re.IGNORECASE,
    )),
]


def classify(text: str, threshold: int = 72) -> str:
    """
    Return the most likely intent for a message.
    1. Check regex patterns first (highest confidence)
    2. Direct substring keyword match (always beats fuzzy)
    3. Fuzzy match against keyword list
    4. Return 'unknown' — caller should use Ollama
    """
    if not text:
        return "unknown"

    text_lower = text.lower().strip()

    # 1. Regex rules
    for intent, pattern in REGEX_INTENTS:
        if pattern.search(text_lower):
            log.debug(f"intent={intent} via regex")
            return intent

    best_intent: Optional[str] = None
    best_score = 0
    best_is_direct = False

    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            kw_lower = kw.lower()
            # Direct substring — guaranteed win over any fuzzy match
            if kw_lower in text_lower:
                score = 10000 + len(kw_lower)
                if score > best_score or (score == best_score and not best_is_direct):
                    best_score = score
                    best_intent = intent
                    best_is_direct = True
                continue
            # Fuzzy: only considered if no direct match has been found yet
            if not best_is_direct:
                score = fuzz.partial_ratio(kw_lower, text_lower)
                if score >= threshold and score > best_score:
                    best_score = score
                    best_intent = intent

    if best_intent:
        log.debug(f"intent={best_intent} score={best_score} direct={best_is_direct}")
        return best_intent

    return "unknown"


def is_admin_command(text: str) -> bool:
    """Quick check if message looks like an admin command."""
    admin_patterns = [
        r"^id\s*:",
        r"^send to\s*:",
        r"^w/?a\s*no\.",
        r"^release\s+employee",
        r"^(mv|m/v)\s+\w",
    ]
    t = text.strip().lower()
    return any(re.match(p, t, re.IGNORECASE) for p in admin_patterns)
