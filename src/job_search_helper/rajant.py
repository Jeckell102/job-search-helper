"""Rajant's first-party careers page and linked job-description PDFs."""
from __future__ import annotations

from html.parser import HTMLParser
import re
import shutil
import subprocess
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://rajant.com/about/careers/"
HOST = "rajant.com"
PDF_PREFIX = "/wp-content/uploads/"
ATS = "Rajant careers"
COMPANY_ID = "COMP-0113"
COMPANY = "Rajant Corporation"


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.parts = []
        self._heading = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in {"h1", "h2", "h3", "p", "li", "div", "title"}:
            self.parts.append(" ")
        if tag in {"h1", "h2", "h3"}:
            self._heading = True

    def handle_data(self, data):
        self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in {"h1", "h2", "h3"}:
            self._heading = False


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path.rstrip("/") == "/about/careers"
                and not parsed.query and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _get(client, url):
    response = client.get(url)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=url == SOURCE):
        raise FetchError("blocked", f"Rajant careers source blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"Rajant careers source HTTP {response.status}.")
    if not response.body:
        raise FetchError("partial", "Rajant careers source was blank.")
    return response


def _role_urls(page):
    urls = []
    for href in page.links:
        candidate = urljoin(SOURCE, href)
        parsed = urlsplit(candidate)
        if (parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path.startswith(PDF_PREFIX)
                and parsed.path.casefold().endswith(".pdf")
                and not parsed.query and not parsed.fragment
                and candidate not in urls):
            urls.append(candidate)
    return urls


def _pdf_text(body):
    if shutil.which("pdftotext") is None:
        raise FetchError("partial", "Rajant role PDF cannot be text-extracted in this runtime.")
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", "-", "-"], input=body,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise FetchError("partial", "Rajant role PDF text extraction failed.") from None
    description = text(result.stdout.decode("utf-8", "replace"))
    if len(description) < 300 or "rajant" not in description.casefold():
        raise FetchError("partial", "Rajant role PDF lacks a complete job description.")
    raw_title = next((line.strip() for line in description.splitlines()
                  if line.strip() and len(line.strip()) < 140
                  and not line.strip().startswith("200 Chesterfield")), "")
    title = re.split(r"\s+Location:|\s*[-–]\s*(?=(?:Malvern|Morehead|Remote))|\s+Malvern PA\.",
                     raw_title, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    if not title:
        raise FetchError("partial", "Rajant role PDF lacks a title.")
    return title, description


def fetch_rajant(url, company_id, company, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="Rajant adapter requires the verified company and careers source.",
                         source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    jobs = []
    try:
        first = _get(client, SOURCE)
        page = _Page()
        page.feed(first.body.decode("utf-8", "replace"))
        page.close()
        visible = text(" ".join(page.parts))
        if "rajant" not in visible.casefold() or "current openings" not in visible.casefold():
            raise FetchError("partial", "Rajant careers identity or Current Openings section is missing.")
        urls = _role_urls(page)
        if not urls:
            raise FetchError("partial", "Rajant careers page has no published role PDF links.")
        seen = set()
        for role_url in urls:
            response = _get(client, role_url)
            title, description = _pdf_text(response.body)
            if role_url in seen:
                raise FetchError("partial", "Rajant careers page contains duplicate role PDFs.")
            seen.add(role_url)
            jobs.append(_base({"id": role_url}, ATS, company_id, company) | {
                "title": title, "description": description, "url": role_url,
            })
        second = _get(client, SOURCE)
        reread = _Page()
        reread.feed(second.body.decode("utf-8", "replace"))
        reread.close()
        if _role_urls(reread) != urls:
            raise FetchError("partial", "Rajant careers inventory changed during the reread.")
        return Inventory("complete", jobs,
                         f"Rajant: retrieved {len(jobs)} published role PDFs and rechecked the careers page.",
                         SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", jobs, "Rajant careers response validation failed.", SOURCE, ATS)
