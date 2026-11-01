from job_search_helper.ats import fetch_inventory
from job_search_helper.caterpillar import XML_SOURCE


class FakeTransport:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    def get(self, url):
        assert url == XML_SOURCE
        return type("Response", (), {"status": self.status, "body": self.body})()


XML = b'''<?xml version="1.0"?><jobs><job><id>r0001</id><title>Senior Engineer</title><url>https://careers.caterpillar.com/en/jobs/r0001/senior-engineer/</url><description>Build things.</description><location>Peoria, Illinois</location></job><job><id>r0001</id><title>Duplicate</title><url>https://careers.caterpillar.com/en/jobs/r0001/duplicate/</url></job></jobs>'''


def test_caterpillar_parses_employer_scoped_xml_and_deduplicates_ids():
    result = fetch_inventory("Browser", "https://careers.caterpillar.com/", "COMP-0238", "Caterpillar", FakeTransport(XML))
    assert result.status == "complete"
    assert len(result.jobs) == 1
    assert result.jobs[0]["req_id"] == "r0001"
    assert result.jobs[0]["ats"] == "Caterpillar Careers"


def test_caterpillar_http_block_does_not_infer_zero_jobs():
    result = fetch_inventory("Browser", "https://careers.caterpillar.com/", "COMP-0238", "Caterpillar", FakeTransport(b"", 403))
    assert result.status == "blocked"
    assert not result.jobs
    assert "HTTP 403" in result.reason
