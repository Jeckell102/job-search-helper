import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from wrapper_task import parse_request

class ScopeCliTests(unittest.TestCase):
    def test_reviewed_approval_and_status(self):
        approval = dict(paths=['src/helper.py'], reason='Required shared helper', expected_state_digest='a'*64, expected_scope_digest='b'*64)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'approval.json';path.write_text(json.dumps(approval))
            self.assertEqual(parse_request(['scope-expand','WRAP-123','--approval-file',str(path)]),dict(action='scope-expand',id='WRAP-123',**approval))
        self.assertEqual(parse_request(['status','WRAP-123','--json']),dict(action='status',id='WRAP-123',_output_json=True))
        for action in ('retry','exclude','include'):
            self.assertEqual(parse_request([action,'WRAP-123']),dict(action=action,id='WRAP-123'))
    def test_incomplete_approval_or_unrelated_flags_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'approval.json';path.write_text('{"paths":["src/helper.py"]}')
            for argv in (['scope-expand','WRAP-123'],['scope-expand','WRAP-123','--approval-file',str(path)],['start','objective','--approval-file',str(path)],['health','--json']):
                with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):parse_request(argv)
if __name__=='__main__':unittest.main()
