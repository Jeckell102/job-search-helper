"""Provisional per-profile inference deadline contract; synthetic only."""
import io
import json
import threading
import unittest
from unittest.mock import patch
import engine
from profile_policy import PROFILES

class TimeoutTests(unittest.TestCase):
    def test_three_profiles_have_separate_bounded_timeouts(self):
        expected={'qwen-instant:4b':120,'qwen-advanced:4b':240,'qwen-pro:4b':420,'qwen-wrapper:4b':240}
        self.assertEqual({k:p.generation_timeout_seconds for k,p in PROFILES.items()},expected)
        self.assertTrue(all(0<p.generation_timeout_seconds<=420 for p in PROFILES.values()))

    def test_urllib_uses_profile_deadline_not_legacy_global(self):
        m=engine.Engine(threading.Event())
        timeouts=[]
        def fake_urlopen(req,timeout):
            payload=json.loads(req.data)
            timeouts.append((payload['model'],timeout))
            return io.BytesIO(b'{"message":{"content":"ok"},"done":true,"done_reason":"stop"}\n')
        with patch.object(engine.urllib.request,'urlopen',side_effect=fake_urlopen):
            for name in PROFILES:
                list(m.stream([{'role':'user','content':'synthetic'}],max_tokens=20,profile_id=name))
        self.assertEqual(timeouts,[('qwen-instant:4b',120),('qwen-advanced:4b',240),('qwen-pro:4b',420),('qwen-wrapper:4b',240)])

    def test_queue_admission_retains_existing_timeout(self):
        gate=engine.Gate(threading.Event())
        # The stage change touches only active generation time; Gate.hold stays independent.
        self.assertFalse(gate.busy)
        with gate.hold(foreground=True):
            self.assertTrue(gate.busy)
        self.assertFalse(gate.busy)
