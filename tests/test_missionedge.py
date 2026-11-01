from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.missionedge import SOURCE, fetch_missionedge


CAREERS = '<a href="https://www.bringtheedge.tech/jobs/m1">Artificial Intelligence Engineer</a><a href="https://www.bringtheedge.tech/jobs/m2">Platform Engineer</a>'
DETAIL = '<main><h1>{title}</h1><p>Apply Now!</p><p>{detail}</p></main>'


class Pages:
    def __init__(self, bodies):
        self.bodies = bodies
        self.calls = 0

    def get(self, url):
        body = self.bodies[url]
        return HTTPResponse(200, body.encode(), {"content-type": "text/html"})


def pages():
    return Pages({
        SOURCE: CAREERS,
        "https://www.bringtheedge.tech/jobs/m1": DETAIL.format(title="Artificial Intelligence Engineer", detail="x" * 600),
        "https://www.bringtheedge.tech/jobs/m2": DETAIL.format(title="Platform Engineer", detail="y" * 600),
    })


def test_missionedge_roles_and_reread():
    result = fetch_missionedge(SOURCE, "COMP-0454", "MissionEdge Technologies", pages())
    assert result.status == "complete"
    assert [job["title"] for job in result.jobs] == ["Artificial Intelligence Engineer", "Platform Engineer"]
    assert all(len(job["description"]) > 500 for job in result.jobs)


def test_missionedge_routes_through_installed_inventory():
    assert fetch_inventory("MissionEdge Technologies careers", SOURCE, "COMP-0454", "MissionEdge Technologies", pages()).status == "complete"


def test_missionedge_rejects_scope_and_drift():
    assert fetch_missionedge("https://example.com/careers/", "COMP-0454", "MissionEdge Technologies", pages()).status == "unsupported"
    bad = pages()
    bad.bodies["https://www.bringtheedge.tech/jobs/m2"] = DETAIL.format(title="Changed Title", detail="z" * 600)
    assert fetch_missionedge(SOURCE, "COMP-0454", "MissionEdge Technologies", bad).status == "partial"
