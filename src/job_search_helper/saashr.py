"""Guarded anonymous SaaShr/UKG Ready inventory for Hallam-ICS."""
from __future__ import annotations

from collections import deque
from html.parser import HTMLParser
import socket
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener
from http.cookiejar import CookieJar

from .ats import FetchError, HTTPResponse, Inventory, MAX_RESPONSE_BYTES, _base, _challenge, _delay, text

SOURCE = "https://secure7.saashr.com/ta/6211585.careers?CareersSearch=&career_portal_id=4915719&ein_id=118982210&lang=en-US"
HOST = "secure7.saashr.com"
PATH = "/ta/6211585.careers"
MAX_PAGES = 100
MAX_JOBS = 5000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.text_parts = []
        self._anchor = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self._anchor = (attrs["href"], attrs, [])

    def handle_data(self, data):
        self.text_parts.append(data)
        if self._anchor is not None:
            self._anchor[2].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor is not None:
            href, attrs, parts = self._anchor
            self.links.append((href, text(" ".join(parts)), attrs))
            self._anchor = None


def _same_board(url):
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname == HOST and parsed.path == PATH
            and not parsed.fragment and not parsed.username and not parsed.password
            and parsed.port in (None, 443))


def _canonical(url):
    parsed = urlsplit(url)
    encoded = urlencode(parse_qsl(parsed.query, keep_blank_values=True))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, encoded, ""))


def _page_links(html, base):
    page = _Page(); page.feed(html); page.close()
    details, pagination = [], []
    for href, title, attrs in page.links:
        candidate = urljoin(base, href)
        if not _same_board(candidate):
            continue
        query = parse_qs(urlsplit(candidate).query, keep_blank_values=True)
        if query.get("career_portal_id") != ["4915719"] or query.get("ein_id") != ["118982210"]:
            continue
        keys = {key.casefold() for key in query}
        if keys & {"jobid", "job_id", "showjob", "job"}:
            ident = next((values[0].strip() for key, values in query.items()
                          if key.casefold() in {"jobid", "job_id", "showjob", "job"} and values and values[0].strip()), "")
            if ident and title.strip():
                details.append((_canonical(candidate), title.strip(), ident))
        elif (attrs.get("rel", "").casefold() == "next" or
              any(word in (title + " " + attrs.get("aria-label", "")).casefold()
                  for word in ("next", "more", "older"))):
            pagination.append(_canonical(candidate))
    return details, pagination


class SaaShrTransport:
    """Anonymous cookie session with pinned host, bounded retries and pacing."""
    def __init__(self, timeout=20, interval=.4, sleep=time.sleep):
        self.timeout, self.interval, self.sleep = timeout, interval, sleep
        self.last = 0.0
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()), _NoRedirect())

    def get(self, url):
        if not _same_board(url):
            raise FetchError("unsupported", "SaaShr session is pinned to the verified Hallam-ICS tenant.")
        for attempt in range(3):
            self.sleep(max(0.0, self.interval - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            request = Request(url, headers={"User-Agent": "JobSearchHelper/1.0 (public job-board inventory; read-only)",
                                             "Accept": "text/html,application/xhtml+xml", "Accept-Encoding": "identity"})
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    result = HTTPResponse(response.status, response.read(MAX_RESPONSE_BYTES + 1), dict(response.headers))
            except HTTPError as exc:
                result = HTTPResponse(exc.code, exc.read(8192), dict(exc.headers)); exc.close()
            except (URLError, TimeoutError, socket.timeout, ConnectionError, HTTPException):
                if attempt == 2:
                    raise FetchError("failed", "SaaShr network/timeout failure after bounded retries.") from None
                self.sleep(2 ** attempt); continue
            if result.status in (408, 429, 500, 502, 503, 504) and attempt < 2:
                self.sleep(_delay(result.headers, attempt)); continue
            return result
        raise FetchError("failed", "SaaShr request did not complete.")


def _read(client, url):
    response = client.get(url)
    if not isinstance(response, HTTPResponse):
        raise FetchError("failed", "SaaShr transport returned an invalid response.")
    if response.status in (401, 403, 429) or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"SaaShr public careers page HTTP {response.status} or human-verification challenge.")
    if response.status != 200:
        raise FetchError("partial", f"SaaShr public careers page HTTP {response.status}.")
    if len(response.body) > MAX_RESPONSE_BYTES:
        raise FetchError("partial", "SaaShr response exceeds the bounded size limit.")
    return response.body.decode("utf-8", "replace")


def _inventory(client):
    queue, visited, details = deque([_canonical(SOURCE)]), set(), {}
    while queue:
        page_url = queue.popleft()
        if page_url in visited:
            continue
        if len(visited) >= MAX_PAGES:
            raise FetchError("partial", "SaaShr pagination limit reached before termination.")
        visited.add(page_url)
        found, next_urls = _page_links(_read(client, page_url), page_url)
        for row in found:
            details[row[0]] = row
        for next_url in next_urls:
            if next_url not in visited:
                queue.append(next_url)
        if len(details) > MAX_JOBS:
            raise FetchError("partial", "SaaShr inventory exceeds the bounded job limit.")
    if not details:
        raise FetchError("partial", "SaaShr page exposed no verifiable Hallam-ICS job detail links.")
    return list(details.values()), visited


def fetch_saashr(careers_url, company_id, company, transport=None, progress_factory=None):
    jobs, source = [], SOURCE
    try:
        client = transport or SaaShrTransport()
        entries, pages = _inventory(client)
        progress = progress_factory(SOURCE) if progress_factory is not None else None
        if progress is not None:
            progress.discover([{"url": url, "title": title, "id": ident} for url, title, ident in entries])
        for url, listed_title, ident in entries:
            saved = progress.entries().get(url, {}).get("job") if progress is not None else None
            if saved is not None:
                jobs.append(saved); continue
            detail = _Page(); detail.feed(_read(client, url)); detail.close()
            body = text(" ".join(detail.text_parts))
            if len(body) < 200:
                if progress is not None: progress.failed(url, "SaaShr job detail lacks a complete public description.")
                raise FetchError("partial", "SaaShr job detail lacks a complete public description.")
            row = _base({"id": ident}, "SaaShr", company_id, company)
            row.update(title=listed_title, url=url, description=body, location="", work_arrangement="")
            jobs.append(row)
            if progress is not None: progress.save_job(url, row)
        reread, _ = _inventory(client)
        if reread != entries:
            raise FetchError("partial", "SaaShr inventory changed during the scan or pagination did not terminate consistently.")
        return Inventory("complete", jobs, f"SaaShr: retrieved {len(jobs)} full Hallam-ICS postings across {len(pages)} page(s) and rechecked the public inventory.", SOURCE, "SaaShr")
    except FetchError as exc:
        return Inventory(exc.status, jobs, exc.reason, source, "SaaShr")
    except (AttributeError, TypeError, ValueError, UnicodeError, OSError):
        return Inventory("partial" if jobs else "failed", jobs, "SaaShr public careers request or schema validation failed; inventory incomplete.", source, "SaaShr")
