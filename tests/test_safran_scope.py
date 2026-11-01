from __future__ import annotations
import copy, json
from pathlib import Path
import unittest
from job_search_helper.ats import HTTPResponse, fetch_inventory

ROOT = Path(__file__).parent / 'fixtures' / 'bamboohr' / 'safran-federal'
SOURCE = 'https://www.safranfederalsystems.com/open-roles'
ALT_SOURCE = 'https://www.safranfederalsystems.com/careers'
APIROOT = 'https://safransed.bamboohr.com'
IDS = ('1101','1102','1138','1144','1145','1148','1150','1151','1157')

def data(name): return json.loads((ROOT / name).read_text())

class Replay:
    def __init__(self, stale=False, drift=False, duplicate=False, wrong_body=False):
        self.calls=[]; self.page = '<html>' + ''.join(f'<a href="{APIROOT}/careers/{i}">role</a>' for i in IDS)
        if stale: self.page += f'<a href="{APIROOT}/careers/999">stale</a>'
        self.drift = drift; self.duplicate = duplicate
        self.listing = data('listing38.json')
        if duplicate: self.listing['result'].append(copy.deepcopy(self.listing['result'][0])); self.listing['meta']['totalCount']=39
        self.wrong_body = wrong_body
    def get(self, url):
        self.calls.append(url)
        if url in (SOURCE, ALT_SOURCE): return HTTPResponse(200, self.page.encode(), {'content-type':'text/html'})
        if url == APIROOT + '/careers/list':
            payload = self.listing
            if self.drift and self.calls.count(url) > 1: payload = copy.deepcopy(self.listing); payload['result'][-1]['jobOpeningName'] += ' changed'
            return HTTPResponse(200, json.dumps(payload).encode(), {'content-type':'application/json'})
        for i in IDS:
            if url == f'{APIROOT}/careers/{i}/detail':
                payload = data(i+'.json')
                if self.wrong_body and i == IDS[0]: payload['result']['jobOpening']['description'] = '<p>Unrelated Safran entity</p>'
                return HTTPResponse(200, json.dumps(payload).encode(), {'content-type':'application/json'})
        raise AssertionError(f'unexpected URL {url}')

class SafranScopeTests(unittest.TestCase):
    def fetch(self, replay, **kw):
        return fetch_inventory('Browser', SOURCE, 'COMP-0263', 'Safran Federal Systems', replay, discovery_transport=replay, **kw)

    def test_corporate_nine_is_complete_and_not_whole_tenant(self):
        t=Replay(); result=self.fetch(t)
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual({j['posting_id'] for j in result.jobs}, set(IDS))
        self.assertEqual(len(result.jobs), 9)
        self.assertTrue(all(j['description'].strip() for j in result.jobs))
        self.assertEqual(t.calls.count(APIROOT + '/careers/list'), 2)

    def test_stale_linked_id_keeps_useful_jobs_partial(self):
        result=self.fetch(Replay(stale=True))
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(result.jobs), 9)

    def test_scope_drift_and_duplicate_listing_fail_closed(self):
        self.assertEqual(self.fetch(Replay(drift=True)).status, 'partial')
        self.assertEqual(self.fetch(Replay(duplicate=True)).status, 'partial')

    def test_wrong_detail_employer_identity_is_partial_with_jobs_retained(self):
        result = self.fetch(Replay(wrong_body=True))
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(result.jobs), 9)

    def test_wrong_identity_or_source_does_not_gain_completion(self):
        t=Replay(); self.assertIn(fetch_inventory('Browser', SOURCE, 'OTHER', 'Safran Federal Systems', t, discovery_transport=t).status, {'partial', 'unsupported'})
        t=Replay(); self.assertIn(fetch_inventory('Browser', SOURCE, 'COMP-0263', 'Other Safran', t, discovery_transport=t).status, {'partial', 'unsupported'})
        t=Replay(); self.assertEqual(fetch_inventory('Browser', ALT_SOURCE, 'COMP-0263', 'Safran Federal Systems', t, discovery_transport=t).status, 'partial')

if __name__ == '__main__': unittest.main()
