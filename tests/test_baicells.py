from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.baicells import COMPANY_ID, COMPANY, SOURCE, fetch_baicells


ROLE_1 = "Global Sales Manager (Fully-Remote)"
ROLE_2 = "Project Delivery Engineer (Based in Dushanbe, Tajikistan)"


class Pages:
    def __init__(self, root, second=None, status=200):
        self.pages = [root, second if second is not None else root]
        self.status = status
        self.calls = Counter()

    def get(self, url):
        self.calls[url] += 1
        index = min(self.calls[url] - 1, 1)
        return HTTPResponse(self.status, self.pages[index].encode(), {"content-type": "text/html"})


def page(*roles):
    panels = "".join(
        f'<div class="panel panel-default"><div class="panel-heading"><h5><a role="button" data-toggle="collapse">{title}</a></h5></div>'
        f'<div class="panel-body"><div class="content"><p>Job Description:</p><p>{body}</p></div></div></div>'
        for title, body in roles
    )
    return f"<html><title>Careers</title><body><h1>Baicells Careers</h1>{panels}</body></html>"


def test_extracts_complete_accordion_roles_and_dispatches():
    root = page((ROLE_1, "Develop global regional markets. " * 20), (ROLE_2, "Maintain network equipment. " * 20))
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Pages(root))
    assert result.status == "complete", result.reason
    assert [job["title"] for job in result.jobs] == [ROLE_1, ROLE_2]
    assert "Develop global regional markets" in result.jobs[0]["description"]
    assert result.jobs[0]["posting_id"].startswith("baicells-")


def test_reread_dedup_and_fail_closed_cases():
    root = page((ROLE_1, "Develop global regional markets. " * 20))
    changed = page((ROLE_1, "Changed description. " * 20))
    assert fetch_baicells(SOURCE, COMPANY_ID, COMPANY, Pages(root, changed)).status == "partial"
    duplicate = page((ROLE_1, "Description. " * 20), (ROLE_1, "Description. " * 20))
    assert fetch_baicells(SOURCE, COMPANY_ID, COMPANY, Pages(duplicate)).status == "partial"
    assert fetch_baicells(SOURCE, COMPANY_ID, COMPANY, Pages(root, status=403)).status == "blocked"
    assert fetch_baicells(SOURCE, "OTHER", COMPANY, Pages(root)).status == "unsupported"


def test_blank_silent_shell_and_short_role_fail_closed():
    assert fetch_baicells(SOURCE, COMPANY_ID, COMPANY, Pages("<html></html>")).status == "partial"
    short = page((ROLE_1, "too short"))
    assert fetch_baicells(SOURCE, COMPANY_ID, COMPANY, Pages(short)).status == "partial"
