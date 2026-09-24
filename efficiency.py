from __future__ import annotations

import re
from typing import Literal


TitleAction = Literal["reject", "review", "ambiguous"]


# These titles go directly to full-description review.
# Luna is unnecessary because we already know the function is relevant enough
# to inspect.
TARGET_TITLE_PATTERNS = (
    r"\bsolutions?\s+engineer\b",
    r"\bfield\s+applications?\s+engineer\b",
    r"\bfield\s+application\s+engineer\b",
    r"\bfield\s+engineer(?:ing)?\b",
    r"\bintegration\s+engineer\b",
    r"\bsystems?\s+integration\b",
    r"\bsales\s+engineer\b",
    r"\bcustomer\s+engineer\b",
    r"\bsolutions?\s+architect\b",
    r"\bfield\s+operations\b",
    r"\bdeployment\s+(?:engineer|manager|lead)\b",
    r"\btechnical\s+support\s+(?:manager|lead|director)\b",
    r"\bproduct\s+support\s+(?:manager|lead|director)\b",
    r"\btechnical\s+training\b",
)


# These are sufficiently clear to reject without Luna or Sol.
REJECT_TITLE_PATTERNS = (
    # User-specified engineering exclusions.
    r"^\s*(?:senior\s+|sr\.?\s+)?systems?\s+engineer\b",
    r"^\s*(?:senior\s+|sr\.?\s+)?(?:staff|principal)\s+engineer\b",
    r"\b(?:electrical|mechanical|materials?|chemical|civil|structural)\s+engineer\b",

    # Software / data.
    r"\b(?:software|firmware)\s+(?:engineer|developer)\b",
    r"\b(?:front[ -]?end|back[ -]?end|full[ -]?stack)\s+(?:engineer|developer)\b",
    r"\b(?:ios|android|mobile)\s+(?:engineer|developer)\b",
    r"\bdata\s+(?:scientist|engineer)\b",
    r"\bmachine\s+learning\s+engineer\b",

    # Test-centric roles.
    r"\bsystems?\s+test\s+engineer\b",
    r"\btest\s+automation\b",
    r"\bautomation\s+test\s+engineer\b",
    r"\bverification\s+engineer\b",
    r"\bvalidation\s+engineer\b",
    r"\bsdet\b",

    # Clearly unrelated professional families.
    r"\baccount(?:ant|ing)\b",
    r"\bbookkeep(?:er|ing)\b",
    r"\bpayroll\b",
    r"\brecruiter\b",
    r"\btalent\s+acquisition\b",
    r"\bhuman\s+resources\b",
    r"\battorney\b",
    r"\blegal\s+counsel\b",
    r"\bparalegal\b",
    r"\bnurs(?:e|ing)\b",
    r"\bphysician\b",
    r"\bsurgeon\b",

    # Clearly inappropriate level.
    r"\bintern(?:ship)?\b",
)


def classify_title(title: str) -> TitleAction:
    """
    $0 deterministic title classification.

    Order matters:
      1. Explicit target functions win.
      2. Explicit exclusions reject.
      3. Everything else is ambiguous and can go to Luna.
    """
    title = (title or "").strip()

    if not title:
        return "ambiguous"

    for pattern in TARGET_TITLE_PATTERNS:
        if re.search(pattern, title, flags=re.I):
            return "review"

    for pattern in REJECT_TITLE_PATTERNS:
        if re.search(pattern, title, flags=re.I):
            return "reject"

    return "ambiguous"


def parse_annual_base_max_usd(text: str) -> float | None:
    """
    Conservatively extracts an annual USD base maximum.

    Returns None for hourly pay, OTE-only compensation, non-USD compensation,
    or wording that is too ambiguous to use as a hard filter.
    """
    if not text:
        return None

    value = " ".join(str(text).split())

    # Do not turn hourly compensation into annual salary.
    if re.search(r"(?:/hour|/hr|per hour|hourly)", value, re.I):
        return None

    # Avoid interpreting OTE as base salary.
    if re.search(r"\bOTE\b", value, re.I) and not re.search(
        r"\bbase\b", value, re.I
    ):
        return None

    # Reject clearly non-USD ranges.
    if re.search(r"\b(?:EUR|GBP|CAD|AUD)\b|[€£]", value, re.I):
        return None

    # $120,000 - $165,000
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

    if not parsed:
        return None

    return max(parsed)


BOILERPLATE_START_PATTERNS = (
    r"^\s*equal employment opportunity\b",
    r"^\s*equal opportunity employer\b",
    r"^\s*eeo\b",
    r"^\s*reasonable accommodation\b",
    r"^\s*accommodation statement\b",
    r"^\s*agency disclaimer\b",
    r"^\s*staffing agencies\b",
    r"^\s*privacy notice\b",
)


def strip_job_boilerplate(description: str) -> str:
    """
    Conservatively removes only obvious trailing corporate/legal boilerplate.

    It intentionally does NOT strip compensation, clearance, travel,
    responsibilities, qualifications, or benefits unless they occur after an
    unmistakable boilerplate heading.
    """
    if not description:
        return ""

    lines = description.splitlines()
    output: list[str] = []

    for line in lines:
        normalized = line.strip()

        if any(
            re.search(pattern, normalized, re.I)
            for pattern in BOILERPLATE_START_PATTERNS
        ):
            break

        output.append(line)

    return "\n".join(output).strip()
