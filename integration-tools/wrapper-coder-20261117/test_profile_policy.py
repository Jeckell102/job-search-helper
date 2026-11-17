import io
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import engine
import server
from profile_policy import PROFILES,resolve_profile,resolve_output_limit
from test_orchestrator import CoreTests

class PolicyUnitTests(unittest.TestCase):
    def test_named_and_legacy_profiles(self):
        self.assertEqual(set(PROFILES), {"qwen-instant:4b","qwen-advanced:4b","qwen-pro:4b","qwen-wrapper:4b"})
        self.assertEqual(resolve_profile("mule-orchestrator").model_id,"qwen-instant:4b")
        self.assertEqual(resolve_profile("jetson-assistant").model_id,"qwen-instant:4b")
        with self.assertRaises(ValueError): resolve_profile("missing")

    def test_pro_has_context_aware_default_above_512(self):
        p=resolve_profile("qwen-pro:4b")
        budget=resolve_output_limit([{"role":"user","content":"hello"}],p)
        self.assertGreater(budget,512)
        self.assertLess(budget,4096)

    def test_explicit_override_and_rejections(self):
        p=resolve_profile("qwen-pro:4b")
        m=[{"role":"user","content":"hello"}]
        self.assertEqual(resolve_output_limit(m,p,800),800)
        for invalid in (True,1.5,4096):
            with self.assertRaises(ValueError): resolve_output_limit(m,p,invalid)
        long_prompt = " ".join(str(i*271828+314159) for i in range(2400))
        with self.assertRaises(ValueError):
            resolve_output_limit([{"role":"user","content":long_prompt}],p)

    def test_native_ollama_request_policy_for_all_profiles(self):
        model=engine.Engine(threading.Event())
        captured=[]
        def fake_urlopen(req,timeout):
            captured.append(json.loads(req.data))
            return io.BytesIO(b'{"message":{"content":"ok"},"done":true,"done_reason":"stop"}\n')
        with patch.object(engine.urllib.request,"urlopen",side_effect=fake_urlopen):
            for name,p in PROFILES.items():
                list(model.stream([{"role":"user","content":"Hi"}],profile_id=name,max_tokens=64))
        self.assertEqual(len(captured),len(PROFILES))
        for (name,p),request in zip(PROFILES.items(),captured):
            self.assertEqual(request["model"],name)
            self.assertIs(request["think"],p.think)
            self.assertEqual(request["options"]["num_predict"],64)
            self.assertEqual(request["options"]["num_ctx"],p.context_tokens)
            self.assertEqual(request["options"]["top_p"],p.top_p)

class StagedHandlerTests(unittest.TestCase):
    setUp=CoreTests.setUp
    tearDown=CoreTests.tearDown

    def test_all_profiles_route_to_correct_model_and_limits(self):
        model=engine.Engine(threading.Event())
        handler=object.__new__(server.Handler)
        handler.server=SimpleNamespace(engine=model)
        responses=[]
        handler.response=lambda status,body: responses.append((status,body))
        called=[]
        def fake_stream(*args,**kwargs):
            called.append(kwargs)
            return iter([{"text":"ok"},{"done":True,"finish_reason":"stop"}])
        with patch.object(model,"stream",side_effect=fake_stream):
            for name in PROFILES:
                handler.chat({"model":name,"messages":[{"role":"user","content":"say hi"}]})
        self.assertEqual([r[0] for r in responses],[200]*len(PROFILES))
        self.assertEqual([x["profile_id"] for x in called],list(PROFILES))
        self.assertEqual(called[0]["max_tokens"],512)
        self.assertEqual(called[1]["max_tokens"],1536)
        self.assertGreater(called[2]["max_tokens"],1536)
        self.assertEqual([r[1]["model"] for r in responses],list(PROFILES))

    def test_explicit_thinking_override_passed_and_invalid_rejected(self):
        model=engine.Engine(threading.Event())
        handler=object.__new__(server.Handler)
        handler.server=SimpleNamespace(engine=model)
        handler.response=lambda *_:None
        called=[]
        with patch.object(model,"stream",side_effect=lambda *a,**kw: called.append(kw) or iter([{"done":True}])):
            handler.chat({"model":"qwen-instant:4b","think":True,"messages":[{"role":"user","content":"hi"}]})
        self.assertIs(called[0]["think_override"],True)
        with self.assertRaises(ValueError):
            handler.chat({"model":"qwen-instant:4b","think":"true","messages":[{"role":"user","content":"hi"}]})

    def test_explicit_impossible_pro_budget_refused(self):
        handler=object.__new__(server.Handler)
        handler.server=SimpleNamespace(engine=engine.Engine(threading.Event()))
        with self.assertRaises(ValueError):
            handler.chat({"model":"qwen-pro:4b","max_tokens":4096,"messages":[{"role":"user","content":"Hi"}]})
