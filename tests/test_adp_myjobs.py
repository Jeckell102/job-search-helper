import json
import unittest
from urllib.parse import parse_qs, urlsplit

from job_search_helper.adp_myjobs import API, SITE, fetch_adp_myjobs, resolve_adp_myjobs, repair_saved_urls
from job_search_helper.core import canonicalize_url
from job_search_helper.ats import HTTPResponse, fetch_inventory


URL = SITE + "/kearfott"
TOKEN = "A" * 40


def response(value):
    return HTTPResponse(200, json.dumps(value).encode())


def detail(number):
    return {"jobRequisitions": [{"itemID": str(number), "requisitionTitle": f"Engineer {number}",
             "clientRequisitionID": f"REQ-{number}", "requisitionDescription": "<p>Build reliable systems.</p>",
             "requisitionLocations": [{"nameCode": {"shortName": "Pine Brook, NJ"}}]}]}


class Transport:
    def __init__(self, listing):
        self.listing = listing
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return response({"myJobsToken": TOKEN})

    def get_with_headers(self, url, headers):
        self.urls.append(url)
        self.assert_headers(headers)
        if "/search-meta/" in url:
            return response(detail(url.rsplit("/", 1)[-1]))
        return response(self.listing(url))

    @staticmethod
    def assert_headers(headers):
        assert headers["myJobsToken"] == TOKEN
        assert headers["rolecode"] == "manager"


class AdpMyJobsTests(unittest.TestCase):
    def test_resolves_only_exact_public_site(self):
        self.assertEqual(resolve_adp_myjobs("ADP", URL + "/"), "kearfott")
        for bad in (URL + "?x=1", "https://myjobs.adp.com/kearfott/jobs", "https://my.adp.com/kearfott"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    resolve_adp_myjobs("ADP", bad)

    def test_fetches_complete_stable_inventory_and_full_details(self):
        def listing(url):
            offset = int(parse_qs(urlsplit(url).query)["$skip"][0])
            rows = [{"reqId": "1"}, {"reqId": "2"}][offset:offset + 20]
            return {"count": 2, "jobRequisitions": rows}
        t = Transport(listing)
        result = fetch_adp_myjobs("ADP", URL, "C-1", "Kearfott", t)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual([job["req_id"] for job in result.jobs], ["REQ-1", "REQ-2"])
        self.assertEqual(result.jobs[0]["location"], "Pine Brook, NJ")
        self.assertIn("Build reliable systems.", result.jobs[0]["description"])
        self.assertEqual(result.jobs[0]['url'], URL + '/cx/job-details?reqId=1')
        self.assertEqual(len({canonicalize_url(job['url']) for job in result.jobs}), 2)
        self.assertEqual(len([url for url in t.urls if "apply-custom-filters" in url]), 2)

    def test_legacy_saved_links_repair_without_mutating_evidence_or_other_adapters(self):
        jobs = [{'ats': 'ADP MyJobs', 'posting_id': '1', 'url': URL, 'description': 'Saved evidence'},
                {'ats': 'Browser', 'posting_id': '2', 'url': URL},
                {'ats': 'ADP MyJobs', 'posting_id': '3', 'url': SITE + '/other'},
                {'ats': 'ADP MyJobs', 'posting_id': '', 'url': URL}]
        payload = {'source_url': URL, 'jobs': jobs, 'fetched_at': 'original'}
        repaired = repair_saved_urls(payload)
        self.assertEqual(repaired['jobs'][0]['url'], URL + '/cx/job-details?reqId=1')
        self.assertEqual(jobs[0]['url'], URL)
        self.assertEqual(repaired['jobs'][0]['description'], 'Saved evidence')
        self.assertEqual(repaired['jobs'][1:], jobs[1:])
        self.assertEqual(repair_saved_urls(repaired), repaired)

    def test_sync_recovers_legacy_multi_job_inventory_without_refetch(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        from job_search_helper.engine import Engine, State, inventory_payload
        from job_search_helper.inbox import InventoryInbox
        from job_search_helper.repository import MemoryRepository
        from test_engine import company
        t = Transport(lambda _: {'count': 2, 'jobRequisitions': [{'reqId': '1'}, {'reqId': '2'}]})
        saved = fetch_adp_myjobs('ADP', URL, 'C-1', 'Acme', t)
        for job in saved.jobs:
            job['url'] = URL  # Reproduce the bad saved inventory.
        employer = dict(company(), **{'Official Careers URL': URL, 'ATS / Source': 'ADP'})
        repo = MemoryRepository({'Companies': [employer]})
        repo.spreadsheet_id = 'fixture'
        state = State()
        self.addCleanup(state.close)
        inbox = InventoryInbox(':memory:', repo.spreadsheet_id)
        self.addCleanup(inbox.close)
        engine = Engine(repo, state, inbox=inbox, error_log_path=None,
                        fetcher=lambda *args: self.fail('Saved inventory must not refetch'))
        with redirect_stdout(StringIO()), patch('job_search_helper.engine.classify_title', return_value='review'):
            cycle = engine.start_cycle(['C-1'])
            inbox.save(cycle, 'C-1', inventory_payload(saved, employer))
            inbox.block(cycle, 'C-1')
            engine.resume_local(cycle, sync_only=True, retry_blocked=True)
        self.assertEqual(state.cycle(cycle)['status'], 'Complete')
        history = repo.read('Job History')
        self.assertEqual(len(history), 2)
        self.assertEqual(len({r['Official Job URL'] for r in history}), 2)
        self.assertIsNone(inbox.get(cycle, 'C-1'))

    def test_retained_title_audit_hydrates_distinct_links_without_changing_database(self):
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from job_search_helper.inbox import InventoryInbox
        from job_search_helper.title_audit import load_title_audits
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'inbox.db'
            inbox = InventoryInbox(path, 'fixture')
            payload = {'source_url': URL, 'inventory_status': 'complete', 'jobs': [
                {'ats': 'ADP MyJobs', 'posting_id': str(n), 'url': URL, 'title': 'Engineer'} for n in (1, 2)]}
            try:
                with patch('job_search_helper.title_audit.classify_title', return_value='reject'):
                    inbox.save('cycle', 'C-1', payload)
                    inbox.acknowledge('cycle', 'C-1')
                    original = inbox.connection.execute('SELECT payload FROM title_filter_audits').fetchone()[0]
                    audits, _ = load_title_audits(path, 'fixture')
                    self.assertEqual(len({row['posting']['url'] for row in audits}), 2)
                    self.assertEqual(inbox.connection.execute('SELECT payload FROM title_filter_audits').fetchone()[0], original)
            finally:
                inbox.close()

    def test_dispatches_from_public_site(self):
        t = Transport(lambda _: {"count": 0, "jobRequisitions": []})
        result = fetch_inventory("ADP", URL, "C-1", "Kearfott", t)
        self.assertEqual(result.status, "complete", result.reason)
