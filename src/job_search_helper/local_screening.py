"""Deterministic screening of saved evidence, independent of scan selection."""
from __future__ import annotations

import re
import unicodedata

from .compensation import parse_annual_base_max_usd
from .policy import Policy


EVALUATOR_VERSION = "local-screen-v1"
RESULT_LABELS = {"not_evaluated": "Not Evaluated", "excluded": "Excluded by Profile",
                 "needs_review": "Needs Review", "no_exclusion": "No Exclusion Found"}


def _title_words(text):
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold()))


def annual_base_max(text: str) -> float | None:
    # Gate the shared legacy amount parser with explicit units and a closed
    # grammar. Ambiguous currencies, components and open-ended pay stay unknown.
    text = " ".join(unicodedata.normalize("NFKC", text).split()).replace("\u2013", "-").replace("\u2014", "-")
    number = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*[kK]?"
    money = rf"(?:USD\s*\$?\s*|\$\s*)?({number})"
    amount = rf"{money}(?:\s*(?:-|to)\s*{money})?"
    label = r"(?:annual\s+|yearly\s+)?base\s+(?:salary|pay)(?:\s+range)?"
    period = r"(?:annually|annual|yearly|per\s+year|/yr|/year)"
    match = re.fullmatch(rf"(?:{label}\s*:?\s*)?{amount}\s*(?:(?:{period}\s*)?(?:{label})?|{period})\.?", text, re.I)
    if not match or not re.search(r"\bUSD\b", text, re.I) or not re.search(r"\bbase\b", text, re.I):
        return None
    if not re.search(r"\b(?:annual|annually|yearly|year)\b|/yr\b", text, re.I):
        return None
    values = [float(value.strip().rstrip("kK").replace(",", "")) * (1000 if value.strip().lower().endswith("k") else 1)
              for value in match.groups() if value is not None]
    if any(value < 10_000 or value > 10_000_000 for value in values) or (len(values) == 2 and values[0] > values[1]):
        return None
    parsed = parse_annual_base_max_usd(text)
    return parsed if parsed == max(values) else None


def evaluate(evidence: dict, policy: Policy) -> dict:
    if not policy.enabled:
        return {"result": "not_evaluated", "reason": "No screening rules configured.", "evidence": []}
    rules, checks = policy.rules, []

    def record(rule, outcome, field, value, reason):
        checks.append({"rule_id": rule, "outcome": outcome, "field": field, "value": value, "reason": reason})

    title = evidence.get("title") or ""
    words = " " + _title_words(title) + " "
    for key in ("exclude", "prefer"):
        phrases = rules["titles"][key]
        if not phrases:
            continue
        matches = [phrase for phrase in phrases if " " + phrase + " " in words]
        if not words.strip():
            outcome, reason = "unknown", "Title is missing or contains no usable words."
        elif key == "exclude":
            outcome = "fail" if matches else "pass"
            reason = "Excluded title phrase: " + ", ".join(matches) if matches else "No excluded title phrase matched."
        else:
            outcome = "hint" if matches else "unknown"
            reason = "Preferred title phrase: " + ", ".join(matches) if matches else "Outside the preferred title list; review transferable fit."
        record("titles." + key, outcome, "title", title, reason)
    allowed = rules["locations"]["work_arrangements"]
    if allowed:
        raw = evidence.get("work_arrangement") or ""
        arrangement = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite", "on-site": "onsite", "on site": "onsite"}.get(raw.strip().casefold())
        if arrangement is None:
            outcome, reason = "unknown", "Work arrangement is missing or ambiguous; location text is not proof."
        elif arrangement in allowed:
            outcome, reason = "pass", "Work arrangement matches the profile."
        else:
            outcome, reason = "fail", "Work arrangement is outside the profile's allowed values."
        record("locations.work_arrangements", outcome, "work_arrangement", raw, reason)
    if rules["salary"]:
        raw = evidence.get("compensation_text") or ""
        maximum = annual_base_max(raw)
        minimum = rules["salary"]["minimum"]
        if maximum is None:
            outcome, reason = "unknown", "Annual USD base-pay maximum is not explicit or supported; review the saved compensation and description."
        elif maximum < minimum:
            outcome, reason = "fail", f"Stated annual USD base maximum {maximum:,.2f} is below profile minimum {minimum:,.2f}."
        else:
            outcome, reason = "pass", f"Stated annual USD base maximum {maximum:,.2f} reaches profile minimum {minimum:,.2f}; this is not a guaranteed offer."
        record("salary.minimum", outcome, "compensation_text", raw, reason)
    outcomes = {check["outcome"] for check in checks}
    result = "excluded" if "fail" in outcomes else "needs_review" if "unknown" in outcomes else "no_exclusion"
    return {"result": result, "reason": " ".join(check["reason"] for check in checks), "evidence": checks}
