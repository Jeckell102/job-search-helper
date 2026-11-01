"""Southwest Antennas' first-party Laravel/Inertia careers inventory."""
from __future__ import annotations

import json
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://southwestantennas.com/careers-southwest-antennas"
HOST = "southwestantennas.com"
CAREER_PREFIX = "/career/"
ATS = "Southwest Antennas careers"
COMPANY_ID = "COMP-0492"
COMPANY = "Southwest Antennas"


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.data_page = ""
        self.parts = []
        self._app = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div" and attrs.get("id") == "app":
            self.data_page = attrs.get("data-page", "")
            self._app = True

    def handle_data(self, data):
        self.parts.append(data)


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path.rstrip("/") == "/careers-southwest-antennas"
                and not parsed.query and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _read(client, url):
    response = client.get(url)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"Southwest Antennas careers page blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"Southwest Antennas careers page HTTP {response.status}.")
    if not response.body.strip():
        raise FetchError("partial", "Southwest Antennas careers page was blank.")
    page = _Page()
    page.feed(response.body.decode("utf-8", "replace"))
    page.close()
    if not page.data_page:
        raise FetchError("partial", "Southwest Antennas page had no Inertia inventory payload.")
    try:
        return json.loads(unescape(page.data_page))
    except (TypeError, json.JSONDecodeError):
        raise FetchError("partial", "Southwest Antennas Inertia payload was invalid.") from None


def _props(payload, detail=False):
    if not isinstance(payload, dict) or payload.get("component") not in {"About/Careers", "About/Career"}:
        raise FetchError("partial", "Southwest Antennas employer page identity was not verified.")
    props = payload.get("props")
    if not isinstance(props, dict):
        raise FetchError("partial", "Southwest Antennas page has no usable props.")
    if detail:
        record = props.get("career")
        if not isinstance(record, dict):
            raise FetchError("partial", "Southwest Antennas role payload is missing.")
        return record
    # The current Inertia payload exposes careers beside app; older captures
    # and fixtures may nest it under app, so accept both shapes explicitly.
    careers = props.get("careers")
    if careers is None:
        careers = props.get("app", {}).get("careers")
    if not isinstance(careers, (dict, list)):
        raise FetchError("partial", "Southwest Antennas careers inventory is malformed.")
    return careers


def _records(careers):
    values = careers if isinstance(careers, list) else [item for group in careers.values() if isinstance(group, list) for item in group]
    active = []
    seen = set()
    for record in values:
        if not isinstance(record, dict):
            raise FetchError("partial", "Southwest Antennas careers inventory contains an invalid record.")
        live = record.get("live")
        if live in (0, False, "0", None):
            continue
        ident = record.get("id")
        slug = record.get("slug")
        position = text(str(record.get("position", "")))
        if ident in (None, "") or not isinstance(slug, str) or not slug or not position:
            raise FetchError("partial", "Southwest Antennas active role is missing identity fields.")
        key = str(ident)
        if key in seen:
            raise FetchError("partial", "Southwest Antennas careers inventory contains duplicate active IDs.")
        seen.add(key)
        active.append((key, position, slug, record))
    return active


def _detail(client, item, company_id, company):
    ident, position, slug, listed = item
    url = urljoin(SOURCE, CAREER_PREFIX + slug)
    parsed = urlsplit(url)
    if parsed.hostname != HOST or not parsed.path.startswith(CAREER_PREFIX) or parsed.query or parsed.fragment:
        raise FetchError("partial", "Southwest Antennas role URL escaped the verified employer scope.")
    payload = _read(client, url)
    record = _props(payload, detail=True)
    if str(record.get("id")) != ident or record.get("live") in (0, False, "0") or record.get("slug") != slug:
        raise FetchError("partial", "Southwest Antennas role changed or is no longer active.")
    title = text(str(record.get("position", "")))
    description = text(record.get("job_description", ""))
    if title != position or len(description) < 100:
        raise FetchError("partial", "Southwest Antennas role lacks a complete description.")
    row = _base({"id": ident}, ATS, company_id, company)
    row.update(title=title, description=description, url=url,
               department=text(str(record.get("department", ""))),
               created_at=str(record.get("created_at", "")),
               updated_at=str(record.get("updated_at", "")))
    return row


def fetch_southwest_antennas(url, company_id, company, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="Southwest Antennas adapter requires the verified company and careers source.", source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    jobs = []
    try:
        first = _records(_props(_read(client, SOURCE)))
        for item in first:
            jobs.append(_detail(client, item, company_id, company))
        second = _records(_props(_read(client, SOURCE)))
        first_ids = [(x[0], x[2]) for x in first]
        second_ids = [(x[0], x[2]) for x in second]
        if first_ids != second_ids:
            raise FetchError("partial", "Southwest Antennas careers inventory changed during the reread.")
        return Inventory("complete", jobs, f"Southwest Antennas: retrieved {len(jobs)} active role pages and rechecked the careers inventory.", SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", jobs, "Southwest Antennas careers response validation failed.", SOURCE, ATS)
