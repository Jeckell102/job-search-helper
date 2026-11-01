"""SEMPRE's employer-published zero-opening careers state."""
from __future__ import annotations

import re

from .ats import FetchError, Inventory, text
from .discovery import CareersTransport

SOURCE = "https://sempre.ai/careers"
NOTICE = "we're not currently hiring, but we're always on the lookout for talented individuals to join our team."


def fetch_sempre(careers_url, company_id, company, transport=None):
    if careers_url != SOURCE:
        return Inventory("unsupported", reason="SEMPRE adapter requires its verified public careers page.", source_url=careers_url, ats="SEMPRE careers")
    client = transport or CareersTransport()
    try:
        response = client.get(SOURCE)
        if response.status != 200:
            raise FetchError("blocked" if response.status in {401, 403, 429} else "partial", "SEMPRE public careers page was unavailable.")
        raw = response.body.decode("utf-8", "replace")
        page = text(raw).casefold()
        if NOTICE not in page:
            raise FetchError("partial", "SEMPRE careers page no longer explicitly reports its zero-opening state.")
        if re.search(r"<[^>]+\bdata-job\s*=", raw, re.I):
            raise FetchError("partial", "SEMPRE careers page contains public job entries despite its zero-opening notice.")
        return Inventory("complete", [], "SEMPRE careers: employer explicitly reports no current openings and publishes no job entries.", SOURCE, "SEMPRE careers")
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, "SEMPRE careers")
    except (AttributeError, TypeError, ValueError):
        return Inventory("partial", [], "SEMPRE public careers schema validation failed.", SOURCE, "SEMPRE careers")
