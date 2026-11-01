"""Conservative job preferences. Unknown evidence always goes to review."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .core import plain_text
from .efficiency import classify_title, load_title_review_list, parse_annual_base_max_usd


@dataclass(frozen=True)
class Screening:
    reason: str | None
    review_note: str


def _sentences(text):
    # Compensation statements commonly format a range as
    # "$75,650.00/Yr. - $126,050.00/Yr.".  The period after the first unit is
    # an abbreviation, not a sentence boundary; splitting there hides the
    # maximum from the conservative salary parser.
    text = re.sub(
        r"(/(?:yr|year|hr|hour|mo|month|wk|week))\.(?=\s*[-\u2013\u2014])",
        r"\1",
        text,
        flags=re.I,
    )
    return re.split(r"(?<=[.!?;])\s+|\n+", text)


def _employment_exclusion(title, description):
    temporary = r"(?:temporary|temp|seasonal|internship|fixed[- ]term|contract[- ]to[- ]hire)"
    kind = rf"(?:{temporary}|contract(?:or)?)"
    prefix = re.match(rf"^{kind}\s+(.+)", title, re.I)
    qualified_title = prefix and any(pattern.match(prefix.group(1)) for pattern in load_title_review_list())
    if qualified_title or re.search(rf"[(/,:\-]\s*{kind}\s*[)]?$|\b(?:internship|fixed[- ]term|contract[- ]to[- ]hire)\b", title, re.I):
        return "Employment exclusion: title explicitly identifies a nonpermanent role."
    pattern = (
        rf"\b(?:employment|job|position|contract)\s+type\s*:\s*{kind}\b|"
        rf"\bthis is (?:a|an) {kind} (?:role|position|job)\b|"
        rf"\b(?:this|the) (?:role|position|job) is (?:a |an )?(?:\d+[- ]month )?{kind}"
        r"(?=\s*(?:[.!?;,]|$)|\s+(?:role|position|job|assignment|employment|opportunity)\b)"
    )
    for sentence in _sentences(description):
        if re.search(pattern, sentence, re.I):
            return "Employment exclusion: posting explicitly specifies temporary or contract employment."
    return None


def _travel_exclusion(description):
    number = r"\d{1,3}(?:\.\d+)?"
    percentage = rf"({number})\s*%?(?:\s*[-\u2013\u2014]\s*|\s+to\s+)({number})\s*%|({number})\s*%"
    for sentence in _sentences(description):
        if not re.search(r"\btravel\b", sentence, re.I):
            continue
        sentence = re.sub(r"\b(?:no more than|not (?:to )?exceed)\b", "up to", sentence, flags=re.I)
        # Negation and alternatives need human interpretation.
        if re.search(r"\b(?:not|no|less than|optional|preferred|historically|previously)\b", sentence, re.I):
            continue
        for match in re.finditer(percentage, sentence):
            before, after = sentence[:match.start()], sentence[match.end():]
            # Connect the percentage to travel, not an unrelated bonus/time split.
            travel_before = re.search(
                r"\btravel\b(?:\s|:|,|\(|-)*(?:(?:is|required|expected|requirement|requirements|of|up to|approximately|around|about|more than|greater than|over|at least|domestic|international|and)\s+)*$",
                before, re.I,
            )
            travel_after = re.match(r"\s*(?:of (?:the |your )?time\s+)?(?:domestic\s+|international\s+)?travel\b", after, re.I)
            if not (travel_before or travel_after):
                continue
            maximum = float(match.group(2) or match.group(3))
            if 50 < maximum <= 100 or (maximum == 50 and re.search(r"\b(?:more than|over|greater than)\s*$", before, re.I)):
                return f"Travel exclusion: posting specifies travel above 50% ({match.group(0)})."
    return None


def _saas_exclusion(description):
    saas = r"(?:SaaS|software[- ]as[- ]a[- ]service)"
    # Require a direct product/responsibility statement. Tool use, experience,
    # integrations, and general company boilerplate are not enough.
    patterns = (
        rf"\b(?:you will|you'll|this role will|this position will)\s+(?:own|manage|lead|sell|market|support)\s+(?:(?:our|the|a|an)\s+)?{saas}\s+(?:product|platform|solution|offering)\b",
        rf"\b(?:own|manage|lead)\s+(?:the\s+)?(?:product\s+)?roadmap\s+for\s+(?:(?:our|the|a|an)\s+)?{saas}\b",
        rf"\b(?:this|the) (?:role|position) (?:is focused on|focuses on)\s+{saas}\b",
    )
    for sentence in _sentences(description):
        if re.search(r"\b(?:not|no|rather than)\b", sentence, re.I):
            continue
        if any(re.search(pattern, sentence, re.I) for pattern in patterns):
            return "Product exclusion: responsibilities explicitly focus on a SaaS product."
    return None


def screen_posting(posting, *, skip_title_filter=False):
    title = str(posting.get("title") or "")
    description = plain_text(posting.get("description", ""))
    title_action = classify_title(title)
    if title_action == "reject" and not skip_title_filter:
        return Screening("Title exclusion: matches title-blacklist.txt.", "")
    note = (
        "Preferred title shortlist match; still requires AI review."
        if title_action == "review" else
        "Title outside the preferred shortlist; retained for AI review of transferable fit."
    )
    note += " Prefer hardware or mixed products; verify permanent employment, travel <=50%, and annual base >=$120,000."
    reason = _employment_exclusion(title, description) or _travel_exclusion(description) or _saas_exclusion(description)
    if reason:
        return Screening(reason, note)

    compensation = plain_text(posting.get("compensation", ""))
    # Salary sections often live only in the description. Never parse arbitrary
    # dollar figures such as product prices as salary evidence.
    salary_parts = [sentence for sentence in _sentences(description)
                    if re.search(r"\b(?:base (?:salary|pay)|annual (?:salary|base)|salary range)\b", sentence, re.I)]
    sources = [part for part in [compensation, *salary_parts] if part.strip()]
    if any(re.search(r"\bbase\b", part, re.I) for part in sources):
        sources = [part for part in sources if re.search(r"\bbase\b", part, re.I)
                   or not re.search(r"\b(?:OTE|on[- ]target earnings|total compensation|bonus|commission|equity)\b", part, re.I)]
    salaries = [parse_annual_base_max_usd(part) for part in sources]
    known = [salary for salary in salaries if salary is not None]
    # An unparseable advertised pay component can describe another region or
    # currency. Keep that uncertainty instead of assuming a global pay ceiling.
    if known and len(known) == len(sources) and max(known) < 120_000:
        return Screening(f"Compensation exclusion: stated maximum annual base is ${max(known):,.0f}, below the $120,000 floor.", note)
    return Screening(None, note)
