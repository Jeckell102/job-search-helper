import json

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.company_sources import repair_source


OFFICIAL = "https://www.righthandrobotics.com/careers"
BOARD = "https://righthand-robotics.breezy.hr/"
DETAIL = BOARD + "p/0123456789ab-robotics-engineer"
FEED = [{
    "id": "0123456789ab",
    "friendly_id": "0123456789ab-robotics-engineer",
    "name": "Robotics Engineer",
    "url": DETAIL,
    "published_date": "2026-11-17T00:00:00.000Z",
    "company": {"friendly_id": "righthand-robotics"},
    "department": "Engineering",
    "location": {"name": "Boston, MA", "is_remote": False},
    "locations": [{"name": "Boston, MA", "is_remote": False}],
    "salary": "",
}]
DETAIL_PAGE = "<script type='application/ld+json'>" + json.dumps([{
    "@type": "JobPosting",
    "url": DETAIL,
    "title": "Robotics Engineer",
    "description": "<p>Build and support production robotics systems.</p>",
}]) + "</script>"


class Board:
    def __init__(self):
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        body = FEED if url == BOARD + "json" else DETAIL_PAGE
        return HTTPResponse(200, json.dumps(body).encode() if isinstance(body, list) else body.encode())


def test_official_careers_source_repairs_to_employer_scoped_breezy_board():
    result = fetch_inventory("Official careers", OFFICIAL, "COMP-0710", "RightHand Robotics", transport=Board())
    assert result.status == "complete", result.reason
    assert len(result.jobs) == 1
    assert result.jobs[0]["url"] == DETAIL
    assert result.jobs[0]["description"]


def test_only_documented_official_careers_aliases_are_repaired():
    ats, board, note = repair_source("Official careers", "https://righthandrobotics.com/careers/", "COMP-0710", "RightHand Robotics")
    assert (ats, board) == ("Breezy HR", BOARD)
    assert note.startswith("Verified company source repair:")
    assert repair_source("Official careers", "https://unrelated.example/careers", "COMP-0710", "RightHand Robotics") == (
        "Official careers", "https://unrelated.example/careers", "",
    )
