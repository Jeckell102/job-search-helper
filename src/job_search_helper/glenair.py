"""Glenair's first-party North America employment inquiry page.

The public U.S. source is an employment-interest form, not a public job
board: it explicitly says it is not a job application and does not publish
role links or an employer-scoped ATS.  Keep this adapter fail-closed so the
normal pipeline cannot turn an inquiry form or a transport failure into an
empty, complete inventory.
"""
from __future__ import annotations

from .ats import FetchError, Inventory
from .discovery import CareersTransport

SOURCE = "https://www.glenair.com/contact/employment.htm"


def fetch_glenair(careers_url, company_id, company, transport=None):
    if careers_url.rstrip("/") != SOURCE.rstrip("/") or company_id != "COMP-0489" or company.casefold() != "glenair":
        return Inventory("unsupported", [], "Glenair adapter received an unexpected company or source.", careers_url, "Glenair employment inquiry", browser_fallback_allowed=False)
    client = transport or CareersTransport()
    try:
        response = client.get(SOURCE)
        if response.status in (401, 403, 429):
            raise FetchError("blocked", f"Glenair employment inquiry HTTP {response.status}; public inventory is unavailable.")
        if response.status != 200:
            raise FetchError("partial", f"Glenair employment inquiry HTTP {response.status}; inventory completeness is unknown.")
        body = response.body.decode("utf-8", "replace").casefold()
        if "not a job application" not in body or "employment submission" not in body:
            raise FetchError("partial", "Glenair source changed; the official employment inquiry identity could not be verified.")
        raise FetchError("partial", "Glenair's official North America source is an employment-interest form, not a public job board or ATS; no public postings can be inventoried.")
    except FetchError as exc:
        return Inventory(exc.status, [], exc.reason, SOURCE, "Glenair employment inquiry", browser_fallback_allowed=False)
    except Exception as exc:
        return Inventory("partial", [], f"Glenair employment inquiry transport failed ({type(exc).__name__}); inventory completeness is unknown.", SOURCE, "Glenair employment inquiry", browser_fallback_allowed=False)
