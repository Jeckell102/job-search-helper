import unittest

from job_search_helper.ats import HTTPResponse, fetch_inventory


SOURCE = "https://www.hallam-ics.com/careers"
BOARD = "https://secure7.saashr.com/ta/6211585.careers?CareersSearch=&career_portal_id=4915719&ein_id=118982210&lang=en-US"
DETAIL = BOARD + "&jobid=123"
ROOT = '<a href="' + DETAIL + '">Controls Engineer</a>'
BODY = '<html><body><h1>Controls Engineer</h1><p>' + ('Complete public description. ' * 20) + '</p></body></html>'


class Pages:
    def __init__(self, root=ROOT, detail=BODY):
        self.pages = {BOARD: root, DETAIL: detail}
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return HTTPResponse(200, self.pages[url].encode())


class HallamTests(unittest.TestCase):
    def test_routes_and_rechecks_company_scoped_saashr(self):
        pages = Pages()
        result = fetch_inventory("Browser", SOURCE, "COMP-0397", "Hallam-ICS", discovery_transport=pages)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(result.ats, "SaaShr")
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(pages.calls, [BOARD, DETAIL, BOARD])

    def test_empty_or_blocked_public_board_never_closes(self):
        class Blocked:
            def get(self, url):
                return HTTPResponse(403, b"Access denied")
        result = fetch_inventory("SaaShr", SOURCE, "COMP-0397", "Hallam-ICS", discovery_transport=Blocked())
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.jobs, [])


if __name__ == "__main__":
    unittest.main()
