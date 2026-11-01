from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.savox import SOURCE, fetch_savox

COMPANY_ID = "COMP-0494"
COMPANY = "Savox Communications"
BUYER = "https://porkkanajakeppioy.teamtailor.com/en/jobs/8545889-buyer-savox-communications"
PLANNER = "https://porkkanajakeppioy.teamtailor.com/en/jobs/8546015-production-planner-savox-communications"


def detail(title):
    return (f"<html><body><h1>{title}</h1><p>Savox Communications designs and manufactures advanced communication solutions.</p>"
            "<p>We are now looking for this role at our Finnish factory. Responsibilities include planning, collaboration and delivery.</p>"
            "<p>Who are we looking for? Relevant experience, a practical mindset and clear communication are required.</p>"
            "<p>What Do We Offer? You will work with experienced colleagues in a supportive environment.</p>"
            "<p>How to Apply: Please submit your application via the recruitment system.</p>"
            "</body></html>").encode()


INDEX = (f"<main><h1>At Savox You are among friends</h1><h2>Open positions</h2>"
         f"<h3>Buyer</h3><a href=\"{BUYER}\">Learn more and apply</a>"
         f"<h3>Production Planner</h3><a href=\"{PLANNER}\">Learn more and apply</a></main>").encode()


class Pages:
    def __init__(self, statuses=None, second=None):
        self.pages = {SOURCE: INDEX, BUYER: detail("BUYER, SAVOX COMMUNICATIONS"),
                      PLANNER: detail("PRODUCTION PLANNER, SAVOX COMMUNICATIONS")}
        self.statuses = statuses or {}
        self.second = second
        self.calls = Counter()

    def get(self, url):
        self.calls[url] += 1
        body = self.pages.get(url, b"")
        if url == SOURCE and self.calls[url] == 2 and self.second is not None:
            body = self.second
        return HTTPResponse(self.statuses.get(url, 200), body, {})


def test_fetches_two_teamtailor_roles_and_rereads_index():
    pages = Pages()
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=pages)
    assert result.status == "complete", result.reason
    assert [job["title"] for job in result.jobs] == [
        "BUYER, SAVOX COMMUNICATIONS", "PRODUCTION PLANNER, SAVOX COMMUNICATIONS"]
    assert pages.calls[SOURCE] == 2
    assert all(len(job["description"]) >= 400 for job in result.jobs)


def test_rejects_wrong_scope_and_inventory_drift():
    assert fetch_savox(SOURCE, "OTHER", COMPANY, Pages()).status == "unsupported"
    changed = INDEX.replace(BUYER.encode(), b"https://porkkanajakeppioy.teamtailor.com/en/jobs/9999999-new-role")
    assert fetch_savox(SOURCE, COMPANY_ID, COMPANY, Pages(second=changed)).status == "partial"


def test_does_not_accept_blocked_detail():
    pages = Pages({BUYER: 403})
    assert fetch_savox(SOURCE, COMPANY_ID, COMPANY, pages).status == "blocked"
