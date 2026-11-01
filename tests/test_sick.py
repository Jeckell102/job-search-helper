import json

from job_search_helper.sick import SEARCH, SOURCE, fetch_sick


def detail(title):
    return f'<html><span itemprop="title">{title}</span><div itemprop="description"><p>Complete description for {title}</p></div></html>'.encode()


class Fake:
    def __init__(self):
        self.posts = []
        self.gets = []
        self.rows = [
            {"id": "1001", "unifiedStandardTitle": "USA One", "unifiedUrlTitle": "USA-One", "brandUrl": "usa", "supportedLocales": ["en_US"]},
            {"id": "1002", "unifiedStandardTitle": "Germany One", "unifiedUrlTitle": "Germany-One", "brandUrl": "germany", "supportedLocales": ["de_DE"]},
            {"id": "1003", "unifiedStandardTitle": "USA Two", "unifiedUrlTitle": "USA-Two", "brandUrl": "usa", "supportedLocales": ["en_US"]},
        ]

    def post(self, url, payload):
        self.posts.append((url, payload))
        page = payload["pageNumber"]
        rows = self.rows if page == 0 else []
        return type("Response", (), {"status": 200, "body": json.dumps({"totalJobs": 3, "jobSearchResult": [{"response": r} for r in rows]}).encode()})()

    def get(self, url):
        self.gets.append(url)
        title = "USA One" if url.endswith("1001-en_US/") else "USA Two"
        return type("Response", (), {"status": 200, "body": detail(title)})()


def test_sick_filters_global_successfactors_results_to_usa_and_validates_reread():
    fake = Fake()
    result = fetch_sick(SOURCE, "COMP-0272", "SICK", fake)
    assert result.status == "complete"
    assert [job["posting_id"] for job in result.jobs] == ["1001", "1003"]
    assert len(fake.gets) == 2
    assert all(call[0] == SEARCH and call[1]["sortBy"] == "date" for call in fake.posts)


def test_sick_rejects_wrong_source():
    result = fetch_sick("https://jobs.sick.com/usa", "COMP-0272", "SICK", Fake())
    assert result.status == "unsupported"
