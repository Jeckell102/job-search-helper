"""BlackTree Technology's employer-published static careers inventory."""
from __future__ import annotations

from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urlencode

from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport


SOURCE = "https://blacktree.com.au/careers/"
HEADINGS = ("Systems Engineers / RF Engineers", "Electronics Technicians", "Project Managers")
COMPANY_ID = "COMP-0042"
COMPANY = "BlackTree Technology"


class _CareersParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._heading_depth = 0
        self._parts: list[str] = []
        self.headings: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "h4":
            self._heading_depth += 1

    def handle_data(self, data):
        if self._heading_depth:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag == "h4" and self._heading_depth:
            self._heading_depth -= 1
            if not self._heading_depth:
                value = " ".join("".join(self._parts).split())
                self._parts = []
                if value:
                    self.headings.append(value)


def _published_positions(transport):
    response = transport.get(SOURCE)
    if response.status != 200:
        raise FetchError("blocked" if response.status in {401, 403, 429} else "partial",
                         "BlackTree public careers page was unavailable.")
    try:
        parser = _CareersParser()
        parser.feed(response.body.decode("utf-8", "replace"))
        parser.close()
    except (AttributeError, TypeError, ValueError):
        raise FetchError("partial", "BlackTree careers page could not be parsed.") from None
    if tuple(parser.headings) != ("In Demand Positions",):
        raise FetchError("partial", "BlackTree careers page no longer exposes its verified in-demand-position section.")
    # The three opportunity names are list items, rather than headings; keep
    # validation tied to their stable, employer-published text and fail closed
    # if the published inventory shape changes.
    raw = response.body.decode("utf-8", "replace")
    if not all(position in raw for position in HEADINGS):
        raise FetchError("partial", "BlackTree published-position inventory changed; retry after adapter review.")
    return HEADINGS


def fetch_blacktree(careers_url, company_id, company, transport=None):
    if careers_url != SOURCE or company_id != COMPANY_ID or company.strip().casefold() != COMPANY.casefold():
        return Inventory("unsupported", reason="BlackTree adapter requires its verified public careers page.",
                         source_url=careers_url, ats="BlackTree careers")
    client = transport or CareersTransport()
    jobs = []
    try:
        positions = _published_positions(client)
        for title in positions:
            identifier = sha256(title.casefold().encode()).hexdigest()[:24]
            job = _base({"id": identifier}, "BlackTree careers", company_id, company)
            # The employer publishes several distinct roles on one careers
            # page.  Preserve a stable, role-specific official page URL so
            # their Job History identities cannot overwrite one another.
            job.update(title=text(title), description="Employer-published in-demand position; submit CV and covering letter to BlackTree.",
                       url=SOURCE + "?" + urlencode({"position": identifier}))
            jobs.append(job)
        if _published_positions(client) != positions:
            raise FetchError("partial", "BlackTree published positions changed during the scan.")
        return Inventory("complete", jobs, f"BlackTree careers: retrieved {len(jobs)} employer-published in-demand positions and rechecked the page.", SOURCE, "BlackTree careers")
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, SOURCE, "BlackTree careers")
    except (AttributeError, TypeError, ValueError):
        return Inventory("partial", jobs, "BlackTree careers schema validation failed.", SOURCE, "BlackTree careers")
