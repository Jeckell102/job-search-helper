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
    if re.search(r"(?:/hour|/hr|per\s+hour|hourly)", value, re.I):
        return None
    if re.search(r"\bOTE\b", value, re.I) and not re.search(r"\bbase\b", value, re.I):
        return None
    if re.search(r"\b(?:EUR|GBP|CAD|AUD)\b|[€£]", value, re.I):
        return None

    amounts = re.findall(
        r"\$\s*([0-9]{2,3}(?:,[0-9]{3})+|[0-9]{2,3}(?:\.\d+)?\s*[kK])",
        value,
    )
    parsed: list[float] = []
    for amount in amounts:
        cleaned = amount.replace(",", "").strip()
        if cleaned.lower().endswith("k"):
            parsed.append(float(cleaned[:-1]) * 1000)
        else:
            parsed.append(float(cleaned))
    return max(parsed) if parsed else None


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
