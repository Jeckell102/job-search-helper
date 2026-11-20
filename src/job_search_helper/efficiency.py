"""Cheap deterministic screening and prompt-size reduction helpers."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

TitleAction = Literal["reject", "review", "ambiguous"]

# The user-maintained file is loaded once per process; restart after editing.
BLACKLIST_PATH = Path(__file__).resolve().parents[2] / "title-blacklist.txt"
REVIEW_LIST_PATH = BLACKLIST_PATH.with_name("title-review-list.txt")


@lru_cache(maxsize=1)
def load_title_blacklist():
    return _load_title_patterns(BLACKLIST_PATH)


@lru_cache(maxsize=1)
def load_title_review_list():
    return _load_title_patterns(REVIEW_LIST_PATH)


def _load_title_patterns(path):
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise ValueError(f"Cannot read title list: {path}. Restore it before starting.") from exc
    patterns = []
    for number, line in enumerate(lines, 1):
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.startswith("regex:"):
            pattern = entry[len("regex:"):].strip()
            if not pattern:
                raise ValueError(f"Empty regex in {path.name}, line {number}.")
        else:
            words = re.findall(r"[^\W_]+", entry, re.UNICODE)
            if not words:
                raise ValueError(f"No words in {path.name}, line {number}.")
            pattern = r"(?<!\w)" + r"[\W_]+".join(re.escape(word) for word in words) + r"(?!\w)"
        try:
            patterns.append(re.compile(pattern, re.I))
        except re.error as exc:
            raise ValueError(f"Invalid regex in {path.name}, line {number}: {exc}") from exc
    return tuple(patterns)


def classify_title(title: str) -> TitleAction:
    """Return a zero-model action for a job title."""
    value = (title or "").strip()
    if not value:
        return "ambiguous"
    if any(pattern.search(value) for pattern in load_title_blacklist()):
        return "reject"
    if any(pattern.search(value) for pattern in load_title_review_list()):
        return "review"
    return "ambiguous"


def parse_annual_base_max_usd(text: str) -> float | None:
    """Conservatively extract a maximum annual USD base salary.

    Hourly, OTE-only, non-USD, or unclear compensation returns None so the model
    can reason about it instead of Python inventing a comparable base figure.
    """
    if not text:
        return None
    value = " ".join(str(text).split())
    if re.search(r"(?:/hour|/hr|per\s+(?:hour|month|week)|hourly|monthly|weekly)", value, re.I):
        return None
    if re.search(r"\b(?:EUR|GBP|CAD|AUD|NZD|SGD|HKD|INR|JPY|CHF)\b|[€£]|\b(?:C|A|NZ|S|HK)\$", value, re.I):
        return None
    # Split pay components before reading amounts: OTE and bonus cannot raise
    # an explicitly lower base salary above the user's floor.
    other_pay = r"\b(?:OTE|on[- ]target earnings|total (?:compensation|rewards|cash)|bonus|commission|equity|stock|incentive)\b"
    if re.search(other_pay, value, re.I) and re.search(r"\b(?:combined|including|inclusive|consists|comprised)\b", value, re.I):
        return None
    parts = re.split(r"[;\n]|\s*\+\s*|\bplus\b|\band\b|,(?!\d)|(?<=[.!?])\s+", value, flags=re.I)
    base_parts = [part for part in parts if re.search(r"\bbase(?:\s+(?:salary|pay))?\b", part, re.I)]
    if not base_parts and re.search(other_pay, value, re.I):
        return None
    number = r"(?:\d{2,3}(?:,\d{3})+(?:\.\d+)?|\d{5,7}(?:\.\d+)?|\d{2,3}(?:\.\d+)?\s*[kK])"
    amount = rf"(?:USD\s*\$?\s*|\$\s*)?({number})"
    amounts = []
    for part in parts:
        # A component containing both base and another pay label is ambiguous.
        if re.search(other_pay, part, re.I):
            if re.search(r"\bbase\b", part, re.I):
                return None
            continue
        # Ranges for additional locations can inherit the base/currency label.
        if not re.search(r"\bUSD\b|\$", value, re.I):
            continue
        for match in re.finditer(amount, part):
            cleaned = match.group(1).replace(",", "").strip()
            amounts.append(float(cleaned[:-1]) * 1000 if cleaned.lower().endswith("k") else float(cleaned))
    return max(amounts) if amounts else None


def parse_hourly_base_max_usd(text: str) -> float | None:
    """Highest advertised USD hourly base, including starting rates.

    The caller annualizes at 2,080 hours/year. Keep unclear units, currencies,
    combined compensation and unrelated dollar amounts for individual review.
    """
    value = " ".join(str(text or "").split())
    unit = r"(?:/\s*(?:hours?|hrs?)\b|per\s+hour\b|an?\s+hour\b)"
    if not re.search(unit + r"|\bhourly\b", value, re.I):
        return None
    if re.search(r"\b(?:EUR|GBP|CAD|AUD|NZD|SGD|HKD|INR|JPY|CHF)\b|[€£]|\b(?:C|A|NZ|S|HK)\$", value, re.I):
        return None
    other = r"\b(?:OTE|on[- ]target earnings|total (?:compensation|rewards|cash)|bonus|commission|equity|stock|incentive|overtime|reimbursement)\b"
    if re.search(other, value, re.I):
        return None
    if re.search(r"/(?:year|yr|month|mo|week|wk)|per\s+(?:year|month|week)|\b(?:annual|annually|monthly|weekly)\b", value, re.I):
        return None
    number = r"\d{1,3}(?:\.\d{1,2})?"
    money = rf"(?:USD\s*\$?\s*|\$\s*)({number})(?![\d,]|\.\d)"
    range_pattern = rf"{money}\s*(?:{unit})?\s*(?:[-–—]|to)\s*(?:USD\s*\$?\s*|\$\s*)?({number})(?![\d,]|\.\d)\s*{unit}"
    single_pattern = rf"{money}\s*{unit}"
    amounts, spans = [], []
    for pattern in (range_pattern, single_pattern):
        for match in re.finditer(pattern, value, re.I):
            if any(start <= match.start() < end for start, end in spans):
                continue
            amounts.extend(float(n) for n in match.groups())
            spans.append(match.span())
    # Also accept clearly labeled compensation fields such as Hourly base: $32-$34.
    if not spans and re.search(r"\bhourly\s+(?:base\s+)?(?:pay|rate|salary|wage|base)\b", value, re.I):
        labeled = rf"{money}(?:\s*(?:[-–—]|to)\s*(?:USD\s*\$?\s*|\$\s*)?({number})(?![\d,]|\.\d))?"
        for match in re.finditer(labeled, value, re.I):
            amounts.extend(float(n) for n in match.groups() if n)
            spans.append(match.span())
    # A separate dollar amount might be another base-pay option or another unit.
    remainder = value
    for start, end in sorted(spans, reverse=True):
        remainder = remainder[:start] + " " + remainder[end:]
    if re.search(r"\$|\bUSD\s*\d", remainder, re.I):
        return None
    return max(amounts) if amounts and all(n > 0 for n in amounts) else None


# Only unmistakable trailing legal/corporate boilerplate is removed. The
# responsibilities, qualifications, clearance, travel, benefits, location and
# compensation sections remain available to the reviewer.
BOILERPLATE_START_PATTERNS = (
    r"^equal employment opportunity(?: employer)?\b",
    r"^equal opportunity employer\b",
    r"^eeo(?: statement)?\b",
    r"^reasonable accommodation(?:s)?\b",
    r"^accommodation statement\b",
    r"^agency disclaimer\b",
    r"^staffing agencies\b",
    r"^privacy notice\b",
)


def strip_job_boilerplate(description: str) -> str:
    """Remove only obvious trailing EEO/privacy/agency boilerplate."""
    if not description:
        return ""
    lines = str(description).splitlines()
    output: list[str] = []
    for line in lines:
        normalized = line.strip()
        if any(re.search(pattern, normalized, re.I) for pattern in BOILERPLATE_START_PATTERNS):
            break
        output.append(line)
    cleaned = "\n".join(output).strip()
    return cleaned or str(description).strip()
