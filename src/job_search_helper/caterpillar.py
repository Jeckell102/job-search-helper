"""Caterpillar's official careers portal adapter.

Caterpillar publishes its employer-scoped inventory on careers.caterpillar.com
using a custom HTML/XML jobs surface (not a standard public ATS API).  Keep the
adapter deliberately narrow: only Caterpillar's own portal and explicit US
records are accepted, and transport failures remain incomplete rather than
being interpreted as an empty board.
"""
from __future__ import annotations

from html import unescape
import re
from urllib.parse import quote, urljoin
from xml.etree import ElementTree

from .ats import FetchError, Inventory
from .discovery import CareersTransport

COMPANY_ID = "COMP-0238"
COMPANY = "Caterpillar"
SOURCE = "https://careers.caterpillar.com/en/"
XML_SOURCE = "https://careers.caterpillar.com/en/jobs/xml/?country=United+States+of+America&pagesize=1000"
HOST = "careers.caterpillar.com"


def _text(value):
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def _child(record, *names):
    wanted = {name.casefold() for name in names}
    for child in record.iter():
        if child.tag.rsplit("}", 1)[-1].casefold() in wanted:
            value = _text("".join(child.itertext()))
            if value:
                return value
    return ""


def _parse_xml(body: bytes):
    root = ElementTree.fromstring(body)
    jobs = []
    for record in root.iter():
        tags = {child.tag.rsplit("}", 1)[-1].casefold() for child in record}
        if not tags.intersection({"job", "jobposting", "posting", "position"}):
            continue
        title = _child(record, "title", "jobtitle", "postingtitle")
        req_id = _child(record, "id", "jobid", "requisitionid", "requisition")
        url = _child(record, "url", "joburl", "detailurl", "jobdetailurl")
        if not title or not req_id or not url:
            continue
        jobs.append((req_id, title, url, _child(record, "description", "jobdescription"),
                     _child(record, "location", "joblocation")))
    return jobs


def _parse_html(body: bytes):
    text = body.decode("utf-8", "replace")
    jobs = []
    pattern = re.compile(
        r'href=["\'](?P<url>/en/jobs/r(?P<id>\d+)/[^"\']+)["\'][^>]*>(?P<title>.*?)</a>',
        re.I | re.S,
    )
    for match in pattern.finditer(text):
        title = re.sub(r"<[^>]+>", " ", match.group("title"))
        jobs.append((match.group("id"), _text(title), urljoin(SOURCE, match.group("url")), "", ""))
    return jobs


def fetch_caterpillar(careers_url, company_id, company, transport=None):
    if (company_id != COMPANY_ID or company.casefold() != COMPANY.casefold()
            or careers_url.rstrip("/") not in {SOURCE.rstrip("/"), "https://careers.caterpillar.com"}):
        return Inventory("unsupported", [], "Caterpillar adapter received an unexpected company or source.", careers_url, "Caterpillar Careers")
    client = transport or CareersTransport()
    try:
        response = client.get(XML_SOURCE)
        if response.status in (401, 403, 429):
            raise FetchError("blocked", f"Caterpillar official careers feed HTTP {response.status}; public inventory is unavailable.")
        if response.status != 200:
            raise FetchError("partial", f"Caterpillar official careers feed HTTP {response.status}; inventory completeness is unknown.")
        try:
            raw_jobs = _parse_xml(response.body)
        except ElementTree.ParseError:
            raw_jobs = _parse_html(response.body)
        jobs = []
        seen = set()
        for req_id, title, url, description, location in raw_jobs:
            if req_id in seen or not url.startswith("https://careers.caterpillar.com/"):
                continue
            seen.add(req_id)
            jobs.append({
                "company_id": company_id, "company": company, "ats": "Caterpillar Careers",
                "posting_id": req_id, "req_id": req_id, "url": url, "title": title,
                "description": description, "location": location, "is_listed": True,
            })
        if not jobs:
            raise FetchError("partial", "Caterpillar official careers feed returned no verifiable US postings; inventory completeness is unknown.")
        return Inventory("complete", jobs, f"Caterpillar employer-scoped feed returned {len(jobs)} US postings.", XML_SOURCE, "Caterpillar Careers")
    except FetchError as exc:
        return Inventory(exc.status, [], exc.reason, XML_SOURCE, "Caterpillar Careers")
    except Exception as exc:
        return Inventory("partial", [], f"Caterpillar official careers feed transport failed ({type(exc).__name__}); inventory completeness is unknown.", XML_SOURCE, "Caterpillar Careers")
