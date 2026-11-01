"""Public BrightMove career portal for Mission Critical Partners.

BrightMove's public portal is a server-rendered HTML listing and detail surface.
This adapter is deliberately pinned to MCP's employer portal and fails closed
when its published count, scope, or detail schema changes.
"""
from __future__ import annotations

from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qsl, urljoin, urlsplit

from .ats import FetchError, HTTPResponse, Inventory, _base
from .core import plain_text
from .discovery import CareersTransport

HOST = "j.brt.mv"
PORTAL = "39203"
SOURCE = "https://j.brt.mv/ax.do?refresh=true&portalGK=39203"
LIST_PATH = "/ax.do"
DETAIL_PATH = "/PortalViewRequirement.do"
MAX_JOBS = 1000


class BrightMoveTransport:
    """Transport restricted to MCP's verified BrightMove portal and details."""
    def __init__(self, base=None):
        self.base = base or CareersTransport()

    def get(self, url):
        p = urlsplit(url)
        pairs = parse_qsl(p.query, keep_blank_values=True, max_num_fields=10)
        query = dict(pairs)
        if (p.scheme != 'https' or p.hostname != HOST or p.port not in (None, 443)
                or p.username or p.password or p.fragment or len(pairs) != len(query)):
            raise FetchError('unsupported', 'BrightMove requires a verified public portal URL.')
        if url != SOURCE and not (p.scheme == "https" and p.hostname == HOST
                                   and p.path == DETAIL_PATH and set(query) == {"reqGK"}
                                   and re.fullmatch(r"[0-9]{1,20}", query.get("reqGK", ""))):
            if not (p.scheme == "https" and p.hostname == HOST and p.path == LIST_PATH
                    and query.get("portalGK") == PORTAL and set(query) <= {"portalGK", "refresh", "allOpenJobsStart"}
                    and query.get("allOpenJobsStart", "1").isdigit()):
                raise FetchError("unsupported", "BrightMove transport is restricted to MCP's pinned public portal and details.")
        return self.base.get(url)


def supports_brightmove(url: str) -> bool:
    try:
        p = urlsplit(url)
        pairs = parse_qsl(p.query, keep_blank_values=True, max_num_fields=10)
        q = dict(pairs)
        return (p.scheme == "https" and p.hostname == HOST and p.path == LIST_PATH
                and p.port in (None, 443) and not p.username and not p.password and not p.fragment
                and len(pairs) == len(q)
                and q.get("portalGK") == PORTAL and set(q) <= {"portalGK", "refresh", "allOpenJobsStart"}
                and ("allOpenJobsStart" not in q or q["allOpenJobsStart"].isdigit()))
    except (TypeError, ValueError):
        return False


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.text: list[str] = []
        self.headings: list[str] = []
        self._href = None
        self._link: list[str] = []
        self._heading: list[str] | None = None
        self.jsonld: list[dict] = []
        self._script_jsonld = False
        self._script_data: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and (attrs.get("type") or "").casefold() == "application/ld+json":
            self._script_jsonld = True
            self._script_data = []
            return
        if tag == "a" and attrs.get("href"):
            self._href = attrs["href"]
            self._link = []
        if tag in {"h1", "h2", "h3"}:
            self._heading = []

    def handle_data(self, data):
        self.text.append(data)
        if self._script_jsonld:
            self._script_data.append(data)
        if self._href is not None:
            self._link.append(data)
        if self._heading is not None:
            self._heading.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._script_jsonld:
            try:
                value = json.loads("".join(self._script_data))
                values = value if isinstance(value, list) else [value]
                self.jsonld.extend(item for item in values if isinstance(item, dict))
            except (TypeError, ValueError, UnicodeError):
                pass
            self._script_jsonld = False
            self._script_data = []
            return
        if tag == "a" and self._href is not None:
            self.links.append((self._href, plain_text(" ".join(self._link))))
            self._href = None
            self._link = []
        if tag in {"h1", "h2", "h3"} and self._heading is not None:
            heading = plain_text(" ".join(self._heading))
            if heading:
                self.headings.append(heading)
            self._heading = None


def _get(url: str, transport) -> _Page:
    response = transport.get(url)
    if not isinstance(response, HTTPResponse):
        raise FetchError("failed", "BrightMove transport returned an invalid response.")
    if response.status in {401, 403, 429}:
        raise FetchError("blocked", f"BrightMove HTTP {response.status}: public portal access denied.")
    if not 200 <= response.status < 300:
        raise FetchError("failed", f"BrightMove HTTP {response.status}; inventory unavailable.")
    parser = _Page()
    parser.feed(response.body.decode("utf-8", "replace"))
    parser.close()
    return parser


def _links(parser: _Page, source: str) -> dict[str, tuple[str, str]]:
    result = {}
    for href, label in parser.links:
        url = urljoin(source, href)
        p = urlsplit(url)
        if (p.scheme != "https" or p.hostname != HOST or p.path != DETAIL_PATH
                or p.port not in (None, 443) or p.username or p.password or p.fragment):
            continue
        q = dict(parse_qsl(p.query, keep_blank_values=True))
        ident = q.get("reqGK", "")
        if set(q) != {"reqGK"} or not re.fullmatch(r"[0-9]{1,20}", ident):
            continue
        if ident in result:
            raise FetchError("partial", "BrightMove listing repeated a posting ID.")
        result[ident] = (url, plain_text(label))
    return result


def _total(parser: _Page) -> int | None:
    body = plain_text(" ".join(parser.text))
    matches = re.findall(r"(?:of\s+)?([0-9][0-9,]*)\s+record\s*\(s\)", body, re.I)
    if not matches:
        return None
    return int(matches[-1].replace(",", ""))


def _range(parser: _Page) -> tuple[int, int, int] | None:
    body = plain_text(" ".join(parser.text))
    matches = re.findall(r"([0-9][0-9,]*)\s*-\s*([0-9][0-9,]*)\s+of\s+([0-9][0-9,]*)\s+record", body, re.I)
    if not matches:
        return None
    return tuple(int(value.replace(",", "")) for value in matches[-1])


def _detail(url: str, parser: _Page, listed_title: str, company_id: str, company: str) -> dict:
    ident = dict(parse_qsl(urlsplit(url).query)).get("reqGK", "")
    structured = [item for item in parser.jsonld if item.get("@type") == "JobPosting"]
    if not structured:
        raise FetchError("partial", "BrightMove detail did not expose a JobPosting record.")
    matching = []
    for item in structured:
        value = item.get("identifier")
        if isinstance(value, dict):
            value = value.get("value")
        if str(value) == ident:
            matching.append(item)
    if matching:
        if len(matching) != 1:
            raise FetchError("partial", "BrightMove detail exposed multiple matching JobPosting records.")
        item = matching[0]
        title = plain_text(item.get("title", ""))
        body = plain_text(item.get("description", ""))
        hiring = item.get("hiringOrganization")
        hiring_name = hiring.get("name", "") if isinstance(hiring, dict) else ""
        if (not title or not body or title.casefold() != listed_title.casefold()
                or plain_text(hiring_name).casefold() not in {"mission critical partners", "mission critical partners, llc"}):
            raise FetchError("partial", "BrightMove structured job record failed title, employer, or description validation.")
        place = item.get("jobLocation")
        place = place[0] if isinstance(place, list) and place else place
        address = place.get("address") if isinstance(place, dict) else {}
        location = plain_text((address or {}).get("addressLocality", "")) if isinstance(address, dict) else ""
        row = _base({"id": ident}, "BrightMove", company_id, company)
        row.update(req_id=ident, title=title, url=url, description=body,
                   location=location,
                   work_arrangement="Remote" if re.search(r"\bremote\b", location, re.I) else "",
                   created_at=plain_text(item.get("datePosted", "")),
                   is_listed=True)
        return row
    raise FetchError("partial", "BrightMove detail did not expose a valid structured JobPosting record.")


def fetch_brightmove(source: str, company_id: str, company: str, transport) -> Inventory:
    if not supports_brightmove(source) or source != SOURCE:
        return Inventory("unsupported", reason="BrightMove adapter requires the verified MCP public portal.", source_url=source, ats="BrightMove")
    jobs: list[dict] = []
    try:
        first = _get(source, transport)
        expected = _total(first)
        links = _links(first, source)
        if expected is None or expected > MAX_JOBS or _range(first) != (1, min(25, expected), expected):
            raise FetchError("partial", "BrightMove listing did not expose a trustworthy published count.")
        starts = list(range(26, expected + 1, 25))
        for start in starts:
            page_url = source + "&allOpenJobsStart=" + str(start)
            page = _get(page_url, transport)
            last = min(start + 24, expected)
            if _total(page) != expected or _range(page) != (start, last, expected):
                raise FetchError("partial", "BrightMove published count changed during pagination.")
            for ident, row in _links(page, source).items():
                if ident in links:
                    raise FetchError("partial", "BrightMove pagination repeated a posting ID.")
                links[ident] = row
        if len(links) != expected:
            raise FetchError("partial", f"BrightMove returned {len(links)} unique postings out of reported total {expected}.")
        for ident, (url, title) in sorted(links.items()):
            jobs.append(_detail(url, _get(url, transport), title, company_id, company))
        check = _get(source, transport)
        check_links = _links(check, source)
        if _total(check) != expected or _range(check) != (1, min(25, expected), expected):
            raise FetchError("partial", "BrightMove inventory changed during the scan.")
        checked = set(check_links)
        for start in starts:
            page = _get(source + "&allOpenJobsStart=" + str(start), transport)
            last = min(start + 24, expected)
            if _total(page) != expected or _range(page) != (start, last, expected):
                raise FetchError("partial", "BrightMove inventory changed during pagination recheck.")
            for ident, row in _links(page, source).items():
                if ident in checked:
                    raise FetchError("partial", "BrightMove recheck repeated a posting ID.")
                checked.add(ident)
                check_links[ident] = row
        if _total(check) != expected or check_links != links:
            raise FetchError("partial", "BrightMove inventory changed during the scan.")
        return Inventory("complete", jobs, f"BrightMove: retrieved {len(jobs)} full postings and rechecked the public inventory.", source, "BrightMove")
    except FetchError as exc:
        return Inventory(exc.status if not jobs else "partial", jobs, exc.reason, source, "BrightMove")
    except (OSError, ValueError, TypeError, AttributeError, UnicodeError):
        return Inventory("partial" if jobs else "failed", jobs, "BrightMove transport or schema validation failed; inventory not complete.", source, "BrightMove")
