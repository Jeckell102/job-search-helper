import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import coordinator_workflow as w
import public_web
import test_coordinator as fixture
import test_coordinator_workflow as workflow_fixture

class StructureTests(unittest.TestCase):
    def test_legacy_html_is_refreshed_once_without_changing_identity_gate(self):
        now=time.time();url='https://company.example/jobs'
        state={'phase':'inspect','evidence_requirements':{'required_files':[], 'source_targets':[{'url':url,'allowed_urls':[url],'identity_terms':['Widget']}]}}
        old={'id':1,'phase':'inspect','created':now,'name':'web_read','arguments':{'url':url},'result':{'ok':True,'result':{'url':url,'status':200,'content_type':'text/html','text':'Widget Careers lists currently available open positions.'}}}
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(w.plan(state,[old],{},Path(root),now)['next']['name'],'web_read')
            failed=copy.deepcopy(old);failed.update(id=2);failed['result']={'ok':False,'error':'timeout'}
            self.assertIsNone(w.plan(state,[old,failed],{},Path(root),now)['next'])
            new=copy.deepcopy(old);new.update(id=3);new['result']['result']['html_structure']={'kind':'source_html_attributes'}
            self.assertIsNone(w.plan(state,[old,new],{},Path(root),now)['next'])
    def test_structure_pagination_survives_plain_text_and_packet(self):
        html='<div class="jv-job-list">Real jobs</div>'+''.join('<a href="/job/%s">Role</a>'%i for i in range(120))+'<a class="jv-pagination-next" href="/search/?p=1">Next</a>'
        with patch.object(public_web,'fetch',return_value={'url':'https://company.example/search','status':200,'content_type':'text/html','body':html,'truncated':False}):
            value=public_web.read_page('https://company.example/search')
        self.assertNotIn('jv-job-list',value['text'])
        self.assertIn('jv-job-list',value['html_structure']['classes'])
        self.assertEqual(value['html_structure']['pagination'][0]['url'],'https://company.example/search/?p=1')
        receipt={'id':1,'created':time.time(),'name':'web_read','arguments':{'url':value['url']},'result':{'ok':True,'result':value}}
        packet=w.packet({},[receipt],{})
        self.assertEqual(packet[0]['html_structure']['pagination'][0]['text'],'Next')
        self.assertFalse(packet[0]['html_structure']['verified_inventory'])
        self.assertLessEqual(len(json.dumps(packet)),12000)

class ClosingTests(unittest.TestCase):
    setUp=workflow_fixture.WorkflowTests.setUp
    task=workflow_fixture.WorkflowTests.task
    collect=workflow_fixture.WorkflowTests.collect
    checkpoint=fixture.CoordinatorTests.checkpoint
    def test_closing_turn_guides_continue_for_next_available_tool(self):
        task=self.task();self.collect(task)
        read=fixture.response('code_read',{'path':'src/a.py','start_line':1})
        self.answers=[read,read,self.checkpoint()]
        self.co.step(task)
        closing=' '.join(x.get('content','') for x in self.history[-1])
        self.assertIn('use outcome continue',closing)
        self.assertIn('session closing is not a blocker',closing)

if __name__=='__main__':unittest.main()
