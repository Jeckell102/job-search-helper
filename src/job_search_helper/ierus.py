"""IERUS Technologies' employer-scoped JobScore Atom inventory."""
from __future__ import annotations

from html import unescape
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from xml.etree import ElementTree

from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport

CAREERS_SOURCE = "https://ierustech.com/careers/open-positions/"
FEED_SOURCE = "https://careers.jobscore.com/jobs/ierustechnologiesinc/feed.atom"
LEGACY_FEED_SOURCE = "https://hire.jobscore.com/jobs/ierustechnologiesinc/feed.atom"
SELF_FEED_SOURCE = "https://www.jobscore.com/jobs/ierustechnologiesinc/feed.atom"
ATS = "JobScore"
COMPANY_ID = "COMP-0449"
COMPANY = "IERUS Technologies"

_DETAIL_HOST = "careers.jobscore.com"
_FEED_PATH = "/jobs/ierustechnologiesinc/feed.atom"
_DETAIL_PREFIX = "/careers/ierustechnologiesinc/jobs/"
_SOURCE_ALIASES = {CAREERS_SOURCE, FEED_SOURCE, LEGACY_FEED_SOURCE, SELF_FEED_SOURCE}


def _tag(element):
    return element.tag.rsplit("}", 1)[-1].casefold()


def _value(element, name):
    for child in element:
        if _tag(child) == name.casefold():
            return "".join(child.itertext()).strip()
    return ""


def _link(entry):
    for child in entry:
        if _tag(child) == "link":
            href = child.attrib.get("href", "").strip()
            if href:
                return href
            value = "".join(child.itertext()).strip()
            if value:
                return value
    return ""


def _verified_feed(url, company_id, company):
    try:
        parsed = urlsplit(url)
        canonical = f"{parsed.scheme}://{parsed.hostname}{parsed.path}"
        return (
            company_id == COMPANY_ID
            and company.strip().casefold() == COMPANY.casefold()
            and not parsed.username
            and not parsed.password
            and parsed.port is None
            and canonical in _SOURCE_ALIASES
            and not parsed.query
            and not parsed.fragment
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _category(entry, fragment):
    for child in entry:
        if _tag(child) == "category" and fragment in child.attrib.get("scheme", ""):
            return text(child.attrib.get("term", ""))
    return ""


def _has_unread_page(root):
    for child in root:
        if _tag(child) == "link" and child.attrib.get("rel", "").casefold() == "next":
            return True
    return False


def _canonical_detail_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.hostname != _DETAIL_HOST
            or parsed.username or parsed.password or parsed.port is not None
            or not parsed.path.startswith(_DETAIL_PREFIX) or parsed.fragment):
        return ""
    if parsed.query:
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if (set(query) != {"ref", "sid"} or query["ref"] != "rss"
                or not query["sid"].isdigit()):
            return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _parse_feed(body):
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, UnicodeError) as exc:
        raise FetchError("partial", "IERUS JobScore feed was not valid Atom XML.") from exc

    if _has_unread_page(root):
        raise FetchError("partial", "IERUS JobScore feed advertised another page that is not yet reconciled.")

    jobs = []
    seen = set()
    for entry in root.iter():
        if _tag(entry) != "entry":
            continue
        posting_id = _value(entry, "id")
        title = text(_value(entry, "title"))
        url = _link(entry)
        description = text(unescape(_value(entry, "content") or _value(entry, "summary")))
        location = text(_value(entry, "location"))
        if not posting_id or not title or not url or not description:
            raise FetchError("partial", "IERUS JobScore feed contained a posting without a full description.")
        url = _canonical_detail_url(url)
        if not url or posting_id in seen:
            raise FetchError("partial", "IERUS JobScore feed contained an invalid or duplicate posting.")
        seen.add(posting_id)
        row = _base({"id": posting_id}, ATS, COMPANY_ID, COMPANY)
        row.update(
            title=title,
            url=url,
            location=location or _category(entry, "#location"),
            description=description,
            department=_category(entry, "#department"),
            created_at=_value(entry, "published"),
            updated_at=_value(entry, "updated"),
        )
        jobs.append(row)
    if not jobs:
        raise FetchError("partial", "IERUS JobScore feed exposed no employer-scoped postings.")
    return jobs


def _read(client):
    response = client.get(FEED_SOURCE)
    if response.status in {401, 403, 429}:
        raise FetchError("blocked", f"IERUS JobScore feed blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"IERUS JobScore feed HTTP {response.status}; inventory completeness is unknown.")
    return _parse_feed(response.body)


def fetch_ierus(careers_url, company_id, company, transport=None):
    if not _verified_feed(careers_url, company_id, company):
        return Inventory("unsupported", [], "IERUS requires its verified employer-scoped JobScore feed.", careers_url, ATS)
    client = transport or CareersTransport(accept="application/atom+xml, application/xml, text/xml")
    try:
        first = _read(client)
        second = _read(client)
        first_key = [(job["posting_id"], job["title"], job["description"]) for job in first]
        second_key = [(job["posting_id"], job["title"], job["description"]) for job in second]
        if first_key != second_key:
            raise FetchError("partial", "IERUS JobScore inventory changed during the reread.")
        return Inventory("complete", first, f"IERUS Technologies: retrieved {len(first)} full JobScore descriptions and rechecked the feed.", FEED_SOURCE, ATS)
    except FetchError as exc:
        return Inventory(exc.status, [], exc.reason, FEED_SOURCE, ATS)
    except (AttributeError, TypeError, OSError, ValueError):
        return Inventory("partial", [], "IERUS JobScore validation failed; inventory completeness is unknown.", FEED_SOURCE, ATS)
