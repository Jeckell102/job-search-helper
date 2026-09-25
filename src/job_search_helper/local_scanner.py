"""Serial local scans using the existing official, read-only adapters."""
from __future__ import annotations

import json

from .ats import HTTPTransport, Inventory, fetch_inventory, resolve_board
from .discovery import CareersTransport
from .scan_service import ScanService
from .taleo_careers import supports_scoped_taleo_careers


def scan_options(settings) -> dict:
    if settings.workers != 1 or settings.browser_enabled or settings.retry_attempts != 3:
        raise ValueError("Local scans currently require workers=1, browser_enabled=false and retry_attempts=3")
    return {"timeout_seconds": settings.timeout_seconds, "host_interval_seconds": settings.host_interval_seconds}


def run_cycle(database, cycle: str, *, retry_exceptions=False, fetcher=None) -> dict:
    service = ScanService(database)
    options = json.loads(service.status(cycle)["cycle"]["run_settings_json"])
    api = HTTPTransport(timeout=options.get("timeout_seconds", 25), interval=options.get("host_interval_seconds", 0.4))
    careers = CareersTransport(timeout=api.timeout, interval=api.interval)

    def fetch(member):
        provider, url = member["provider_at_start"], member["careers_url_at_start"]
        # Source repair/discovery needs a new verified namespace before it can
        # reuse provider IDs. This phase accepts explicit boards/scoped sites.
        if not supports_scoped_taleo_careers(provider, url):
            try:
                resolve_board(provider, url)
            except ValueError as exc:
                return Inventory("unsupported", reason=str(exc), source_url=url)
        return fetch_inventory(provider, url, member["company_id"], member["company_name_at_start"],
                               api, discovery_transport=careers)

    fetcher = fetcher or fetch
    try:
        # Capture retries before recovery so a result just recovered does not
        # immediately cause another network attempt in the same invocation.
        retry_ids = {row["company_id"] for row in service.members(cycle)
                     if retry_exceptions and row["status"] in {"partial", "blocked", "failed", "unsupported"}}
        service.recover(cycle)
        for member in service.members(cycle):
            retry = member["company_id"] in retry_ids
            if member["status"] != "queued" and not retry:
                continue
            if retry and member["selected_attempt_id"]:
                attempt = service._attempt(member["selected_attempt_id"])
                if attempt["apply_status"] == "quarantined":
                    continue
            attempt = service.begin_attempt(cycle, member["company_id"], retry=retry)
            try:
                service.validate_source(cycle, member["company_id"])
                inventory = fetcher(member)
            except Exception as exc:
                inventory = Inventory("failed", reason=f"Adapter raised {type(exc).__name__}; inspect this source before retrying",
                                      source_url=member["careers_url_at_start"])
            service.stage_inventory(attempt, inventory)
            service.apply_inventory(attempt)
        return service.status(cycle)
    except BaseException:
        service.interrupt(cycle)
        raise
