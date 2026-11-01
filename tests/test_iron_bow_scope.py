from __future__ import annotations
import json
from pathlib import Path
import unittest
from job_search_helper.ats import HTTPResponse, fetch_inventory

FIXTURE = Path(__file__).parent / 'fixtures' / 'ironbow' / 'greenhouse-jobs17.json'
CORPORATE = 'https://ironbow.com/careers'
BOARD = 'https://boards-api.greenhouse.io/v1/boards/ironbowtechnologies/jobs?content=true'

class Replay:
    def __init__(self, payload): self.payload = payload; self.urls=[]
    def get(self, url):
        self.urls.append(url)
        if url.startswith('https://boards-api.greenhouse.io/v1/boards/') and url.endswith('?content=true'):
            return HTTPResponse(200, json.dumps(self.payload).encode(), {'content-type':'application/json'})
        raise AssertionError(f'unexpected API URL: {url}')

class IronBowScopeTests(unittest.TestCase):
    def payload(self): return json.loads(FIXTURE.read_text())

    def test_configured_corporate_route_fetches_actual_17_job_feed(self):
        t=Replay(self.payload())
        result=fetch_inventory('Browser', CORPORATE, 'COMP-0315', 'Iron Bow Technologies', t)
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(len(result.jobs), 17)
        self.assertEqual(len({j['posting_id'] for j in result.jobs}), 17)
        self.assertTrue(all(j['description'].strip() for j in result.jobs))
        self.assertTrue(all(j['url'].startswith('https://ironbow.com/job-details?gh_jid=') for j in result.jobs))
        self.assertEqual(t.urls, [BOARD])

    def test_exact_api_allowlist_and_source_aliases(self):
        t=Replay(self.payload())
        result=fetch_inventory('Greenhouse', BOARD, 'COMP-0315', 'Iron Bow Technologies', t)
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(t.urls, [BOARD])
        self.assertIn(fetch_inventory('Greenhouse', CORPORATE + '?x=1', 'COMP-0315', 'Iron Bow Technologies', Replay(self.payload())).status, {'unsupported', 'failed'})

    def test_sandbox_canonicalization_requires_exact_matching_gh_jid(self):
        payload=self.payload(); payload['jobs'][0]['absolute_url']='https://ironbow-com.sandbox.hs-sites.com/job-details?gh_jid=9999999999#x'
        result=fetch_inventory('Greenhouse', BOARD, 'COMP-0315', 'Iron Bow Technologies', Replay(payload))
        self.assertEqual(result.status, 'partial')

    def test_other_greenhouse_company_keeps_original_public_urls(self):
        t=Replay(self.payload())
        result=fetch_inventory('Greenhouse', 'https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true', 'C-1', 'Acme', t)
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertTrue(all('sandbox.hs-sites.com' in j['url'] for j in result.jobs))

if __name__ == '__main__': unittest.main()
