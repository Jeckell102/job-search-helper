from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.polytron import SOURCE, fetch_polytron

COMPANY_ID = "COMP-0401"
COMPANY = "Polytron"
PDF = "https://polytron.com/wp-content/uploads/2026/application-engineer.pdf"


class Pages:
    def __init__(self, root, pdf, statuses=None):
        self.pages = {SOURCE: root, PDF: pdf}
        self.statuses = statuses or {}
        self.calls = Counter()

    def get(self, url):
        self.calls[url] += 1
        return HTTPResponse(self.statuses.get(url, 200), self.pages.get(url, b""), {})


def listing():
    return (b'<main><h1>Careers at Polytron</h1><h2>Open Positions</h2>'
            + f'<a href="{PDF}">Application Engineer</a></main>'.encode())


def test_fetches_official_role_pdf_and_rereads_listing(monkeypatch):
    pdf = b"%PDF fake"
    pages = Pages(listing(), pdf)
    monkeypatch.setattr("job_search_helper.polytron.shutil.which", lambda _: "/usr/bin/pdftotext")
    monkeypatch.setattr(
        "job_search_helper.polytron.subprocess.run",
        lambda *args, **kwargs: type("Result", (), {
            "stdout": b"Job Description - Application Engineer\n" + b"Responsibilities and qualifications. " * 20
        })(),
    )
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=pages)
    assert result.status == "complete", result.reason
    assert len(result.jobs) == 1
    assert result.jobs[0]["title"] == "Application Engineer"
    assert len(result.jobs[0]["description"]) > 300
    assert pages.calls[SOURCE] == 2


def test_rejects_wrong_scope_and_missing_role():
    assert fetch_polytron(SOURCE, "OTHER", COMPANY, Pages(listing(), b"pdf")).status == "unsupported"
    assert fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Pages(b"<h1>Careers at Polytron</h1>", b"pdf")).status == "partial"


def test_does_not_accept_blocked_pdf():
    pages = Pages(listing(), b"pdf", {PDF: 403})
    assert fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=pages).status == "blocked"
