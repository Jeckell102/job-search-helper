import copy
import json

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.gdit import ROOT, SOURCE, fetch_gdit


def resp(value, status=200):
    return HTTPResponse(status, json.dumps(value).encode(), {})


def listing(i):
    return {"id": f"opaque-{i}", "externalPath": f"/job/GDIT-{i}", "title": f"Role {i}",
            "jobReqId": f"R{i}", "locationsText": "Falls Church, VA"}


def detail(i):
    return {"jobPostingInfo": {"id": f"opaque-{i}", "jobPostingSiteId": "External_Career_Site",
        "jobReqId": f"R{i}", "title": f"Role {i}",
        "jobDescription": "This complete public GDIT description covers responsibilities, qualifications, collaboration, and the work environment. " * 2,
        "location": "Falls Church, VA", "additionalLocations": [], "posted": True}}


class Transport:
    def __init__(self, responses): self.responses, self.posts, self.gets = list(responses), [], []
    def post(self, url, payload): self.posts.append((url, copy.deepcopy(payload))); return self.responses.pop(0)
    def get(self, url): self.gets.append(url); return self.responses.pop(0)


def board(i=1):
    return {"total": 1, "jobPostings": [listing(i)], "facets": []}


def test_gdit_complete_and_dispatch(tmp_path):
    responses = [resp(board()), resp(detail(1)), resp(board()), resp(board()), resp(detail(1)), resp(board())]
    t = Transport(responses)
    result = fetch_inventory("Workday", SOURCE, "COMP-0011", "General Dynamics Information Technology", t)
    assert result.status == "complete", result.reason
    assert result.jobs[0]["description"]
    assert t.posts[0][0] == ROOT + "/jobs"


def test_gdit_checkpoint_resumes_detail_progress(tmp_path):
    path = tmp_path / "progress.json"
    t = Transport([resp(board()), resp(detail(1)), resp(board())])
    result = fetch_gdit(SOURCE, "COMP-0011", "General Dynamics Information Technology", t, path)
    assert result.status == "complete"
    saved = json.loads(path.read_text())
    assert saved["phase"] == "complete" and saved["ids"] == ["/job/GDIT-1"]


def test_gdit_access_error_is_not_closed(tmp_path):
    t = Transport([resp(board()), HTTPResponse(403, b"", {})])
    result = fetch_gdit(SOURCE, "COMP-0011", "General Dynamics Information Technology", t, tmp_path / "p.json")
    assert result.status == "blocked"


def test_gdit_closed_detail_is_not_silent(tmp_path):
    t = Transport([resp(board()), HTTPResponse(404, b"", {}), resp(board())])
    result = fetch_gdit(SOURCE, "COMP-0011", "General Dynamics Information Technology", t, tmp_path / "p.json")
    assert result.status == "partial"
    assert "closed ID" in result.reason or "cover" in result.reason
