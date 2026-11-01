"""Bounded public TriNet Hire board support for verified employer pages.

The Uhnder board is currently an explicitly empty public inventory.  Keep the
empty-state proof strict; if TriNet publishes postings again, fail closed until
their public detail schema is mapped rather than silently importing partial data.
"""
from __future__ import annotations

import re

from .ats import FetchError, Inventory
from .shared_boards import checked


SOURCE = "https://app.trinethire.com/companies/32235-uhnder-inc/jobs"


def fetch_trinet(url, company_id, company, transport=None):
    if url != SOURCE:
        return Inventory("unsupported", reason="TriNet Hire requires the verified Uhnder employer board.",
                         source_url=url, ats="TriNet Hire")
    client = transport
    if client is None:
        from .discovery import CareersTransport
        client = CareersTransport()
    try:
        body = checked(client.get(url), True)
        if re.search(r"no current job openings|no current openings|no jobs currently", body, re.I):
            return Inventory("complete", [], "TriNet Hire: verified public board is empty.", url, "TriNet Hire")
        # TriNet renders location/department separators as ``job`` rows even
        # when the employer has no postings.  Treat that explicit empty table
        # shape as empty only when no employer-detail link is present; a real
        # posting must expose a same-board job URL and therefore fails closed
        # if TriNet changes its public detail markup.
        has_detail = re.search(r'href=["\'][^"\']*/companies/32235-uhnder-inc/jobs/[^"\'?#]+', body, re.I)
        table = re.search(r'<table[^>]*class=["\'][^"\']*job-list[^"\']*["\'][\s\S]*?</table>', body, re.I)
        tbody = re.search(r'<tbody[^>]*class=["\'][^"\']*sortable[^"\']*["\'][\s\S]*?</tbody>', table.group(0), re.I) if table else None
        if table and tbody and not has_detail and not re.search(r'<tr(?![^>]*class=["\'][^"\']*separator)', tbody.group(0), re.I):
            return Inventory("complete", [], "TriNet Hire: verified public board is empty.", url, "TriNet Hire")
        return Inventory("partial", [],
                         "TriNet Hire public board has postings, but its detail schema is not yet verified.",
                         url, "TriNet Hire")
    except FetchError as error:
        return Inventory(error.status, [], error.reason, url, "TriNet Hire")
    except (OSError, UnicodeDecodeError, TypeError, AttributeError):
        return Inventory("failed", [], "TriNet Hire public board could not be read.", url, "TriNet Hire")
