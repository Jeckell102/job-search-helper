from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.dsi_innovations import SOURCE, fetch_dsi_innovations


ROLE = """<section><p>DSI Innovations is growing and in search of a Controls Engineer to support various industrial automation manufacturing facility projects.</p><p>Responsibilities of the Controls Engineer Include: design and troubleshoot control systems.</p><p>Qualifications of the Controls Engineer Include: experience with PLCs and industrial networks.</p><p>Education Requirements for the Controls Engineer Include: engineering degree.</p><p>Additional role details and project responsibilities are published for this employer-scoped opening. </p>""" + ("<p>substantive role detail </p>" * 30) + """<a href="/controls-engineer-online-application-employment-opportunities-form-only/">Apply</a></section>"""
BODY = ROLE.replace("Controls Engineer", "Field Service Engineer").replace("controls-engineer", "field-service-engineer") + ROLE + ROLE.replace("Controls Engineer", "Electrical Design Engineer").replace("controls-engineer", "electrical-design-engineer")


class Pages:
    def __init__(self, *bodies, status=200):
        self.bodies = list(bodies) or [BODY]
        self.status = status
        self.calls = 0

    def get(self, url):
        body = self.bodies[min(self.calls, len(self.bodies) - 1)]
        self.calls += 1
        return HTTPResponse(self.status, body.encode(), {"content-type": "text/html"})


def test_dsi_roles_and_reread():
    pages = Pages(BODY)
    result = fetch_dsi_innovations(SOURCE, "COMP-0391", "DSI Innovations", pages)
    assert result.status == "complete"
    assert [job["title"] for job in result.jobs] == ["Controls Engineer", "Electrical Design Engineer", "Field Service Engineer"]
    assert pages.calls == 2


def test_dsi_routes_through_installed_inventory():
    result = fetch_inventory("DSI Innovations careers", SOURCE, "COMP-0391", "DSI Innovations", Pages(BODY))
    assert result.status == "complete"
    assert len(result.jobs) == 3


def test_dsi_rejects_wrong_scope_and_drift():
    assert fetch_dsi_innovations(SOURCE, "OTHER", "DSI Innovations", Pages(BODY)).status == "unsupported"
    result = fetch_dsi_innovations(SOURCE, "COMP-0391", "DSI Innovations", Pages(BODY, BODY.replace("Controls Engineer", "Senior Controls Engineer")))
    assert result.status == "partial"
