"""Exercise the operator retry command against real pinned mapping inputs."""
import unittest
from unittest.mock import patch
import coordinator as c
import test_coordinator as fixture
from coordinator_identity import validate_bound_identity

class RetryCommandRefreshTests(unittest.TestCase):
    setUp = fixture.CoordinatorTests.setUp

    def prepare(self):
        self.co.workflow_version = 2
        folder = self.root / 'src/job_search_helper'
        folder.mkdir()
        (folder / 'company_sources.py').write_text('REPAIRS={"COMP-0001": {"company":"Company A", "expected_url":"https://example.com/careers", "url":"https://jobs.example.com/a"}}')
        item = {'objective': 'Repair Company A src/a.py tests/test_a.py', 'mode': 'develop',
            'integration': {'company_id': 'COMP-0001', 'company': 'Company A',
                'configured_url': 'https://example.com/careers', 'tests': ['tests/test_a.py'],
                'source_targets': ['src/a.py']}}
        original_builder = c.build_requirements
        def legacy_builder(*args, **kwargs):
            requirements = original_builder(*args, **kwargs)
            requirements.pop('investigation_targets', None)
            return requirements
        with patch.object(c, 'build_requirements', side_effect=legacy_builder):
            task = self.co.command({'action': 'batch', 'items': [item]})['ids'][0]
        self.co.store.configure_queue(False)
        return task, self.co.store.get(task)

    def test_real_retry_command_refreshes_mapping_without_free_text_targets(self):
        task, before = self.prepare()
        result = self.co.command({'action': 'retry', 'id': task,
            'investigation_targets': [{'url': 'https://attacker.example'}]})
        self.assertTrue(result['ok'])
        state = self.co.store.get(result['state']['id'])
        self.assertEqual(state['evidence_requirements']['investigation_targets'], [{
            'url': 'https://jobs.example.com/a', 'allowed_urls': ['https://jobs.example.com/a'],
            'identity_terms': ['Company A'], 'purpose': 'configured_listing'}])
        self.assertEqual(self.co.store.get(task), before)
        validate_bound_identity(state)
        self.assertEqual(self.history, [])

    def test_source_baseline_drift_prevents_any_successor(self):
        task, before = self.prepare()
        (self.root / 'src/job_search_helper/company_sources.py').write_text('REPAIRS={}\n')
        with self.assertRaisesRegex(ValueError, 'baseline drift'):
            self.co.command({'action': 'retry', 'id': task})
        self.assertEqual(self.co.store.get(task), before)
        self.assertEqual(len(self.co.store.all()), 1)

    def test_unbound_mapping_cannot_refresh_even_from_builder(self):
        task, before = self.prepare()
        proposed = {'investigation_targets': [{'url': 'https://other.example/jobs',
            'allowed_urls': ['https://other.example/jobs'], 'identity_terms': ['Company A'],
            'purpose': 'configured_listing'}]}
        with patch.object(c, 'build_requirements', return_value=proposed):
            with self.assertRaisesRegex(ValueError, 'outside the original source binding'):
                self.co.command({'action': 'retry', 'id': task})
        self.assertEqual(self.co.store.get(task), before)
        self.assertEqual(len(self.co.store.all()), 1)

if __name__ == '__main__': unittest.main()
