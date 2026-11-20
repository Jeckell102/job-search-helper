from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.scythe_robotics import SOURCE, fetch_scythe_robotics

COMPANY_ID = "COMP-0506"
COMPANY = "Scythe Robotics"


class Pages:
    def __init__(self, body):
        self.body = body.encode()
        self.calls = 0

    def get(self, url):
        self.calls += 1
        return HTTPResponse(200, self.body, {"content-type": "text/html"})


def test_explicit_zero_openings_is_complete_and_rechecked():
    page = Pages("<html><title>Scythe Robotics Careers</title><main>"
                 "<h1>Scythe Robotics Careers</h1>"
                 "<p>No positions available at this time</p></main></html>")
    result = fetch_scythe_robotics(SOURCE, COMPANY_ID, COMPANY, page)
    assert result.status == "complete", result.reason
    assert result.jobs == []
    assert page.calls == 2


def test_routed_inventory_uses_scythe_adapter():
    page = Pages("<html><title>Scythe Robotics Careers</title><main>"
                 "<h1>Scythe Robotics Careers</h1>"
                 "<p>No positions available at this time</p></main></html>")
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=page)
    assert result.status == "complete", result.reason
    assert result.ats == "Dover careers"


def test_identity_mismatch_fails_closed():
    result = fetch_scythe_robotics(SOURCE, COMPANY_ID, "Other Company", Pages("valid"))
    assert result.status == "unsupported"


def test_dover_paginates_and_rereads_full_detail_pages():
    first = """<html><title>Scythe Robotics Careers</title><h1>Scythe Robotics Careers</h1>
    <a href='/Scythe%20Robotics/careers/11111111-1111-1111-1111-111111111111/autonomy-engineer'>Autonomy Engineer</a>
    <a href='/jobs/scytherobotics?page=2'>Next</a></html>"""
    second = """<html><title>Scythe Robotics Careers</title><h1>Scythe Robotics Careers</h1>
    <a href='/Scythe%20Robotics/careers/22222222-2222-2222-2222-222222222222/field-technician'>Field Technician</a></html>"""
    detail_a = """<html><title>Autonomy Engineer | Scythe Robotics</title><h1>Autonomy Engineer</h1>
    <p>Scythe Robotics careers description: build and validate autonomous mowing systems with the engineering team. This is the complete public role description.</p></html>"""
    detail_b = """<html><title>Field Technician | Scythe Robotics</title><h1>Field Technician</h1>
    <p>Scythe Robotics careers description: deploy, service, and test autonomous commercial equipment in the field. This is the complete public role description.</p></html>"""

    class Pages:
        def __init__(self):
            self.calls = []
            self.body = {
                SOURCE: first,
                SOURCE + "?page=2": second,
                "https://app.dover.com/Scythe%20Robotics/careers/11111111-1111-1111-1111-111111111111/autonomy-engineer": detail_a,
                "https://app.dover.com/Scythe%20Robotics/careers/22222222-2222-2222-2222-222222222222/field-technician": detail_b,
            }

        def get(self, url):
            self.calls.append(url)
            return HTTPResponse(200, self.body[url].encode(), {"content-type": "text/html"})

    pages = Pages()
    result = fetch_scythe_robotics(SOURCE, COMPANY_ID, COMPANY, pages)
    assert result.status == "complete", result.reason
    assert [job["title"] for job in result.jobs] == ["Autonomy Engineer", "Field Technician"]
    assert all(len(job["description"]) > 100 for job in result.jobs)
    assert pages.calls.count(SOURCE) == 2
    assert pages.calls.count(SOURCE + "?page=2") == 2
