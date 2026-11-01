from job_search_helper.ats import HTTPResponse
from job_search_helper.symbotic import SOURCE, fetch_symbotic


INDEX = """
<html><body><h1>Open Positions at Symbotic</h1><p>Symbotic careers and open positions for robotics and automation.</p>
<a href='/careers/jobs/R123/'>Engineer</a>
</body></html>
"""
DETAIL = "<html><body><h1>Robotics Engineer</h1><p>Symbotic is seeking an engineer.</p><p>{}</p></body></html>".format("Responsibilities and qualifications. " * 20)


class Transport:
    def __init__(self, blocked=False):
        self.blocked = blocked
        self.index_reads = 0

    def get(self, url):
        if self.blocked:
            return HTTPResponse(403, b"Cloudflare")
        if url == SOURCE:
            self.index_reads += 1
            return HTTPResponse(200, INDEX.encode())
        return HTTPResponse(200, DETAIL.encode())


def test_active_roles_are_retrieved_and_reread():
    result = fetch_symbotic(SOURCE, "COMP-0200", "Symbotic", Transport())
    assert result.status == "complete"
    assert len(result.jobs) == 1
    assert result.jobs[0]["posting_id"] == "R123"


def test_blocked_source_is_not_zero():
    result = fetch_symbotic(SOURCE, "COMP-0200", "Symbotic", Transport(blocked=True))
    assert result.status == "blocked"
    assert result.jobs == []


def test_identity_is_guarded():
    result = fetch_symbotic("https://example.com/careers/", "COMP-0200", "Symbotic", Transport())
    assert result.status == "unsupported"
