"""Regression checks for missing mapped inventory and crowded fresh contexts."""
import copy
import time
import unittest
from pathlib import Path
import tempfile

import coordinator_workflow as w
from coordinator_evidence import build_requirements, phase_evidence


class PilotEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, text in {
            'src/job_search_helper/widget.py': 'COMPANY = "Widget"\nCOMPANY_ID = "COMP-1234"\n',
            'src/job_search_helper/company_sources.py': 'REPAIRS={"COMP-1234": {"company":"Widget", "expected_url":"https://widget.example/careers", "url":"https://jobs.example/widget"}}',
            'tests/test_widget.py': 'assert True',
        }.items():
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        self.req = build_requirements('COMP-1234 https://widget.example/careers tests/test_widget.py', ['tests/test_widget.py'], self.root)
        self.now = time.time()

    def receipt(self, ident, name, url, final, text):
        return {'id': ident, 'phase': 'inspect', 'created': self.now, 'name': name,
                'arguments': {'url': url}, 'result': {'ok': True, 'result': {'url': final, 'status': 200, 'text': text}}}

    def test_landing_evidence_does_not_replace_mapped_inventory(self):
        self.assertEqual(self.req['investigation_targets'][0]['url'], 'https://jobs.example/widget')
        req = dict(self.req, required_files=[])
        state = {'phase': 'inspect', 'evidence_requirements': req}
        landing = self.receipt(1, 'web_read', 'https://widget.example/careers', 'https://widget.example/careers', 'Widget careers: our company is a great place to work.')
        plan = w.plan(state, [landing], {}, self.root, self.now)
        self.assertEqual(plan['next']['arguments']['url'], 'https://jobs.example/widget')
        self.assertEqual(plan['next']['name'], 'web_read')

    def test_observed_redirect_is_rendered_once_then_blocks(self):
        state = {'phase': 'inspect', 'evidence_requirements': {'required_files': [], 'source_targets': self.req['investigation_targets']}}
        raw = self.receipt(1, 'web_read', 'https://jobs.example/widget', 'https://new.example/widget', 'Enable JavaScript to run this app.')
        plan = w.plan(state, [raw], {}, self.root, self.now)
        self.assertEqual(plan['next']['arguments']['url'], 'https://new.example/widget')
        rendered = self.receipt(2, 'rendered_web_read', 'https://new.example/widget', 'https://new.example/widget', 'Enable JavaScript to run this app.')
        self.assertIsNone(w.plan(state, [raw, rendered], {}, self.root, self.now)['next']['name'])
        rendered['result']['result']['text'] = 'Widget careers no positions available at this time.'
        self.assertIsNone(w.plan(state, [raw, rendered], {}, self.root, self.now)['next'])

    def test_unobserved_prose_url_never_becomes_render_destination(self):
        state = {'phase': 'inspect', 'evidence_requirements': {'required_files': [], 'source_targets': self.req['investigation_targets']}}
        raw = self.receipt(1, 'web_read', 'https://jobs.example/widget', 'https://jobs.example/widget', 'Enable JavaScript. See https://unrelated.example/')
        self.assertEqual(w.plan(state, [raw], {}, self.root, self.now)['next']['arguments']['url'], 'https://jobs.example/widget')

    def test_packet_retains_wrapper_tests_and_retrieval_metadata(self):
        required = ['tests/test_widget.py', 'src/job_search_helper/widget.py', 'src/job_search_helper/company_sources.py']
        manifest = {p: str(i) for i, p in enumerate(required)}
        receipts = []
        for i, p in enumerate(required):
            receipts.append({'id': i + 1, 'name': 'code_read', 'arguments': {'path': p, 'start_line': 1}, 'result': {'ok': True, 'result': {'sha256': manifest[p], 'text': '1: ' + 'data ' * 2000}}})
        for i in range(8):
            r = copy.deepcopy(receipts[-1]); r['id'] = i + 10; r['arguments']['start_line'] = 100 + i; receipts.append(r)
        receipts.append(self.receipt(30, 'web_read', 'https://jobs.example/widget', 'https://new.example/widget', 'Widget careers content ' * 200))
        state = {'evidence_requirements': {'required_files': required}, 'workflow': {'focus_receipt_id': 1}}
        packet = w.packet(state, receipts, manifest)
        self.assertIn('src/job_search_helper/widget.py', [p['arguments'].get('path') for p in packet])
        self.assertIn('tests/test_widget.py', [p['arguments'].get('path') for p in packet])
        self.assertEqual(packet[1]['retrieval']['url'], 'https://new.example/widget')
        self.assertLessEqual(sum(len(p['excerpt']) for p in packet), 12000)

    def test_focused_tail_and_stale_read_do_not_hide_current_wrapper_head(self):
        path = 'src/job_search_helper/widget.py'
        def read(ident, start, sha, text):
            return {'id': ident, 'name': 'code_read', 'arguments': {'path': path, 'start_line': start},
                    'result': {'ok': True, 'result': {'sha256': sha, 'text': text}}}
        receipts = [read(1, 1, 'old', '1: stale'),
                    read(2, 1, 'new', '1: SOURCE = "https://jobs.example/widget"\n2: def safe_public_path(): pass'),
                    read(3, 241, 'new', '241: tail')]
        state = {'evidence_requirements': {'required_files': [path]}, 'workflow': {'focus_receipt_id': 3}}
        packet = w.packet(state, receipts, {path: 'new'})
        self.assertEqual(packet[0]['receipt_id'], 3)
        self.assertTrue(any('safe_public_path' in r['excerpt'] and 'SOURCE' in r['excerpt'] for r in packet))
        self.assertNotIn(1, [r['receipt_id'] for r in packet])

if __name__ == '__main__': unittest.main()
