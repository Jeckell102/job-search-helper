from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.company_sources import repair_source
from job_search_helper.ierus import (
    CAREERS_SOURCE,
    FEED_SOURCE,
    LEGACY_FEED_SOURCE,
    fetch_ierus,
)


FEED = """<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'>
<entry><id>job-1</id><title>RF Engineer</title><link href='https://careers.jobscore.com/careers/ierustechnologiesinc/jobs/rf-engineer-job-1'/>
<content type='html'>&lt;p&gt;Responsibilities and qualifications for RF engineering.&lt;/p&gt;</content><category scheme='http://schemas.jobscore.com/atom#department' term='Engineering'/><category scheme='http://schemas.jobscore.com/atom#location' term='Huntsville, AL'/></entry>
<entry><id>job-2</id><title>Systems Engineer</title><link href='https://careers.jobscore.com/careers/ierustechnologiesinc/jobs/systems-engineer-job-2'/>
<content type='html'>&lt;p&gt;Responsibilities and qualifications for systems engineering.&lt;/p&gt;</content><category scheme='http://schemas.jobscore.com/atom#location' term='Remote'/></entry>
</feed>"""


class Feed:
    def __init__(self, body=FEED, status=200):
        self.body = body.encode()
        self.status = status
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return HTTPResponse(self.status, self.body, {"content-type": "application/atom+xml"})


def test_retrieves_and_rereads_employer_scoped_feed():
    feed = Feed()
    result = fetch_inventory("Browser", CAREERS_SOURCE, "COMP-0449", "IERUS Technologies", transport=feed)
    assert result.status == "complete"
    assert len(result.jobs) == 2
    assert all(job["description"] for job in result.jobs)
    assert result.jobs[0]["department"] == "Engineering"
    assert result.jobs[0]["location"] == "Huntsville, AL"
    assert feed.calls == [FEED_SOURCE, FEED_SOURCE]


def test_rejects_wrong_scope():
    result = fetch_ierus(FEED_SOURCE, "COMP-0449", "Other Company", Feed())
    assert result.status == "unsupported"


def test_accepts_legacy_feed_alias_but_reads_the_canonical_feed():
    feed = Feed()
    result = fetch_ierus(LEGACY_FEED_SOURCE, "COMP-0449", "IERUS Technologies", feed)
    assert result.status == "complete"
    assert feed.calls == [FEED_SOURCE, FEED_SOURCE]


def test_source_repair_canonicalizes_each_trusted_feed_alias():
    for source in (CAREERS_SOURCE, FEED_SOURCE, LEGACY_FEED_SOURCE):
        ats, repaired, note = repair_source("Browser", source, "COMP-0449", "IERUS Technologies")
        assert (ats, repaired) == ("JobScore", FEED_SOURCE)
        assert note.startswith("Verified company source repair:")


def test_rejects_detail_url_outside_the_canonical_tenant():
    body = FEED.replace("https://careers.jobscore.com/careers/", "https://hire.jobscore.com/careers/")
    result = fetch_ierus(FEED_SOURCE, "COMP-0449", "IERUS Technologies", Feed(body=body))
    assert result.status == "partial"


def test_rejects_a_canonical_host_with_an_untrusted_port():
    body = FEED.replace("https://careers.jobscore.com/", "https://careers.jobscore.com:444/")
    result = fetch_ierus(FEED_SOURCE, "COMP-0449", "IERUS Technologies", Feed(body=body))
    assert result.status == "partial"


def test_removes_only_jobscore_feed_tracking_parameters():
    body = FEED.replace(
        "rf-engineer-job-1'", "rf-engineer-job-1?ref=rss&amp;sid=68'",
    )
    result = fetch_ierus(FEED_SOURCE, "COMP-0449", "IERUS Technologies", Feed(body=body))
    assert result.status == "complete"
    assert result.jobs[0]["url"].endswith("/rf-engineer-job-1")


def test_fails_closed_when_the_feed_advertises_an_unread_page():
    body = FEED.replace("<entry>", "<link rel='next' href='https://careers.jobscore.com/jobs/ierustechnologiesinc/feed.atom?page=2'/><entry>", 1)
    result = fetch_ierus(FEED_SOURCE, "COMP-0449", "IERUS Technologies", Feed(body=body))
    assert result.status == "partial"


def test_feed_failure_is_not_empty_completion():
    result = fetch_ierus(FEED_SOURCE, "COMP-0449", "IERUS Technologies", Feed(status=503))
    assert result.status == "partial"
    assert result.jobs == []
