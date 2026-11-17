"""Staged HTTP contract tests; no real Ollama or production service."""
import http.client
import json
import threading
import unittest
from unittest.mock import patch
import engine, server
from profile_policy import PROFILES
from test_orchestrator import CoreTests

class HTTPProfileTests(unittest.TestCase):
    def setUp(self):
        CoreTests.setUp(self)
        self.model=engine.Engine(threading.Event())
        self.app=server.Server(('127.0.0.1',0),server.Handler,self.model)
        self.thread=threading.Thread(target=self.app.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.app.shutdown(); self.app.server_close(); self.thread.join(2)
        CoreTests.tearDown(self)

    def call(self,method,path,data=None):
        c=http.client.HTTPConnection('127.0.0.1',self.app.server_port,timeout=4)
        try:
            c.request(method,path,body=None if data is None else json.dumps(data),
                headers={'Content-Type':'application/json'})
            r=c.getresponse()
            return r.status,r.read().decode()
        finally: c.close()

    def test_catalog_exposes_only_user_profile_names(self):
        code,body=self.call('GET','/v1/models')
        self.assertEqual(code,200)
        ids={x['id'] for x in json.loads(body)['data']}
        self.assertEqual(ids, {'Instant','Advanced','Pro','Wrapper Coder'})

    def test_all_profiles_reach_http_inference_route(self):
        captured=[]
        def fake_stream(*a,**kw):
            captured.append(kw)
            return iter([{'text':'ok'},{'done':True,'finish_reason':'stop','input_tokens':21,'output_tokens':2}])
        with patch.object(self.model,'stream',side_effect=fake_stream):
            for name in PROFILES:
                code,body=self.call('POST','/v1/chat/completions',
                    {'model':name,'messages':[{'role':'user','content':'Test'}]})
                self.assertEqual(code,200)
                r=json.loads(body)
                self.assertEqual(r['model'],name)
                self.assertEqual(r['choices'][0]['finish_reason'],'stop')
                self.assertEqual(r['usage']['prompt_tokens'],21)
        self.assertEqual([r['profile_id'] for r in captured],list(PROFILES))
        self.assertEqual(captured[0]['max_tokens'],512)
        self.assertEqual(captured[1]['max_tokens'],1536)
        self.assertTrue(1536<captured[2]['max_tokens']<4096)

    def test_legacy_alias_selects_instant(self):
        captured=[]
        with patch.object(self.model,'stream',
             side_effect=lambda *a,**kw: captured.append(kw) or iter([{'text':'ok'},{'done':True,'finish_reason':'stop'}])):
            code,body=self.call('POST','/v1/chat/completions',
                 {'model':'jetson-assistant','messages':[{'role':'user','content':'Test'}]})
        self.assertEqual(code,200)
        self.assertEqual(captured[0]['profile_id'],'qwen-instant:4b')

    def test_visible_profile_names_route_to_internal_profiles(self):
        captured=[]
        def fake_stream(*a,**kw):
            captured.append(kw)
            return iter([{'text':'ok'},{'done':True,'finish_reason':'stop','input_tokens':21,'output_tokens':2}])
        with patch.object(self.model,'stream',side_effect=fake_stream):
            for visible,internal in (('Instant','qwen-instant:4b'),('Advanced','qwen-advanced:4b'),('Pro','qwen-pro:4b')):
                code,body=self.call('POST','/v1/chat/completions',
                    {'model':visible,'messages':[{'role':'user','content':'Test'}]})
                self.assertEqual(code,200)
                self.assertEqual(json.loads(body)['model'],visible)
                self.assertEqual(captured[-1]['profile_id'],internal)

    def test_frontend_tool_metadata_is_ignored_for_ordinary_chat(self):
        def fake_stream(*a,**kw):
            return iter([{'text':'normal chat works'},{'done':True,'finish_reason':'stop','input_tokens':10,'output_tokens':3}])
        payload={'model':'Instant',
                 'messages':[{'role':'user','content':'Hello'}],
                 'tools':[{'type':'function','function':{'name':'web_search','parameters':{'type':'object'}}}],
                 'tool_choice':'auto'}
        with patch.object(self.model,'stream',side_effect=fake_stream):
            code,body=self.call('POST','/v1/chat/completions',payload)
        self.assertEqual(code,200)
        self.assertEqual(json.loads(body)['choices'][0]['message']['content'],'normal chat works')

    def test_tool_role_messages_are_still_rejected(self):
        payload={'model':'Instant','messages':[
            {'role':'tool','content':'untrusted external result'},
            {'role':'user','content':'Use that'}
        ]}
        code,body=self.call('POST','/v1/chat/completions',payload)
        self.assertEqual(code,400)
        self.assertEqual(json.loads(body)['error']['type'],'invalid_request_error')

    def test_http_stream_reports_length_not_stop(self):
        def incomplete(*a,**kw):
            yield {'text':'partial'}
            yield {'done':True,'finish_reason':'length','input_tokens':12,'output_tokens':512}
        with patch.object(self.model,'stream',side_effect=incomplete):
            code,body=self.call('POST','/v1/chat/completions',
                {'model':'qwen-instant:4b','stream':True,'messages':[{'role':'user','content':'Test'}]})
        self.assertEqual(code,200)
        self.assertIn('"finish_reason": "length"',body)
        self.assertNotIn('"finish_reason": "stop"',body)

    def test_unknown_profile_and_impossible_max_tokens_fail(self):
        for body in ({'model':'unknown','messages':[{'role':'user','content':'Test'}]},
                     {'model':'qwen-pro:4b','max_tokens':4096,'messages':[{'role':'user','content':'Test'}]}):
            code,resp=self.call('POST','/v1/chat/completions',body)
            self.assertEqual(code,400)
            self.assertEqual(json.loads(resp)['error']['type'],'invalid_request_error')
if __name__=='__main__':unittest.main()
