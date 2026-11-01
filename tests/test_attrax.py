from job_search_helper.ats import HTTPResponse
from job_search_helper.attrax import SOURCE, fetch_attrax


class Transport:
    def __init__(self):
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if url == SOURCE + "?page=1&size=48":
            return HTTPResponse(200, ("<html><body><b>3 result(s)</b>"
                "<a href='/job/alpha-jid-1'>Alpha</a>"
                "<a href='/job/beta-jid-2'>Beta</a></body></html>").encode())
        if url == SOURCE + "?page=2&size=48":
            return HTTPResponse(200, ("<html><body><b>3 result(s)</b>"
                "<a href='/job/gamma-jid-3'>Gamma</a></body></html>").encode())
        if "/job/" in url:
            title = url.rsplit("/", 1)[-1].split("-jid-", 1)[0].title()
            return HTTPResponse(200, (f"<html><body><h1>{title}</h1>"
                "This is a sufficiently long public job description with responsibilities, "
                "requirements, and location information for validation.</body></html>").encode())
        raise AssertionError(url)


def test_attrax_paginates_details_and_rechecks():
    transport = Transport()
    result = fetch_attrax(SOURCE, "COMP-0477", "Wabtec", transport)
    assert result.status == "complete"
    assert len(result.jobs) == 3
    assert {job["posting_id"] for job in result.jobs} == {"1", "2", "3"}
    assert result.ats == "SmartRecruiters Attrax"


def test_attrax_requires_pinned_source():
    result = fetch_attrax("https://careers.wabtec.com/", "COMP-0477", "Wabtec", Transport())
    assert result.status == "unsupported"
