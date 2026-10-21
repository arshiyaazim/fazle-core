"""
Fazle Core — Shared date-range parser (Phase 1.2 / v1.1.0)

Lightweight, no external deps beyond stdlib. Bangla + English + Banglish.

API:
    parse_date_range(text, *, default_days=None) -> (start_dt, end_dt, label) | None

All datetimes are TZ-AWARE in Asia/Dhaka (+06:00) — that's the local business TZ.
End is EXCLUSIVE (e.g. "today" → start=today 00:00, end=tomorrow 00:00).

Recognises (case-insensitive):
    today, yesterday, this week, last week, this month, last month, this year
    last N days / N day(s) ago / past N days / গত N দিন / N দিনে
    last N weeks / months
    month names: jan..dec, january..december, jan 2026
    Bangla months: জানুয়ারি..ডিসেম্বর
    YYYY-MM-DD..YYYY-MM-DD   (ISO range)
    YYYY-MM-DD                (single day)
    এই সপ্তাহে, গত সপ্তাহে, এই মাসে, গত মাসে, এ মাসে
    আজ, গতকাল, পরশু

Returns None if no recognisable token found AND default_days is None.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone, date

# Asia/Dhaka — fixed offset (no DST in BD)
BD_TZ = timezone(timedelta(hours=6), name="Asia/Dhaka")

_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

_EN_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_BN_MONTHS = {
    "জানুয়ারি": 1, "ফেব্রুয়ারি": 2, "মার্চ": 3, "এপ্রিল": 4,
    "মে": 5, "জুন": 6, "জুলাই": 7, "আগস্ট": 8,
    "সেপ্টেম্বর": 9, "অক্টোবর": 10, "নভেম্বর": 11, "ডিসেম্বর": 12,
}


def _now() -> datetime:
    return datetime.now(BD_TZ)


def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_week(dt: datetime) -> datetime:
    """Week starts Saturday in BD (banking convention). Use Saturday 00:00."""
    # weekday(): Mon=0..Sun=6. Saturday=5.
    days_since_sat = (dt.weekday() - 5) % 7
    return _start_of_day(dt - timedelta(days=days_since_sat))


def _start_of_month(dt: datetime) -> datetime:
    return _start_of_day(dt.replace(day=1))


def _add_months(dt: datetime, n: int) -> datetime:
    m = dt.month - 1 + n
    y = dt.year + m // 12
    m = m % 12 + 1
    return dt.replace(year=y, month=m, day=1, hour=0, minute=0, second=0, microsecond=0)


# ── Pattern set (most specific first) ─────────────────────────────────────────
# ISO range: 2026-04-01..2026-04-15  or  2026-04-01 to 2026-04-15
_ISO_RANGE_RE = re.compile(
    r"\b(\d{4}-\d{1,2}-\d{1,2})\s*(?:\.\.|to|-)\s*(\d{4}-\d{1,2}-\d{1,2})\b"
)
_ISO_SINGLE_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")

# last N days / past N days / গত N দিন
_LAST_N_RE = re.compile(
    r"(?:\b(?:last|past|recent)\s+|গত\s+)?(\d{1,3})\s*(day|days|দিন|দিনের|সপ্তাহ|week|weeks|month|months|মাস)\b",
    re.IGNORECASE,
)


def _parse_iso(s: str) -> datetime | None:
    try:
        d = date.fromisoformat(s)
        return datetime(d.year, d.month, d.day, tzinfo=BD_TZ)
    except Exception:
        return None


def parse_date_range(text: str, *, default_days: int | None = None
                     ) -> tuple[datetime, datetime, str] | None:
    """
    Parse a date range from natural-language text.

    Returns (start_dt, end_dt_exclusive, label) or None if no token found and
    default_days is None.
    """
    t = text.translate(_BN_DIGITS).strip()
    tl = t.lower()
    now = _now()
    today_start = _start_of_day(now)
    tomorrow_start = today_start + timedelta(days=1)

    # 1) ISO range: 2026-04-01..2026-04-15
    m = _ISO_RANGE_RE.search(t)
    if m:
        a = _parse_iso(m.group(1))
        b = _parse_iso(m.group(2))
        if a and b:
            if b < a:
                a, b = b, a
            return a, b + timedelta(days=1), f"{m.group(1)} → {m.group(2)}"

    # 2) Single ISO date
    m = _ISO_SINGLE_RE.search(t)
    if m:
        a = _parse_iso(f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}")
        if a:
            return a, a + timedelta(days=1), a.strftime("%Y-%m-%d")

    # 3) Keywords
    if re.search(r"\bto[-\s]?day\b|আজ(?!কে)|আজকের", tl):
        return today_start, tomorrow_start, "today"
    if re.search(r"\byesterday\b|গতকাল|গতকালের", tl):
        return today_start - timedelta(days=1), today_start, "yesterday"
    if re.search(r"\b(?:day before yesterday|পরশু)\b", tl):
        return today_start - timedelta(days=2), today_start - timedelta(days=1), "day before yesterday"
    if re.search(r"\bthis\s+week\b|এই\s*সপ্তাহ", tl):
        s = _start_of_week(now)
        return s, s + timedelta(days=7), "this week"
    if re.search(r"\blast\s+week\b|গত\s*সপ্তাহ|গতো?\s*সপ্তাহ", tl):
        s = _start_of_week(now) - timedelta(days=7)
        return s, s + timedelta(days=7), "last week"
    if re.search(r"\bthis\s+month\b|এই\s*মাস|এ\s*মাস", tl):
        s = _start_of_month(now)
        return s, _add_months(s, 1), "this month"
    if re.search(r"\blast\s+month\b|গত\s*মাস", tl):
        s = _add_months(_start_of_month(now), -1)
        return s, _start_of_month(now), "last month"
    if re.search(r"\bthis\s+year\b|এই\s*বছর", tl):
        s = today_start.replace(month=1, day=1)
        return s, s.replace(year=s.year + 1), "this year"

    # 4) "last N days/weeks/months" / "গত N দিন/সপ্তাহ/মাস"
    m = _LAST_N_RE.search(t)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit in ("day", "days", "দিন", "দিনের"):
            return today_start - timedelta(days=n), tomorrow_start, f"last {n} days"
        if unit in ("week", "weeks", "সপ্তাহ"):
            return today_start - timedelta(days=7 * n), tomorrow_start, f"last {n} weeks"
        if unit in ("month", "months", "মাস"):
            s = _add_months(today_start, -n)
            return s, tomorrow_start, f"last {n} months"

    # 5) Month name (optionally with year): "march", "march 2026", "মার্চ"
    for name, mo in {**_EN_MONTHS, **_BN_MONTHS}.items():
        if re.search(rf"\b{re.escape(name)}\b", tl if name.isascii() else t):
            # optional year
            year = now.year
            ym = re.search(r"\b(20\d{2})\b", t)
            if ym:
                year = int(ym.group(1))
            s = datetime(year, mo, 1, tzinfo=BD_TZ)
            e = _add_months(s, 1)
            return s, e, f"{s.strftime('%B %Y')}"

    # 6) default
    if default_days is not None:
        return (today_start - timedelta(days=default_days), tomorrow_start,
                f"last {default_days} days")
    return None
