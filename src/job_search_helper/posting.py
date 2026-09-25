"""Stable posting identities and text fingerprints, independent of screening policy."""
from __future__ import annotations

import hashlib
import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
