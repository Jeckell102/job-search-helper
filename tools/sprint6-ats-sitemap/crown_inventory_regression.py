"""Run explicitly against a proposed Crown repair before live qualification."""

from collections import Counter
import unittest

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.successfactors import CROWN_SOURCE


HOST = "https://us-careers.crown.com"
SITEMAP = HOST + "/sitemap.xml"
JOBS = {
    "/job/Field-Service/10001/": "Field Service",
    "/TheGoods/job/Culinary-Associate/10002/": "Culinary Associate",
    "/17West/job/Culinary-Internship/10003/": "Culinary Internship",
}


class CrownBoard:
    def __init__(self, *, missing_description=False):
        self.calls = Counter()
        self.missing_description = missing_description

    def get(self, url):
        self.calls[url] += 1
        if url == CROWN_SOURCE:
            excerpt = list(JOBS.items())[:2]
            anchors = "".join(
                f'<a class="jobTitle-link" href="{path}">{title}</a>'
                for path, title in excerpt
            )
            return HTTPResponse(200, (anchors * 3).encode())
        if url == SITEMAP:
            locations = "".join(
                f"<url><loc>{HOST}{path}</loc></url>" for path in JOBS
            )
            return HTTPResponse(
                200,
                f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locations}</urlset>'.encode(),
            )
        title = JOBS[url.removeprefix(HOST)]
        description = (
            ""
            if self.missing_description and title == "Culinary Internship"
            else f'<div itemprop="description">Responsibilities and qualifications for {title}.</div>'
        )
        return HTTPResponse(
            200,
            (
                f'<link rel="canonical" href="{url}">'
                f'<span itemprop="title">{title}</span>{description}'
            ).encode(),
        )


class CrownInventoryRegression(unittest.TestCase):
    def test_missing_listing_total_uses_rechecked_official_membership(self):
        board = CrownBoard()
        result = fetch_inventory(
            "SuccessFactors", HOST + "/", "COMP-0588", "Crown Equipment",
            discovery_transport=board,
        )
        self.assertEqual("complete", result.status, result.reason)
        self.assertEqual({HOST + path for path in JOBS}, {job["url"] for job in result.jobs})
        self.assertTrue(all(job["description"] for job in result.jobs))
        self.assertGreaterEqual(board.calls[SITEMAP], 2)

    def test_sitemap_job_with_missing_description_stays_partial(self):
        board = CrownBoard(missing_description=True)
        result = fetch_inventory(
            "SuccessFactors", HOST + "/", "COMP-0588", "Crown Equipment",
            discovery_transport=board,
        )
        self.assertEqual("partial", result.status, result.reason)
        self.assertEqual(
            {HOST + path for path in list(JOBS)[:2]}, {job["url"] for job in result.jobs}
        )


if __name__ == "__main__":
    unittest.main()
