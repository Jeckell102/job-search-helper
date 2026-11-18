"""Independent inspection-only observation acceptance boundaries."""
import copy
import hashlib
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import coordinator_evidence as evidence
import coordinator_workflow as workflow
import public_web

class DiagnosticBoundaries(unittest.TestCase):
    def setUp(self):
        self.now = time.time()
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'src').mkdir(); (self.root/'src/a.py').write_text('value = 1\n')
        self.manifest = {'src/a.py': hashlib.sha256(b'value = 1\n').hexdigest()}
        self.primary = {'url':'https://employer.example/careers','allowed_urls':['https://employer.example/careers'],'identity_terms':['Exact Employer']}
        self.mapped = {'url':'https://ats.example/employer','allowed_urls':['https://ats.example/employer'],'identity_terms':['Exact Employer'],'purpose':'configured_listing'}
        self.state = {'phase':'inspect','workflow_version':2,'mode':'develop','evidence_requirements':{'version':1,'required_files':['src/a.py'],'source_targets':[self.primary],'investigation_targets':[self.mapped]}}
        self.read = {'id':1,'phase':'inspect','created':self.now,'name':'code_read','arguments':{'path':'src/a.py','start_line':1},'result':{'ok':True,'result':{'path':'src/a.py','sha256':self.manifest['src/a.py'],'text':'1: value = 1'}}}
        self.identity = self.page(2,'web_read',self.primary['url'],self.primary['url'],'Exact Employer careers and employment opportunities are available here.')
        self.raw = self.page(3,'web_read',self.mapped['url'],'https://parent.example/search','Enable JavaScript to run this app.')
        self.rendered = self.page(4,'rendered_web_read','https://parent.example/search','https://parent.example/search','Generic parent company careers. 0 results.')

    def page(self, ident, tool, requested, final, text):
        return {'id':ident,'phase':'inspect','created':self.now,'name':tool,'arguments':{'url':requested},'result':{'ok':True,'result':{'url':final,'status':200,'text':text}}}

    def gate(self, receipts, state=None):
        with patch.object(evidence.time,'time',return_value=self.now):
            return evidence.phase_evidence(state or self.state,receipts,self.manifest)

    def test_generic_diagnostic_allows_inspection_but_never_becomes_inventory_evidence(self):
        receipts=[self.read,self.identity,self.raw,self.rendered]
        self.assertTrue(self.gate(receipts)[0])
        self.assertEqual(evidence.source_receipts(self.mapped,receipts,self.now),[])
        plan=workflow.plan(self.state,receipts,self.manifest,self.root,self.now)
        self.assertIsNone(plan['next'])
        self.assertEqual(self.state['phase'],'inspect')

    def test_primary_identity_still_required_even_when_both_diagnostics_exist(self):
        for identity in (None,self.page(2,'web_read',self.primary['url'],self.primary['url'],'Unrelated parent company careers and opportunities.')):
            receipts=[self.read,self.raw,self.rendered]+([identity] if identity else [])
            self.assertFalse(self.gate(receipts)[0])

    def test_unfinished_stale_wrong_phase_or_unrelated_render_cannot_finish_diagnostics(self):
        for key,value in [('result',None),('created',self.now-1801),('phase','implement')]:
            rendered=copy.deepcopy(self.rendered); rendered[key]=value
            self.assertFalse(self.gate([self.read,self.identity,self.raw,rendered])[0],(key,value))
        rendered=copy.deepcopy(self.rendered);rendered['arguments']['url']='https://unobserved.example/search'
        self.assertFalse(self.gate([self.read,self.identity,self.raw,rendered])[0])

    def test_raw_only_or_unlinked_render_does_not_complete_diagnostic(self):
        self.assertFalse(self.gate([self.read,self.identity,self.raw])[0])
        self.assertFalse(self.gate([self.read,self.identity,self.rendered])[0])
        raw=copy.deepcopy(self.raw);raw['result']['result']['url']=self.mapped['url']
        raw['result']['result']['text']='Go to https://parent.example/search then enable JavaScript.'
        self.assertFalse(self.gate([self.read,self.identity,raw,self.rendered])[0])

    def test_no_mapped_target_retains_existing_inspection_behavior(self):
        state=copy.deepcopy(self.state);state['evidence_requirements']['investigation_targets']=[]
        self.assertTrue(self.gate([self.read,self.identity],state)[0])

    def test_diagnostic_cannot_satisfy_development_implementation_gate(self):
        state=copy.deepcopy(self.state);state['phase']='implement'
        receipts=copy.deepcopy([self.read,self.identity,self.raw,self.rendered])
        for receipt in receipts:receipt['phase']='implement'
        self.assertFalse(self.gate(receipts,state)[0])

    def test_finalized_transport_failures_are_explicit_unverified_diagnostics(self):
        raw=copy.deepcopy(self.raw);raw['result']={'ok':False,'error':'HTTP transport unavailable'}
        rendered=copy.deepcopy(self.rendered);rendered['arguments']['url']=self.mapped['url']
        rendered['result']={'ok':False,'error':'Rendering unavailable'}
        observed=evidence.investigation_observation(self.mapped,[raw,rendered],self.now)
        self.assertTrue(observed['complete'])
        self.assertFalse(observed['verified_inventory'])
        self.assertEqual([o['outcome'] for o in observed['observations']],['failed','failed'])
        self.assertTrue(all(o['verified_inventory'] is False for o in observed['observations']))

    def test_render_before_latest_raw_is_not_linked(self):
        rendered=copy.deepcopy(self.rendered);rendered['created']=self.now-1
        self.assertFalse(evidence.investigation_observation(self.mapped,[self.raw,rendered],self.now)['complete'])

    def test_links_bounded_resolved_and_no_additional_requests(self):
        unsafe=['http://127.0.0.1/jobs','https://localhost/jobs','https://x.internal/jobs',
                'https://user:pass@example.com/jobs','https://example.com:444/jobs',
                'javascript:alert(1)','http://169.254.169.254/jobs','http://[::1]/jobs']
        html=''.join('<a href="'+url+'">Jobs</a>' for url in unsafe)
        html+=''.join('<a href="/jobs/'+str(i)+'">Jobs</a>' for i in range(150))
        result={'url':'https://public.example/careers/','status':200,'content_type':'text/html',
                'body':html,'truncated':False}
        with patch.object(public_web,'fetch',return_value=result) as fetch:
            page=public_web.read_page('https://public.example/careers/')
        fetch.assert_called_once_with('https://public.example/careers/')
        self.assertLessEqual(len(page['links']),100)
        self.assertTrue(page['links'])
        self.assertTrue(all(link['url'].startswith('https://public.example/jobs/') for link in page['links']))

if __name__=='__main__': unittest.main()
