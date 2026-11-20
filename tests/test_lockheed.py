import json
from pathlib import Path

from job_search_helper.lockheed import COMPANY_ID, COMPANY, ROOT, scan


def listing(i):
    ident = str(700000 + i)
    return {"id": ident, "name": f"Lockheed Role {i}", "displayJobId": f"LM-{i}",
            "positionUrl": f"/careers/job/{ident}"}


def detail(entry):
    return {**entry, "publicUrl": ROOT + entry["positionUrl"],
            "jobDescription": "x" * 140, "standardizedLocations": ["Bethesda, MD"],
            "department": "Engineering", "workLocationOption": "Hybrid"}


class Client:
    def __init__(self, pages, details):
        self.pages, self.details = pages, details
        self.total = len(pages[0]) + (len(pages[1]) if len(pages) > 1 else 0)
        self.calls = []
    def search(self, start):
        self.calls.append(("search", start))
        return {"count": self.total, "positions": self.pages[len([c for c in self.calls if c[0] == "search"]) - 1], "appliedFilters": {}}
    def detail(self, ident):
        self.calls.append(("detail", ident)); return self.details[ident]


def test_exhaustion_and_reconciliation(tmp_path):
    entries = [listing(i) for i in range(11)]
    pages = [entries[:10], entries[10:], entries[:10], entries[10:]]
    result = scan(Client(pages, {e["id"]: detail(e) for e in entries}), checkpoint_path=tmp_path / "c.json")
    assert result.status == "complete"
    assert len(result.jobs) == 11
    assert len(result.jobs) == len({j["posting_id"] for j in result.jobs})


def test_missing_detail_does_not_complete(tmp_path):
    entries = [listing(0)]
    bad = {**detail(entries[0]), "jobDescription": "short"}
    result = scan(Client([entries, entries], {entries[0]["id"]: bad}), checkpoint_path=tmp_path / "c.json")
    assert result.status == "partial"
    assert json.loads((tmp_path / "c.json").read_text())["phase"] == "details"


def test_interrupted_resume_uses_saved_details(tmp_path):
    entries = [listing(i) for i in range(2)]
    path = tmp_path / "c.json"
    first = Client([entries], {entries[0]["id"]: detail(entries[0]), entries[1]["id"]: detail(entries[1])})
    # A client that fails on the second detail leaves an atomic checkpoint.
    class Interrupt(Client):
        def detail(self, ident):
            if ident == entries[1]["id"]: raise RuntimeError("interrupt")
            return super().detail(ident)
    assert scan(Interrupt([entries], first.details), checkpoint_path=path).status == "partial"
    resumed = Client([entries, entries], first.details)
    resumed.total = len(entries)
    assert scan(resumed, checkpoint_path=path).status == "complete"
    assert [c for c in resumed.calls if c[0] == "detail"] == [("detail", entries[1]["id"])]


def test_listing_checkpoint_keeps_observed_pages_on_interruption(tmp_path):
    entries = [listing(i) for i in range(11)]
    path = tmp_path / "c.json"

    class InterruptedListing(Client):
        def search(self, start):
            if start == 10:
                raise RuntimeError("browser context closed")
            return super().search(start)

    result = scan(InterruptedListing([entries[:10], entries[10:]], {}), checkpoint_path=path)
    saved = json.loads(path.read_text())
    assert result.status == "partial"
    assert saved["phase"] == "listing"
    assert saved["total"] == 11
    assert len(saved["entries"]) == 10
    assert saved["ids"] == [] and saved["jobs"] == []


def test_scope_and_route_are_company_specific():
    from job_search_helper.lockheed import fetch_lockheed
    assert fetch_lockheed("https://other.eightfold.ai/careers", COMPANY_ID, COMPANY).status == "unsupported"
    assert fetch_lockheed("https://lockheedmartin.eightfold.ai/careers?query=x", COMPANY_ID, COMPANY).status == "unsupported"
