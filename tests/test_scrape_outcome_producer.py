import unittest

from job_search_helper.company_events import source_revision
from job_search_helper.repair_retry import (
    REPAIR_RETRY_SCHEMA, RELEASE_BINDING_SCHEMA, release_binding_sha256,
    retry_attempt_id,
)
from job_search_helper.scrape_outcome_producer import record_cycle_outcomes


class Repository:
    def __init__(self): self.facts = []
    def record_scrape_outcome(self, facts):
        self.facts.append(facts)
        return {'outcome_id': 'OUT-' + str(len(self.facts)), 'recorded': True, 'outcome': facts}


class OutcomeProducerTests(unittest.TestCase):
    def setUp(self):
        self.company = {'Company ID': 'COMP-1', 'Company Status': 'Active',
                        'Official Careers URL': 'https://jobs.example.test', 'ATS / Source': 'Greenhouse'}

    def test_complete_scoped_cycle_records_confirmed_bounded_outcome(self):
        repo = Repository()
        cycle = {'id': 'CYC-1', 'start_request_id': 'REQ-1', 'company_event': {
            'event_id': 'CEV-1', 'source_revision': source_revision(self.company)},
            'companies': {'COMP-1': {'stage': 'complete', 'ats': 'Greenhouse'}}}
        result = record_cycle_outcomes(repo, cycle, [self.company], storage_confirmed=True)
        self.assertEqual(len(result), 1)
        self.assertEqual(repo.facts[0]['inventory_status'], 'complete')
        self.assertEqual(repo.facts[0]['storage_status'], 'confirmed')
        self.assertTrue(repo.facts[0]['source_current'])

    def test_unconfirmed_or_ambiguous_work_cannot_create_repair_facts(self):
        repo = Repository()
        cycle = {'id': 'CYC-1', 'companies': {'COMP-1': {'stage': 'failed'}}}
        record_cycle_outcomes(repo, cycle, [self.company], storage_confirmed=False)
        self.assertEqual(repo.facts[0]['storage_status'], 'sync_pending')
        self.assertEqual(repo.facts[0]['failure']['category'], 'unknown')

    def test_unsafe_checkpoint_facts_are_skipped_without_disrupting_the_scrape(self):
        cases = (({**self.company, 'Company ID': 'X' * 257}, 'X' * 257),
                 ({**self.company, 'Company Status': ['not-text']}, 'COMP-1'),
                 ({**self.company, 'Official Careers URL': 'not-a-url'}, 'COMP-1'))
        for company, company_id in cases:
            with self.subTest(company=company):
                repo = Repository()
                cycle = {'id': 'CYC-1', 'companies': {company_id: {'stage': 'complete'}}}
                self.assertEqual(record_cycle_outcomes(repo, cycle, [company], storage_confirmed=True), [])
                self.assertEqual(repo.facts, [])

    def test_repaired_retry_outcome_preserves_attempt_and_release_identity(self):
        repo = Repository()
        release = {'schema': RELEASE_BINDING_SCHEMA, 'release_id': 'REL-1',
                   'source_manifest_sha256': '1' * 64,
                   'dependency_manifest_sha256': '2' * 64,
                   'config_sha256': '3' * 64}
        retry = {'schema': REPAIR_RETRY_SCHEMA, 'attempt_id': '', 'failed_request_id': 'REQ-failed',
                 'company_id': 'COMP-1', 'source_revision': source_revision(self.company),
                 'activated_at': '2026-11-19T12:00:00Z', 'release': release}
        retry['attempt_id'] = retry_attempt_id(retry)
        cycle = {'id': 'CYC-1', 'companies': {'COMP-1': {'stage': 'complete'}},
                 'repair_retry': retry}
        record_cycle_outcomes(repo, cycle, [self.company], storage_confirmed=True)
        self.assertEqual(repo.facts[0]['attempt_id'], retry['attempt_id'])
        self.assertEqual(repo.facts[0]['failed_request_id'], 'REQ-failed')
        self.assertEqual(repo.facts[0]['release_version'], 'REL-1')
        self.assertEqual(repo.facts[0]['release_binding_sha256'], release_binding_sha256(release))

    def test_malformed_retry_lineage_cannot_produce_a_repair_outcome(self):
        repo = Repository()
        cycle = {'id': 'CYC-1', 'companies': {'COMP-1': {'stage': 'complete'}},
                 'repair_retry': {'attempt_id': 'RTRY-1', 'release': {'release_id': 'REL-1'}}}
        self.assertEqual(record_cycle_outcomes(repo, cycle, [self.company], storage_confirmed=True), [])
        self.assertEqual(repo.facts, [])
