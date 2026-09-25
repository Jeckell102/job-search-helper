"""Conservative salary evidence parsing without personal thresholds."""
from __future__ import annotations

import re


def parse_annual_base_max_usd(text: str) -> float | None:
    """Conservatively extract a maximum annual USD base salary.

    Hourly, OTE-only, non-USD, or unclear compensation returns None so callers
    can preserve uncertainty instead of inventing a comparable base figure.
    """
    if not text:
        return None
    value = " ".join(str(text).split())
    if re.search(r"(?:/hour|/hr|per\s+(?:hour|month|week)|hourly|monthly|weekly)", value, re.I):
        return None
    if re.search(r"\b(?:EUR|GBP|CAD|AUD|NZD|SGD|HKD|INR|JPY|CHF)\b|[€£]|\b(?:C|A|NZ|S|HK)\$", value, re.I):
        return None
    # Split pay components so OTE and bonuses cannot inflate the base amount.
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
