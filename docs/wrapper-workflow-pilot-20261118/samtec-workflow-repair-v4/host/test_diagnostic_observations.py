import copy
import time
import unittest
from unittest.mock import patch
import coordinator_evidence as e
import public_web

class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.now=time.time()
        self.target={'url':'https://old.example/jobs', 'allowed_urls':['https://old.example/jobs'], 'identity_terms':['Widget Company']}
    def receipt(self, ident, name='web_read', url=None, ok=True, text='Generic parent company careers', final=None):
        return {'id':ident, 'created':self.now, 'phase':'inspect', 'name':name,
                'arguments':{'url':url or self.target['url']},
                'result':{'ok':ok, 'error':'bounded transport failed' if not ok else '',
                          'result':{'url':final or url or self.target['url'], 'status':200 if ok else 403, 'text':text}}}
    def test_generic_and_failed_observations_complete_diagnostic_not_source(self):
        for ok in (True,False):
            raw=self.receipt(1,ok=ok)
            rendered=self.receipt(2,'rendered_web_read',ok=ok)
            observation=e.investigation_observation(self.target,[raw,rendered],self.now)
            self.assertTrue(observation['complete'])
            self.assertEqual(observation['receipt_ids'],[1,2])
            self.assertFalse(observation['verified_inventory'])
            self.assertEqual(e.source_receipts(self.target,[raw,rendered],self.now),[])
    def test_failed_raw_requires_render_and_pending_stale_other_phase_do_not_count(self):
        raw=self.receipt(1,ok=False)
        self.assertEqual(e.investigation_observation(self.target,[raw],self.now)['next']['name'],'rendered_web_read')
        for change in ({'result':None},{'created':self.now-1801},{'phase':'implement'},{'arguments':{'url':'https://other.example/jobs'}}):
            bad=copy.deepcopy(raw);bad.update(change)
            result=e.investigation_observation(self.target,[bad],self.now)
            self.assertFalse(result['complete']);self.assertEqual(result['receipt_ids'],[])
    def test_only_observed_redirect_destination_can_complete(self):
        raw=self.receipt(1,final='https://new.example/jobs')
        wrong=self.receipt(2,'rendered_web_read','https://unrelated.example/jobs')
        result=e.investigation_observation(self.target,[raw,wrong],self.now)
        self.assertFalse(result['complete']);self.assertEqual(result['next']['arguments']['url'],'https://new.example/jobs')
        right=self.receipt(3,'rendered_web_read','https://new.example/jobs',ok=False)
        self.assertTrue(e.investigation_observation(self.target,[raw,right],self.now)['complete'])
    def test_meaningful_raw_is_observation_without_inventory_certification(self):
        raw=self.receipt(1,text='Widget Company Careers with currently listed positions.')
        result=e.investigation_observation(self.target,[raw],self.now)
        self.assertTrue(result['complete']);self.assertFalse(result['verified_inventory'])
    def test_public_links_bounded_resolved_and_unsafe_schemes_dropped(self):
        body='<a href="/search/jobs"><span>Search Available Careers</span></a><a href="javascript:evil()">bad</a><a href="http://127.0.0.1/jobs">private</a><a href="https://u:p@example.org">credentials</a>'
        body += ''.join(f'<a href="/jobs/{i}">Job {i}</a>' for i in range(150))
        with patch.object(public_web,'fetch',return_value={'url':'https://company.example/careers','status':200,'content_type':'text/html','body':body,'truncated':False}):
            result=public_web.read_page('https://company.example/careers')
        self.assertEqual(result['links'][0],{'url':'https://company.example/search/jobs','text':'Search Available Careers'})
        self.assertLessEqual(len(result['links']),100)
        self.assertFalse(any('127.0.0.1' in x['url'] or 'javascript:' in x['url'] or 'u:p@' in x['url'] for x in result['links']))

if __name__ == '__main__':unittest.main()
