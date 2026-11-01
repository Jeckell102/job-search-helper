from job_search_helper.ats import HTTPResponse
from job_search_helper.ycombinator import SOURCE, fetch_ycombinator


class Transport:
    def __init__(self, body): self.body = body
    def get(self, url): return HTTPResponse(200, self.body.encode())


def test_explicit_empty_company_inventory_is_complete():
    body = "Jobs at Surtr Defense Systems No jobs at Surtr Defense Systems are currently posted on the YC platform."
    result = fetch_ycombinator(SOURCE, "COMP-0323", "Surtr Defense Systems", Transport(body))
    assert result.status == "complete"
    assert result.jobs == []


def test_nonempty_unstable_inventory_fails_closed():
    result = fetch_ycombinator(SOURCE, "COMP-0323", "Surtr Defense Systems", Transport("Company Jobs 1"))
    assert result.status == "unsupported"
