"""Antenna Research Associates' official careers-board verification.

ARA links its careers page to a public UKG/SAASHR single-page board.  The
board shell is public, but its documented anonymous search/config endpoints
currently return 404, so an empty shell must not be interpreted as zero jobs.
"""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _challenge
from .discovery import CareersTransport

SOURCE = "https://ara-inc.com/careers/"
BOARD = "https://secure7.saashr.com/ta/6178347.careers?CareersSearch"
BOARD_HOST = "secure7.saashr.com"
ATS = "Antenna Research Associates careers"
COMPANY_ID = "COMP-0493"
COMPANY = "Antenna Research Associates"


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_data(self, data):
        self.text.append(data)


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname == "ara-inc.com"
                and parsed.path.rstrip("/") == "/careers"
                and not parsed.query and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _get(client, url):
    response = client.get(url)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"ARA careers source blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("blocked", f"ARA public careers board returned HTTP {response.status}.")
    if not response.body:
        raise FetchError("partial", "ARA careers source was blank.")
    return response


def _board_link(page):
    for href in page.links:
        candidate = urljoin(SOURCE, href)
        parsed = urlsplit(candidate)
        if (parsed.scheme == "https" and parsed.hostname == BOARD_HOST
                and parsed.path == "/ta/6178347.careers"
                and parsed.query == "CareersSearch" and not parsed.fragment):
            return candidate
    return ""


def fetch_antenna_research_associates(url, company_id, company, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="ARA adapter requires the verified company and careers source.",
                         source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    try:
        source = _Page()
        source.feed(_get(client, SOURCE).body.decode("utf-8", "replace"))
        source.close()
        board = _board_link(source)
        if not board:
            raise FetchError("partial", "ARA careers page no longer links its verified public job board.")

        board_response = _get(client, BOARD)
        board_body = board_response.body.decode("utf-8", "replace")
        board_page = _Page()
        board_page.feed(board_body)
        board_page.close()
        # The public response is a JavaScript shell (the rendered inventory is
        # requested by client-side API calls).  Do not treat that shell as an
        # empty job board; the anonymous API currently returns 404.
        if 'id="_app"' in board_body:
            raise FetchError("blocked", "ARA's linked SAASHR job board is a JavaScript shell; its public search/config API currently returns HTTP 404, so inventory cannot be verified.")
        raise FetchError("partial", "ARA linked job board had no verifiable public inventory.")
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", [], "ARA careers response validation failed.", SOURCE, ATS)
