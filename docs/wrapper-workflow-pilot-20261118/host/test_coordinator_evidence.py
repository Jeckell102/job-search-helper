import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from coordinator_evidence import (build_requirements, evidence_fingerprint,
                                  manifest_digest, phase_evidence)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        files = {
            'src/job_search_helper/widget_robotics.py': 'COMPANY = "Widget Robotics"\nCOMPANY_ID = "COMP-1234"\n',
            'src/job_search_helper/ats.py': 'def fetch_inventory(): pass\n',
            'src/job_search_helper/company_sources.py': 'REPAIRS = {"COMP-1234": {"company": "Widget Robotics", "expected_url": "https://widget.example/careers", "url": "https://ats.example/widget"}}\n',
            'tests/test_widget_robotics.py': 'from job_search_helper.widget_robotics import COMPANY\ndef test_identity(): assert COMPANY == "Widget Robotics"\n',
            'docs/wrapper-development-test-protocol.md': '# Required protocol\n',
            'docs/unrelated.md': 'Unrelated instructions\n',
        }
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.manifest = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()}
        self.requirements = build_requirements('Review Widget Robotics at https://widget.example/careers. Run tests/test_widget_robotics.py.',
                                              ['tests/test_widget_robotics.py'], self.root)
        self.state = {'phase': 'inspect', 'evidence_requirements': self.requirements}

    def receipt(self, name, args, value, phase='inspect', **extra):
        return {'name': name, 'phase': phase, 'arguments': args,
                'result': {'ok': True, 'result': value, **extra}}

    def reads(self, phase='inspect'):
        return [self.receipt('code_read', {'path': path}, {'path': path, 'text': '1: Real source excerpt',
                                                        'sha256': self.manifest[path]}, phase)
                for path in self.requirements['required_files']]

    def page(self, **changes):
        value = {'url': 'https://widget.example/careers', 'status': 200,
                 'text': 'Widget Robotics Careers. No positions available at this time.',
                 'links': [], 'render_seconds': 1.0}
        value.update(changes)
        return self.receipt('rendered_web_read', {'url': 'https://widget.example/careers'}, value)

    def test_requirements_freeze_original_tests_wrapper_mapping_and_routing(self):
        self.assertEqual(set(self.requirements['required_files']), {
            'tests/test_widget_robotics.py', 'src/job_search_helper/widget_robotics.py',
            'src/job_search_helper/ats.py', 'src/job_search_helper/company_sources.py'})
        target = self.requirements['source_targets'][0]
        self.assertEqual(target['url'], 'https://widget.example/careers')
        self.assertEqual(target['identity_terms'], ['Widget Robotics'])
        self.assertIn('https://ats.example/widget', target['allowed_urls'])
        self.assertEqual(json.loads(json.dumps(self.requirements)), self.requirements)

    def test_direct_import_and_test_stem_both_find_wrapper(self):
        (self.root / 'tests/test_widget_robotics.py').write_text('def test_a(): assert True\n')
        derived = build_requirements('Review tests/test_widget_robotics.py', ['tests/test_widget_robotics.py'], self.root)
        self.assertIn('src/job_search_helper/widget_robotics.py', derived['required_files'])
        (self.root / 'tests/test_contract.py').write_text('import job_search_helper.widget_robotics as wrapper\n')
        derived = build_requirements('Review tests/test_contract.py', ['tests/test_contract.py'], self.root)
        self.assertIn('src/job_search_helper/widget_robotics.py', derived['required_files'])

    def test_requirement_discovery_rejects_hardlinks_and_symlinks(self):
        original = self.root / 'docs/unrelated.md'
        os.link(original, self.root / 'src/hardlinked.py')
        (self.root / 'src/symlink.py').symlink_to(original)
        requirements = build_requirements('Review src/hardlinked.py and src/symlink.py; run tests/test_widget_robotics.py',
                                          ['tests/test_widget_robotics.py'], self.root)
        self.assertNotIn('src/hardlinked.py', requirements['required_files'])
        self.assertNotIn('src/symlink.py', requirements['required_files'])

    def test_unrelated_and_protocol_reads_cannot_replace_required_reads(self):
        for missing in ('tests/test_widget_robotics.py', 'src/job_search_helper/widget_robotics.py'):
            with self.subTest(missing=missing):
                receipts = [r for r in self.reads() if r['arguments']['path'] != missing]
                for path in ('docs/unrelated.md', 'docs/wrapper-development-test-protocol.md'):
                    receipts.append(self.receipt('code_read', {'path': path}, {'path': path, 'text': 'Real text', 'sha256': self.manifest[path]}))
                ok, reason = phase_evidence(self.state, receipts + [self.page()], self.manifest)
                self.assertFalse(ok)
                self.assertIn(missing, reason)

    def test_stale_or_empty_assigned_read_is_not_inspection(self):
        for change in ({'sha256': 'stale'}, {'text': ''}):
            with self.subTest(change=change):
                receipts = self.reads()
                receipts[0]['result']['result'].update(change)
                self.assertFalse(phase_evidence(self.state, receipts + [self.page()], self.manifest)[0])

    def test_search_empty_or_populated_is_discovery_not_retrieved_source(self):
        for results in ([], [{'url': 'https://widget.example/careers', 'title': 'Widget Robotics'}]):
            search = self.receipt('web_search', {'query': 'unrelated internet query'}, {'results': results})
            ok, reason = phase_evidence(self.state, self.reads() + [search], self.manifest)
            self.assertFalse(ok)
            self.assertIn('https://widget.example/careers', reason)

    def test_source_rejects_http_failure_shell_missing_identity_or_content(self):
        variations = [{'status': 404}, {'status': 500}, {'status': None}, {'status': True},
                      {'text': ''}, {'text': 'Widget Robotics Careers. Dover You need to enable JavaScript to run this app.'},
                      {'text': 'Widget Robotics. Verify you are human before proceeding.'},
                      {'text': 'Different Robotics Careers. No positions available at this time.'}]
        for change in variations:
            with self.subTest(change=change):
                self.assertFalse(phase_evidence(self.state, self.reads() + [self.page(**change)], self.manifest)[0])

    def test_unrelated_retrieval_cannot_qualify_even_if_text_names_company(self):
        page = self.page(url='https://unrelated.example/')
        page['arguments']['url'] = 'https://unrelated.example/'
        self.assertFalse(phase_evidence(self.state, self.reads() + [page], self.manifest)[0])

    def test_meaningful_declared_or_mapped_source_can_qualify(self):
        for page in (self.page(), self.page(url='https://ats.example/widget')):
            if page['result']['result']['url'] == 'https://ats.example/widget':
                page['arguments']['url'] = 'https://ats.example/widget'
            with self.subTest(url=page['arguments']['url']):
                self.assertEqual(phase_evidence(self.state, self.reads() + [page], self.manifest), (True, ''))

    def test_redirect_needs_company_cue_or_known_final_target(self):
        redirected = self.page(url='https://new-ats.example/widget-jobs')
        self.assertTrue(phase_evidence(self.state, self.reads() + [redirected], self.manifest)[0])
        no_identity = copy.deepcopy(self.state)
        no_identity['evidence_requirements']['source_targets'][0]['identity_terms'] = []
        self.assertFalse(phase_evidence(no_identity, self.reads() + [redirected], self.manifest)[0])

    def test_diff_before_edit_cannot_satisfy_implementation(self):
        state = {**self.state, 'phase': 'implement'}
        before = self.manifest.copy()
        after = {**before, 'src/job_search_helper/widget_robotics.py': 'new-file-hash'}
        diff = self.receipt('code_diff', {}, {'diff': 'old diff'}, 'implement',
                            source_manifest_sha256=manifest_digest(before), source_unchanged_during_diff=True)
        ok, reason = phase_evidence(state, self.reads('implement') + [diff], after)
        self.assertFalse(ok)
        self.assertIn('after the last edit', reason)
        diff['result']['source_manifest_sha256'] = manifest_digest(after)
        self.assertTrue(phase_evidence(state, self.reads('implement') + [diff], after)[0])
        diff['result']['source_unchanged_during_diff'] = False
        self.assertFalse(phase_evidence(state, self.reads('implement') + [diff], after)[0])

    def test_old_task_without_requirements_fails_closed(self):
        self.assertFalse(phase_evidence({'phase': 'inspect'}, self.reads() + [self.page()], self.manifest)[0])

    def test_browser_timing_not_progress_but_content_status_and_links_are(self):
        first = self.page()
        timed = self.page(render_seconds=9.85, elapsed_seconds=50, retrieved_at='later')
        self.assertEqual(evidence_fingerprint(first), evidence_fingerprint(timed))
        for change in ({'text': 'Widget Robotics Careers. A new Engineer position is open.'},
                       {'status': 404}, {'links': [{'text': 'Engineer', 'url': '/jobs/engineer'}]}):
            with self.subTest(change=change):
                self.assertNotEqual(evidence_fingerprint(first), evidence_fingerprint(self.page(**change)))

    def test_test_durations_not_progress_but_status_output_and_source_changes_are(self):
        first = self.receipt('code_test', {'paths': 'tests/test_widget_robotics.py'},
                             {'exit_code': 0, 'output': '0.03s call tests/test_widget_robotics.py::test_identity\n4 passed in 0.07s', 'seconds': 0.08},
                             source_manifest_sha256='before')
        timed = copy.deepcopy(first)
        timed['result']['result'].update(output='4.00s call tests/test_widget_robotics.py::test_identity\n4 passed in 4.03s', seconds=4.10)
        self.assertEqual(evidence_fingerprint(first), evidence_fingerprint(timed))
        for change in ({'exit_code': 1}, {'output': '3 passed, 1 failed in 4.03s'}):
            altered = copy.deepcopy(timed)
            altered['result']['result'].update(change)
            self.assertNotEqual(evidence_fingerprint(first), evidence_fingerprint(altered))
        timed['result']['source_manifest_sha256'] = 'after'
        self.assertNotEqual(evidence_fingerprint(first), evidence_fingerprint(timed))

    def test_new_file_hash_or_excerpt_is_new_progress_failed_or_pending_is_not(self):
        first = self.reads()[0]
        changed = copy.deepcopy(first)
        changed['result']['result']['sha256'] = 'changed'
        self.assertNotEqual(evidence_fingerprint(first), evidence_fingerprint(changed))
        changed = copy.deepcopy(first)
        changed['arguments']['start_line'] = 120
        changed['result']['result']['text'] = '120: next assertions'
        self.assertNotEqual(evidence_fingerprint(first), evidence_fingerprint(changed))
        self.assertIsNone(evidence_fingerprint({'name': 'code_read', 'result': None}))
        self.assertIsNone(evidence_fingerprint({'name': 'code_read', 'result': {'ok': False, 'error': 'missing'}}))


if __name__ == '__main__':
    unittest.main()
