import json
import copy
import re
from pathlib import Path

from job_search_helper.ats import HTTPResponse
from job_search_helper.digitalrecruiters import API, API_PATH, SOURCE, fetch_digitalrecruiters, safe_api_path
from urllib.parse import urlsplit

FIXTURES = Path(__file__).parent / "fixtures" / "exail"


def _actual_payload(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class CapturedApiTransport:
    """Replay the captured 134-job API and synthesize only the unneeded details."""
    def __init__(self, missing_detail=None):
        self.page1 = _actual_payload("listing-page-1.json")
        self.page2 = _actual_payload("listing-page-2.json")
        self.sample = _actual_payload("detail-sample.json")
        self.calls = []
        self.missing_detail = missing_detail

    def _detail(self, ident):
        if str(ident) == str(self.sample["job_ad_id"]):
            return self.sample
        item = next(x for x in self.page1["items"] + self.page2["items"]
                     if str(x["job_ad_id"]) == str(ident))
        d = copy.deepcopy(self.sample)
        d["job_ad_id"] = item["job_ad_id"]
        d["id"] = item["id"]
        d["title"] = item["title"]
        d["url"] = item["url"]
        d["jsonld"]["identifier"]["value"] = item["id"]
        d["jsonld"]["title"] = item["title"]
        return d

    def _response(self, url):
        if "job-ads/" in url and "?" in url:
            m = re.search(r"job-ads/(\d+)", url)
            if m and m.group(1) == str(self.missing_detail):
                return HTTPResponse(404, b"not found")
            return HTTPResponse(200, json.dumps(self._detail(m.group(1))).encode())
        if "job-ads?" in url:
            return HTTPResponse(200, json.dumps(self.page2 if "page=2" in url else self.page1).encode())
        return HTTPResponse(200, b"<html><title>Job offers at EXAIL</title></html>")

    def get(self, url):
        self.calls.append(("GET", url))
        return self._response(url)

    def post(self, url, payload):
        self.calls.append(("POST", url, payload))
        return self._response(url)


def test_digitalrecruiters_requires_pinned_exail_board():
    result = fetch_digitalrecruiters("https://jobs.exail.com/en/annonces?page=2", "COMP-0357", "Exail", CapturedApiTransport())
    assert result.status == "unsupported"


def test_captured_exail_api_retrieves_all_134_jobs_with_full_details():
    transport = CapturedApiTransport()
    result = fetch_digitalrecruiters(SOURCE, "COMP-0357", "Exail", transport)
    assert result.status == "complete", result.reason
    assert len(result.jobs) == 134
    assert len({job["posting_id"] for job in result.jobs}) == 134
    assert all(len(job["description"]) > 100 for job in result.jobs)
    assert any("job-ads" in call[1] for call in transport.calls)
    posts = [call for call in transport.calls if call[0] == "POST"]
    assert posts
    assert all(call[2] == {"filters": {}} for call in posts)
    assert all("domainName=jobs.exail.com" in call[1] and "locale=en_GB" in call[1] for call in posts)
    assert all(call[0] == "GET" for call in transport.calls if "/job-ads/" in call[1])


def test_captured_exail_missing_detail_is_partial_with_verified_jobs_retained():
    missing_item = _actual_payload("listing-page-1.json")["items"][1]
    missing = missing_item["job_ad_id"]
    result = fetch_digitalrecruiters(SOURCE, "COMP-0357", "Exail", CapturedApiTransport(missing))
    assert result.status == "partial"
    expected = {item["id"] for name in ("listing-page-1.json", "listing-page-2.json")
                for item in _actual_payload(name)["items"]}
    assert {job["posting_id"] for job in result.jobs} == expected - {missing_item["id"]}


def test_exail_api_allowlist_rejects_wrong_domain_duplicate_query_and_filtered_requests():
    listing = API + "?domainName=jobs.exail.com&limit=100&page=1&locale=en_GB"
    assert safe_api_path(urlsplit(listing))
    assert not safe_api_path(urlsplit(listing.replace("api.digitalrecruiters.com", "evil.example")))
    assert not safe_api_path(urlsplit(listing + "&page=1"))
    assert not safe_api_path(urlsplit(listing.replace("domainName=jobs.exail.com", "domainName=other.example")))
    detail = API + "/4559317?domainName=jobs.exail.com&locale=en_GB&external=0&withJsonld=1"
    assert safe_api_path(urlsplit(detail))
    assert not safe_api_path(urlsplit(detail + "&external=0"))
    assert not safe_api_path(urlsplit(detail.replace("/4559317?", "/4559317?domainName=jobs.exail.com&")))


def test_exail_final_listing_recheck_detects_title_drift():
    class Drifting(CapturedApiTransport):
        page1_reads = 0
        def _response(self, url):
            if "job-ads?" in url and "page=1" in url:
                self.page1_reads += 1
                if self.page1_reads > 1:
                    self.page1 = copy.deepcopy(self.page1)
                    self.page1["items"][0]["title"] += " changed"
            return super()._response(url)
    result = fetch_digitalrecruiters(SOURCE, "COMP-0357", "Exail", Drifting())
    assert result.status == "partial"
    assert "changed" in result.reason.lower() or "listing" in result.reason.lower()


def test_exail_detail_identity_and_profile_corruption_is_partial():
    class Corrupt(CapturedApiTransport):
        def _detail(self, ident):
            d = super()._detail(ident)
            if str(ident) == str(self.page1["items"][0]["job_ad_id"]):
                d["brand_name"] = "Other Employer"
            elif str(ident) == str(self.page1["items"][1]["job_ad_id"]):
                d["profile"] = None
            return d
    result = fetch_digitalrecruiters(SOURCE, "COMP-0357", "Exail", Corrupt())
    assert result.status == "partial"
    assert len(result.jobs) <= 132


def test_exail_empty_profile_is_allowed_but_missing_profile_is_not():
    class EmptyProfile(CapturedApiTransport):
        def _detail(self, ident):
            d = super()._detail(ident)
            d["profile"] = ""
            return d
    result = fetch_digitalrecruiters(SOURCE, "COMP-0357", "Exail", EmptyProfile())
    assert result.status == "complete"
    assert len(result.jobs) == 134


def test_exail_http_transport_rejects_filtered_post_and_posting_to_details():
    import unittest
    from job_search_helper.ats import FetchError, HTTPTransport, _safe_api_url
    listing = API + "?domainName=jobs.exail.com&limit=100&page=1&locale=en_GB"
    detail = API + "/4559317?domainName=jobs.exail.com&locale=en_GB&external=0&withJsonld=1"
    for url, payload in ((listing, {"filters": {"job": ["engineering"]}}),
                         (listing, {"filters": {}, "extra": True}),
                         (detail, {"filters": {}})):
        with unittest.TestCase().assertRaises(FetchError):
            HTTPTransport().post(url, payload)
    for url in (listing + "&search=secret", listing.replace("/public/", "/private/"),
                listing.replace("https:", "http:"), listing + "#untrusted"):
        with unittest.TestCase().assertRaises(FetchError):
            _safe_api_url(url)


def test_exail_final_second_page_change_and_truncated_page_are_incomplete():
    class SecondPage(CapturedApiTransport):
        reads = 0
        def _response(self, url):
            if "job-ads?" in url and "page=2" in url:
                self.reads += 1
                if self.reads > 1:
                    self.page2 = copy.deepcopy(self.page2)
                    self.page2["items"][0]["title"] += " changed"
            return super()._response(url)
    assert fetch_digitalrecruiters(SOURCE, "COMP-0357", "Exail", SecondPage()).status == "partial"
    transport = CapturedApiTransport()
    transport.page2["items"] = transport.page2["items"][:-1]
    assert fetch_digitalrecruiters(SOURCE, "COMP-0357", "Exail", transport).status == "partial"
