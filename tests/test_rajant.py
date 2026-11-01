from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.rajant import SOURCE, COMPANY_ID, COMPANY, fetch_rajant

PDF = "https://rajant.com/wp-content/uploads/2026/10/role.pdf"


class Pages:
    def __init__(self, root, pdf, statuses=None):
        self.pages = {SOURCE: root, PDF: pdf}
        self.statuses = statuses or {}
        self.calls = Counter()

    def get(self, url):
        self.calls[url] += 1
        return HTTPResponse(self.statuses.get(url, 200), self.pages.get(url, b""), {})


def listing():
    return (b'<main><h1>Join Rajant</h1><h2>Current Openings</h2>'
            + f'<a href="{PDF}">Read More</a></main>'.encode())


def test_fetches_official_role_pdf_and_rereads_listing(monkeypatch):
    pages = Pages(listing(), b"%PDF fake")
    monkeypatch.setattr("job_search_helper.rajant.shutil.which", lambda _: "/usr/bin/pdftotext")
    monkeypatch.setattr(
        "job_search_helper.rajant.subprocess.run",
        lambda *args, **kwargs: type("Result", (), {
            "stdout": b"Digital Marketing & Content Intern - Malvern, PA\nRajant Corporation\n" + b"Responsibilities and qualifications. " * 20
        })(),
    )
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=pages)
    assert result.status == "complete", result.reason
    assert len(result.jobs) == 1
    assert "Rajant" in result.jobs[0]["description"]
    assert pages.calls[SOURCE] == 2


def test_rejects_wrong_scope_and_missing_role():
    assert fetch_rajant(SOURCE, "OTHER", COMPANY, Pages(listing(), b"pdf")).status == "unsupported"
    assert fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY,
                           discovery_transport=Pages(b"<h1>Join Rajant</h1>", b"pdf")).status == "partial"


def test_does_not_accept_blocked_source_or_pdf():
    assert fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY,
                           discovery_transport=Pages(listing(), b"pdf", {SOURCE: 403})).status == "blocked"
    assert fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY,
                           discovery_transport=Pages(listing(), b"pdf", {PDF: 403})).status == "blocked"
