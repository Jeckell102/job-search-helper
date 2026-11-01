import json
import unittest

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.brassring import fetch_brassring


SOURCE = "https://sjobs.brassring.com/TGNewUI/Search/Home/Home?partnerid=25539&siteid=5313"


def entry(req, title, department, description):
    return {"Link": "https://sjobs.brassring.com/TGnewUI/Search/home/HomeWithPreLoad?partnerid=25539&siteid=5313&PageType=JobDetails&jobid=" + req,
            "Questions": [{"QuestionName": "reqid", "Value": req}, {"QuestionName": "jobtitle", "Value": title},
                          {"QuestionName": "department", "Value": department}, {"QuestionName": "jobdescription", "Value": description},
                          {"QuestionName": "formtext4", "Value": "California"}, {"QuestionName": "formtext5", "Value": "Poway"}]}


class PublicBoard:
    def __init__(self, entries):
        self.entries = entries
        self.posts = 0

    def get(self, url):
        return HTTPResponse(200, b'<input id="__RequestVerificationToken" value="token"><input id="CookieValue" value="session">')

    def post(self, endpoint, data, token):
        self.posts += 1
        return HTTPResponse(200, json.dumps({"JobsCount": len(self.entries), "Jobs": {"Job": self.entries}}).encode())


class BrassRingTests(unittest.TestCase):
    def test_gaasi_uses_exact_published_department_partition(self):
        board = PublicBoard([entry("1", "ASI engineer", "General Atomics Aeronautical Systems", "Build aircraft."),
                             entry("2", "Parent role", "General Atomics", "Other work.")])
        result = fetch_brassring(SOURCE, "COMP-0072", "General Atomics Aeronautical Systems", board)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual([job["posting_id"] for job in result.jobs], ["1"])
        self.assertEqual(result.jobs[0]["department"], "General Atomics Aeronautical Systems")
        self.assertEqual(board.posts, 2)  # initial listing plus stability recheck

    def test_gaasi_rejects_a_listing_without_a_published_department(self):
        board = PublicBoard([entry("1", "Unknown role", "", "Build aircraft.")])
        result = fetch_brassring(SOURCE, "COMP-0072", "General Atomics Aeronautical Systems", board)
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.jobs, [])

    def test_fetch_inventory_passes_the_public_transport_to_brassring(self):
        board = PublicBoard([entry("1", "ASI engineer", "General Atomics Aeronautical Systems", "Build aircraft.")])
        result = fetch_inventory("BrassRing", SOURCE, "COMP-0072", "General Atomics Aeronautical Systems", board)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 1)
