"""Guarded public career-page adapter for UKG Pro Workforce Ready (SaaShr).

Hallam-ICS publishes its public board at one tenant-specific SaaShr URL.  The
page is JavaScript-heavy and its markup has changed over time, so this adapter
accepts only links that remain on the exact tenant and only closes an
inventory after every discovered detail page has a complete description.
"""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit

from .ats import FetchError, HTTPResponse, HTTPTransport, Inventory, _base, text
from .discovery import CareersTransport

SOURCE = "https://secure7.saashr.com/ta/6211585.careers?CareersSearch=&career_portal_id=4915719&ein_id=118982210&lang=en-US"
HOST = "secure7.saashr.com"
PATH = "/ta/6211585.careers"


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.parts: list[str] = []
        self.text_parts: list[str] = []
        self._anchor: str | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self._anchor = attrs["href"]
            self.parts = []

    def handle_data(self, data):
        self.text_parts.append(data)
        if self._anchor is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor is not None:
            self.links.append((self._anchor, text(" ".join(self.parts))))
            self._anchor = None
            self.parts = []


def _read(client, url):
    response = client.get(url)
    if not isinstance(response, HTTPResponse):
        raise FetchError("failed", "SaaShr transport returned an invalid response.")
    if response.status in (401, 403, 429):
        raise FetchError("blocked", f"SaaShr public careers page HTTP {response.status}.")
    if response.status != 200:
        raise FetchError("partial", f"SaaShr public careers page HTTP {response.status}.")
    return response.body.decode("utf-8", "replace")


def _role_links(html):
    page = _Page()
    page.feed(html)
    result = []
    for href, title in page.links:
        url = urljoin(SOURCE, href)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != HOST or parsed.path != PATH:
            continue
        query = parse_qs(parsed.query, keep_blank_values=True)
        # SaaShr exposes detail links as the same tenant route with a job
        # selector.  Do not treat the unfiltered search URL as a posting.
        if not any(key.casefold() in {"jobid", "job_id", "showjob", "job"} for key in query):
            continue
        ident = next((value[0].strip() for key, value in query.items()
                      if key.casefold() in {"jobid", "job_id", "showjob", "job"} and value and value[0].strip()), "")
        if not ident or not title.strip():
            continue
        canonical = parsed._replace(fragment="").geturl()
        if canonical not in [item[0] for item in result]:
            result.append((canonical, title.strip(), ident))
    return result


def fetch_saashr(careers_url, company_id, company, transport=None):
    client = CareersTransport() if transport is None or isinstance(transport, HTTPTransport) else transport
    jobs = []
    try:
        first = _role_links(_read(client, SOURCE))
        if not first:
            raise FetchError("partial", "SaaShr page exposed no verifiable Hallam-ICS job detail links.")
        for url, listed_title, ident in first:
            detail = _Page()
            detail.feed(_read(client, url))
            body = text(" ".join(detail.text_parts))
            if len(body) < 200:
                raise FetchError("partial", "SaaShr job detail lacks a complete public description.")
            row = _base({"id": ident}, "SaaShr", company_id, company)
            row.update(title=listed_title, url=url, description=body, location="", work_arrangement="")
            jobs.append(row)
        if _role_links(_read(client, SOURCE)) != first:
            raise FetchError("partial", "SaaShr Hallam-ICS inventory changed during the scan.")
        return Inventory("complete", jobs, f"SaaShr: retrieved {len(jobs)} full Hallam-ICS postings and rechecked the public inventory.", SOURCE, "SaaShr")
    except FetchError as exc:
        return Inventory(exc.status, jobs, exc.reason, SOURCE, "SaaShr")
    except (AttributeError, TypeError, ValueError, UnicodeError):
        return Inventory("partial", jobs, "SaaShr public careers schema validation failed; inventory incomplete.", SOURCE, "SaaShr")

