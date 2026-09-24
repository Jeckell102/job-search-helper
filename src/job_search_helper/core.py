"""Pure functions. No network, model calls, or spreadsheet side effects."""
from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import zlib
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .efficiency import classify_title

POLICY_VERSION = "2026-09-17-v2"
TITLE_FILTER_VERSION = "2026-09-23-v4"
FIT_LABELS = {"Strong": "Strong Potential Fit", "Possible": "Potential Fit", "Stretch": "Potential Fit"}
TRACKING = {"gh_src", "lever-source", "lever-via", "fbclid", "gclid"}


def canonicalize_url(url: str) -> str:
    """Remove only known tracking parameters; NEVER discard gh_jid/job IDs."""
    if not url or not str(url).strip():
        return ""
    parts = urlsplit(str(url).strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Expected an ordinary public HTTP(S) job URL")
    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                   if not k.lower().startswith("utm_") and k.lower() not in TRACKING)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(query), ""))


def job_key(company_id: str, ats: str, posting_id: str, url: str) -> str:
    if not company_id.strip():
        raise ValueError("A stable Company ID is required")
    identifier = str(posting_id or "").strip()
    if not identifier:
        canonical = canonicalize_url(url)
        if not canonical:
            raise ValueError("A posting requires an ID or official URL")
        identifier = "url-" + hashlib.sha256(canonical.encode()).hexdigest()
    return f"{company_id.strip().lower()}:{ats.strip().lower()}:{identifier}"


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored += 1
        if tag in {"p", "br", "li", "div", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.ignored:
            self.ignored -= 1
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def plain_text(value: str) -> str:
    # Greenhouse sometimes HTML-escapes the content returned by its API.
    parser = _Text()
    parser.feed(html.unescape(str(value or "")))
    parser.close()  # JSH_AMPERSAND_FIX: flush buffered trailing entity text
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def material_hash(posting: dict) -> str:
    fields = {key: plain_text(posting.get(key, "")).casefold()
              for key in ("title", "location", "work_arrangement", "compensation", "description")}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def changed_fields(old: dict | None, new: dict) -> list[str]:
    if not old:
        return ["Initial evidence baseline"]
    return [key for key in ("title", "location", "work_arrangement", "compensation", "description")
            if plain_text(old.get(key, "")).casefold() != plain_text(new.get(key, "")).casefold()]


def excluded_title(title: str) -> bool:
    """Use the same user-maintained exclusions as scraping and cleanup."""
    return classify_title(title) == "reject"


def reconsiderations(row: dict | None) -> int:
    value = (row or {}).get("Reconsideration Count", "")
    if value in ("", None):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid reconsideration count; repair it explicitly, do not reset it") from exc
    if str(value).strip() not in {str(number), str(float(number))} or number < 0:
        raise ValueError("Invalid reconsideration count")
    return number


def pack_snapshot(value: dict) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if len(payload) > 2_000_000:
        raise ValueError("Snapshot evidence exceeds the supported uncompressed size")
    packed = "JSH1:" + base64.b64encode(zlib.compress(payload, 9)).decode()
    if len(packed) > 45000:
        raise ValueError("Snapshot exceeds safe Sheets cell size; retained locally, manual review required")
    return packed


def unpack_snapshot(value: str) -> dict:
    if not value:
        return {"v": 1, "evaluated": None, "pending": None, "evaluations": []}
    if not isinstance(value, str) or not value.startswith("JSH1:"):
        raise ValueError("Unknown Current Snapshot format; refusing to overwrite prior evidence")
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(base64.b64decode(value[5:], validate=True), 2_000_001)
        if len(raw) > 2_000_000 or decoder.unconsumed_tail or not decoder.eof:
            raise ValueError("Invalid or excessive snapshot")
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get("v") != 1 or not isinstance(result.get("evaluations"), list):
            raise ValueError("Unsupported snapshot version")
        if any(result.get(k) is not None and not isinstance(result.get(k), dict) for k in ("evaluated", "pending")):
            raise ValueError("Invalid snapshot posting")
        if any(not isinstance(item, dict) for item in result["evaluations"]):
            raise ValueError("Invalid snapshot evaluations")
        return result
    except (ValueError, TypeError, KeyError, zlib.error) as exc:
        raise ValueError("Invalid Current Snapshot; refusing to discard evidence") from exc


def validate_decision(decision: dict, pending: dict, old_snapshot: dict) -> None:
    for field in ("job_key", "description_hash", "decision", "narrative", "reviewer", "policy_version"):
        if not isinstance(decision.get(field), str) or not decision[field].strip():
            raise ValueError(f"Decision requires nonempty {field}")
    if decision["policy_version"] != POLICY_VERSION:
        raise ValueError("Review policy version does not match this helper")
    if decision["description_hash"] != material_hash(pending):
        raise ValueError("Stale assessment: description hash no longer matches")
    if decision["decision"] not in {"accept", "reject", "needs_info"}:
        raise ValueError("Decision must be accept, reject, or needs_info")
    title_only_reject = decision.get("evaluation_stage") == "title_screen" and decision["decision"] == "reject"
    if not plain_text(pending.get("description", "")) and decision["decision"] != "needs_info" and not title_only_reject:
        raise ValueError("Cannot complete a fit assessment without the job description")
    if old_snapshot.get("evaluated") and material_hash(old_snapshot["evaluated"]) != material_hash(pending):
        if type(decision.get("material_change")) is not bool:
            raise ValueError("A changed baseline needs an explicit material_change boolean")
    if decision["decision"] == "accept":
        if decision.get("fit_level") not in FIT_LABELS:
            raise ValueError("Accepted roles require Strong, Possible, or Stretch")
    salary = decision.get("base_max_usd")
    if salary is not None:
        if type(salary) not in (int, float) or not 0 < salary < 10_000_000:
            raise ValueError("base_max_usd must be a plausible annual USD base maximum or null")
        if salary < 120000 and decision["decision"] == "accept":
            raise ValueError("Known maximum annual base below $120,000 is a hard exclusion")
    if len(decision["narrative"]) > 12000:
        raise ValueError("Narrative exceeds the supported evidence size")
