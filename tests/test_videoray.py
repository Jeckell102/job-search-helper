import copy
import json

import job_search_helper.ats as ats_module
import job_search_helper.discovery as discovery_module
from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.videoray import SOURCE, fetch_videoray


def response(payload):
    return HTTPResponse(200, json.dumps(payload).encode(), {"content-type": "application/json"})


def listing():
    return {"title": "Senior Electronics Engineer", "externalPath": "/job/Senior-Electronics-Engineer_1234",
            "locationsText": "Pottstown, PA", "postedOn": "Posted Today", "bulletFields": ["1234"]}


def detail():
    return {"jobPostingInfo": {"id": "opaque-1234", "jobPostingSiteId": "AVAV", "jobReqId": "1234",
            "title": "Senior Electronics Engineer", "jobDescription": "<p>Design VideoRay electronics.</p>",
            "location": "Pottstown, PA", "additionalLocations": [], "remoteType": "", "posted": True,
            "legalEntityName": "VideoRay LLC"}}


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []

    def post(self, url, payload):
        self.posts.append((url, copy.deepcopy(payload)))
        return self.responses.pop(0)

    def get(self, url):
        return self.responses.pop(0)


LOCAL_INDEX = b'''<html><body><a href="/about-us/careers/senior-electronics-engineer/">Senior Electronics Engineer</a></body></html>'''
LOCAL_DETAIL = b'''<html><h1>Senior Electronics Engineer</h1><main><p>Design VideoRay electronics.</p></main></html>'''


def test_videoray_scoped_board_returns_complete_inventory():
    transport = Transport([response({"total": 1, "jobPostings": [listing()], "facets": []}), response(detail())])
    transport.responses = [HTTPResponse(200, LOCAL_INDEX), HTTPResponse(200, LOCAL_DETAIL), *transport.responses]
    result = fetch_videoray(SOURCE, "COMP-0348", "VideoRay", transport)
    assert result.status == "complete", result.reason
    assert len(result.jobs) == 1
    assert transport.posts[0][1]["searchText"] == "VideoRay"


def test_parent_roles_require_video_ray_legal_entity_attribution():
    transport = Transport([HTTPResponse(200, LOCAL_INDEX), HTTPResponse(200, LOCAL_DETAIL),
                           response({"total": 1, "jobPostings": [listing()], "facets": []}),
                           response({"jobPostingInfo": {**detail()["jobPostingInfo"], "legalEntityName": "AeroVironment, Inc."}})])
    result = fetch_videoray(SOURCE, "COMP-0348", "VideoRay", transport)
    assert result.status == "partial"
    assert "attribution" in result.reason


def test_parent_role_accepts_explicit_segment_attribution_without_metadata():
    info = {**detail()["jobPostingInfo"],
            "jobDescription": "This position supports UXS / VideoRay products."}
    info.pop("legalEntityName")
    transport = Transport([HTTPResponse(200, LOCAL_INDEX), HTTPResponse(200, LOCAL_DETAIL),
                           response({"total": 1, "jobPostings": [listing()], "facets": []}),
                           response({"jobPostingInfo": info})])
    result = fetch_videoray(SOURCE, "COMP-0348", "VideoRay", transport)
    assert result.status == "complete", result.reason
    assert len(result.jobs) == 1


def test_local_parent_overlap_is_deduplicated_with_parent_canonical_id():
    transport = Transport([HTTPResponse(200, LOCAL_INDEX), HTTPResponse(200, LOCAL_DETAIL),
                           response({"total": 1, "jobPostings": [listing()], "facets": []}), response(detail())])
    result = fetch_videoray(SOURCE, "COMP-0348", "VideoRay", transport)
    assert result.status == "complete"
    assert len(result.jobs) == 1
    assert result.jobs[0]["posting_id"] == "opaque-1234"


def test_wrong_source_and_identity_fail_closed():
    assert fetch_videoray("https://videoray.com/about-us/careers/", "COMP-0348", "VideoRay", Transport([])).status == "unsupported"
    assert fetch_videoray(SOURCE, "OTHER", "VideoRay", Transport([])).status == "unsupported"


def test_normal_dispatch_uses_videoray_adapter():
    transport = Transport([response({"total": 0, "jobPostings": [], "facets": []})])
    transport.responses = [HTTPResponse(200, LOCAL_INDEX), HTTPResponse(200, LOCAL_DETAIL), *transport.responses]
    result = fetch_inventory("Workday (shared parent board)", SOURCE, "COMP-0348", "VideoRay", transport)
    assert result.status == "complete", result.reason
    assert result.ats == "VideoRay local + AVAV Workday"


def test_normal_dispatch_builds_separate_default_transports(monkeypatch):
    api = Transport([response({"total": 1, "jobPostings": [listing()], "facets": []}), response(detail())])
    local = Transport([HTTPResponse(200, LOCAL_INDEX), HTTPResponse(200, LOCAL_DETAIL)])
    monkeypatch.setattr(ats_module, "HTTPTransport", lambda: api)
    monkeypatch.setattr(discovery_module, "CareersTransport", lambda: local)

    result = fetch_inventory("Workday (shared parent board)", SOURCE, "COMP-0348", "VideoRay")

    assert result.status == "complete", result.reason
    assert len(result.jobs) == 1
    assert len(api.posts) == 1
    assert not local.posts
    assert not api.responses
    assert not local.responses
