import unittest
from pathlib import Path

from job_search_helper.ats import HTTPResponse
from job_search_helper.peplink import fetch_peplink


SOURCE = "https://www.peplink.com/company/career/"


class CareersTransport:
    def __init__(self, body=None, *, status=200, final_body=None):
        fixture = Path(__file__).parent / "fixtures" / "peplink" / "jobs.html"
        self.body = (body if body is not None else fixture.read_bytes())
        self.status = status
        self.final_body = final_body
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        body = self.final_body if self.final_body is not None and len(self.calls) > 1 else self.body
        return HTTPResponse(self.status, body)


def with_extra_jobs(body, count=5):
    extras = []
    for index in range(1, count + 1):
        ident = f"job-overlay-{index + 4}"
        extras.append(f'''<div class="jobs-card convex-card">
          <div class="jobs-header"><h3>Synthetic Role {index}</h3><p class="jobs-location">Worldwide</p></div>
          <p>Extra role summary.</p><button class="open-overlay" data-overlay="#{ident}">View Details</button>
        </div>
        <div class="overlay" id="{ident}"><div class="overlay-body">
          <div class="jobs-header"><h3>Synthetic Role {index}</h3><p class="jobs-location">Worldwide</p></div>
          <div class="overlay-card-content"><h4>Responsibilities</h4><ul><li>Build systems.</li></ul></div>
          <div class="overlay-card-content"><h4>Requirements</h4><ul><li>Relevant experience.</li></ul></div>
        </div></div>''')
    page = body.decode()
    marker = '<div class="jobs-list">'
    return page.replace(marker, marker + "".join(extras), 1)


class PeplinkTests(unittest.TestCase):
    def test_all_four_roles_persist_separately_and_rescan_without_collisions(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        from job_search_helper.engine import Engine, State
        from job_search_helper.repository import MemoryRepository
        inventory = fetch_peplink(SOURCE, "COMP-0149", "Peplink", CareersTransport())
        self.assertEqual(inventory.status, "complete", inventory.reason)
        repo = MemoryRepository({"Companies": [{"Company": "Peplink", "Company ID": "COMP-0149",
            "Company Status": "Active", "ATS / Source": "Browser", "Official Careers URL": SOURCE}]})
        state = State()
        self.addCleanup(state.close)
        engine = Engine(repo, state, fetcher=lambda *args: inventory)
        with patch("job_search_helper.engine.classify_title", return_value="review"), redirect_stdout(StringIO()):
            for _ in range(2):
                cycle = engine.start_cycle(["COMP-0149"])
                engine.resume(cycle)
        rows = repo.read("Job History")
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({row["Job Key"] for row in rows}), 4)
        self.assertEqual(len({row["Official Job URL"] for row in rows}), 4)

    def test_captured_four_jobs_have_complete_overlay_content(self):
        transport = CareersTransport()
        result = fetch_peplink(SOURCE, "COMP-0149", "Peplink", transport)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 4)
        self.assertEqual(len({job["posting_id"] for job in result.jobs}), 4)
        self.assertTrue(all("Responsibilities" in job["description"] and
                            "Requirements" in job["description"] and
                            "?position=" in job["url"] and "#job-overlay-" in job["url"]
                            for job in result.jobs))
        self.assertEqual(transport.calls, [SOURCE, SOURCE])

    def test_five_added_cards_are_not_rejected_by_hardcoded_count(self):
        fixture = Path(__file__).parent / "fixtures" / "peplink" / "jobs.html"
        transport = CareersTransport(body=with_extra_jobs(fixture.read_bytes(), 5).encode())
        result = fetch_peplink(SOURCE, "COMP-0149", "Peplink", transport)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 9)

    def test_mapping_and_content_failures_stay_partial(self):
        fixture = Path(__file__).parent / "fixtures" / "peplink" / "jobs.html"
        original = fixture.read_bytes().decode()
        mutations = {
            "missing overlay": original.replace('data-overlay="#job-overlay-1"', 'data-overlay="#missing"', 1),
            "mismatched title": original.replace("Senior Mechanical Engineer / <br/>", "Wrong title / <br/>", 1),
            "missing requirements": original.replace("<h4>Requirements</h4>", "<h4>Other</h4>", 1),
            "duplicate mapping": original.replace('data-overlay="#job-overlay-2"', 'data-overlay="#job-overlay-1"', 1),
        }
        for name, body in mutations.items():
            with self.subTest(name=name):
                result = fetch_peplink(SOURCE, "COMP-0149", "Peplink", CareersTransport(body=body.encode()))
                self.assertEqual(result.status, "partial")

    def test_final_reread_drift_and_http_failure_stay_incomplete(self):
        fixture = Path(__file__).parent / "fixtures" / "peplink" / "jobs.html"
        changed = fixture.read_bytes().decode().replace("Worldwide", "North America", 1).encode()
        result = fetch_peplink(SOURCE, "COMP-0149", "Peplink",
                               CareersTransport(final_body=changed))
        self.assertEqual(result.status, "partial")
        self.assertEqual(fetch_peplink(SOURCE, "COMP-0149", "Peplink",
                                       CareersTransport(status=403)).status, "blocked")

    def test_exact_source_identity_guards(self):
        for url, company_id, company in [
                (SOURCE + "?country=US", "COMP-0149", "Peplink"),
                (SOURCE, "OTHER", "Peplink"),
                (SOURCE, "COMP-0149", "Other Employer"),
        ]:
            result = fetch_peplink(url, company_id, company, CareersTransport())
            self.assertEqual(result.status, "unsupported")


if __name__ == "__main__":
    unittest.main()
