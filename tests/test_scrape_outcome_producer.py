import unittest

from job_search_helper.company_events import source_revision
from job_search_helper.outcomes import UNCLASSIFIED_HOLD, classify_outcome
from job_search_helper.ats import Inventory
from job_search_helper.engine import inventory_payload
from job_search_helper.repair_retry import (
    REPAIR_RETRY_SCHEMA, RELEASE_BINDING_SCHEMA, release_binding_sha256,
    retry_attempt_id,
)
from job_search_helper.scrape_outcome_producer import (
    normal_cycle_outcome_facts, record_cycle_outcomes,
)


class Repository:
    def __init__(self): self.facts = []
    def record_scrape_outcome(self, facts):
        self.facts.append(facts)
        return {'outcome_id': 'OUT-' + str(len(self.facts)), 'recorded': True, 'outcome': facts}


class OutcomeProducerTests(unittest.TestCase):
    def setUp(self):
        self.company = {'Company ID': 'COMP-1', 'Company Status': 'Active',
                        'Official Careers URL': 'https://jobs.example.test', 'ATS / Source': 'Greenhouse'}

    def test_complete_normal_cycle_records_confirmed_bounded_outcome(self):
        repo = Repository()
        cycle = {'id': 'CYC-1', 'companies': {'COMP-1': {
            'stage': 'complete', 'inventory_status': 'complete',
            'outcome_source_revision': source_revision(self.company), 'ats': 'Greenhouse'}}}
        result = record_cycle_outcomes(repo, cycle, [self.company], storage_confirmed=True)
        self.assertEqual(len(result), 1)
        self.assertEqual(repo.facts[0]['inventory_status'], 'complete')
        self.assertEqual(repo.facts[0]['storage_status'], 'confirmed')
        self.assertTrue(repo.facts[0]['source_current'])

    def test_unconfirmed_or_ambiguous_work_cannot_create_repair_facts(self):
        repo = Repository()
        cycle = {'id': 'CYC-1', 'companies': {'COMP-1': {
            'stage': 'failed', 'inventory_status': 'failed',
            'outcome_source_revision': source_revision(self.company)}}}
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
                cycle = {'id': 'CYC-1', 'companies': {company_id: {
                    'stage': 'complete', 'inventory_status': 'complete',
                    'outcome_source_revision': 'saved-source-revision'}}}
                self.assertEqual(record_cycle_outcomes(repo, cycle, [company], storage_confirmed=True), [])
                self.assertEqual(repo.facts, [])

    def test_pending_browser_or_incomplete_discovery_downgrades_to_partial_hold(self):
        repo = Repository()
        cycle = {'id': 'CYC-1', 'companies': {'COMP-1': {
            'stage': 'complete', 'inventory_status': 'complete',
            'outcome_source_revision': source_revision(self.company),
            'browser_pending_urls': ['https://jobs.example.test/role/1'],
            'browser_discovery_incomplete': True,
        }}}
        record_cycle_outcomes(repo, cycle, [self.company], storage_confirmed=True)
        self.assertEqual('partial', repo.facts[0]['inventory_status'])
        self.assertEqual('unknown', repo.facts[0]['failure']['category'])

    def test_stale_after_storage_is_recorded_as_bounded_audit_evidence(self):
        repo = Repository()
        cycle = {'id': 'CYC-1', 'companies': {'COMP-1': {
            'stage': 'partial', 'inventory_status': 'partial',
            'outcome_source_revision': 'old-source-revision',
        }}}
        result = record_cycle_outcomes(repo, cycle, [self.company], storage_confirmed=True)
        self.assertEqual(1, len(repo.facts))
        self.assertEqual(1, len(result))
        self.assertFalse(repo.facts[0]['source_current'])

    def test_storage_failure_is_recorded_for_reconciliation_not_repair(self):
        repo = Repository()
        cycle = {'id': 'CYC-1', 'companies': {'COMP-1': {
            'stage': 'complete', 'inventory_status': 'complete',
            'outcome_source_revision': source_revision(self.company),
        }}}
        record_cycle_outcomes(repo, cycle, [self.company], storage_confirmed=False)
        self.assertEqual('sync_pending', repo.facts[0]['storage_status'])

    def test_adapter_is_bounded_and_missing_completion_evidence_holds(self):
        item = {'stage': 'complete', 'inventory_status': 'unexpected',
                'outcome_source_revision': source_revision(self.company), 'ats': 'Greenhouse'}
        facts = normal_cycle_outcome_facts({'id': 'CYC-1'}, self.company, item,
                                           storage_confirmed=True)
        self.assertEqual('partial', facts['inventory_status'])
        self.assertEqual('unknown', facts['failure']['category'])
        item['outcome_source_revision'] = 'x' * 257
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            normal_cycle_outcome_facts({'id': 'CYC-1'}, self.company, item,
                                       storage_confirmed=True)

    def test_missing_saved_source_revision_is_an_unclassified_hold(self):
        facts = normal_cycle_outcome_facts(
            {'id': 'CYC-1'}, self.company,
            {'stage': 'complete', 'inventory_status': 'complete'},
            storage_confirmed=True)
        self.assertIsNone(facts['source_current'])
        self.assertEqual(UNCLASSIFIED_HOLD, classify_outcome(facts)['outcome'])

    def test_cycle_provenance_drives_current_and_changed_post_storage_outcomes(self):
        payload = inventory_payload(
            Inventory('complete', [], source_url='https://jobs.example.test', ats='Greenhouse'),
            self.company)
        # F6 receipt/input payload bytes deliberately remain unchanged by M3.
        self.assertNotIn('outcome_source_revision', payload)
        cycle = {'id': 'CYC-1', 'companies': {'COMP-1': {
            **payload, 'stage': 'complete',
            'outcome_source_revision': source_revision(self.company)}}}
        current = normal_cycle_outcome_facts(cycle, self.company,
                                             cycle['companies']['COMP-1'], storage_confirmed=True)
        self.assertTrue(current['source_current'])
        self.assertEqual('complete', current['inventory_status'])
        self.assertEqual(source_revision(self.company), current['source_revision'])
        self.assertEqual(source_revision(self.company),
                         current['current_source_revision'])
        classified_current = classify_outcome(current)
        canonical_old_shape = dict(current)
        canonical_old_shape.pop('current_source_revision')
        self.assertNotIn('comparison', classified_current)
        self.assertEqual(classified_current['outcome_id'],
                         classify_outcome(canonical_old_shape)['outcome_id'])

        changed = {**self.company, 'ATS / Source': 'Lever'}
        repo = Repository()
        record_cycle_outcomes(repo, cycle, [changed], storage_confirmed=True)
        self.assertFalse(repo.facts[0]['source_current'])
        self.assertEqual(source_revision(self.company), repo.facts[0]['source_revision'])
        self.assertEqual(source_revision(changed), repo.facts[0]['current_source_revision'])
        self.assertEqual('STALE_OR_PAUSED', classify_outcome(repo.facts[0])['outcome'])

    def test_frozen_identity_and_current_comparison_have_deterministic_outcome_ids(self):
        frozen = source_revision(self.company)
        changed = {**self.company, 'ATS / Source': 'Lever'}
        item = {'stage': 'partial', 'inventory_status': 'partial',
                'outcome_source_revision': frozen}
        facts = normal_cycle_outcome_facts({'id': 'CYC-1'}, changed, item,
                                           storage_confirmed=True)
        one, two = classify_outcome(facts), classify_outcome(dict(facts))
        self.assertEqual(frozen, one['identity']['source_revision'])
        self.assertEqual(source_revision(changed), one['comparison']['current_source_revision'])
        self.assertEqual(one['outcome_id'], two['outcome_id'])

    def test_verified_zero_openings_is_complete_only_with_saved_proof(self):
        item = {'stage': 'complete', 'inventory_status': 'zero',
                'zero_openings_verified': True,
                'outcome_source_revision': source_revision(self.company)}
        facts = normal_cycle_outcome_facts({'id': 'CYC-1'}, self.company, item,
                                           storage_confirmed=True)
        self.assertTrue(facts['zero_openings_verified'])
        self.assertEqual('COMPLETE', classify_outcome(facts)['outcome'])

    def test_company_event_operator_and_recovery_cycles_are_excluded(self):
        for key in ('company_event', 'operator_request', 'recovery_pause'):
            with self.subTest(key=key):
                repo = Repository()
                cycle = {'id': 'CYC-1', key: {'id': key}, 'companies': {'COMP-1': {
                    'stage': 'complete', 'inventory_status': 'complete',
                    'outcome_source_revision': source_revision(self.company)}}}
                self.assertEqual([], record_cycle_outcomes(
                    repo, cycle, [self.company], storage_confirmed=True))
                self.assertEqual([], repo.facts)

    def test_repair_retry_outcome_retains_full_attempt_and_release_identity(self):
        repo = Repository()
        release = {'schema': RELEASE_BINDING_SCHEMA, 'release_id': 'REL-1',
                   'source_manifest_sha256': '1' * 64,
                   'dependency_manifest_sha256': '2' * 64,
                   'config_sha256': '3' * 64}
        retry = {'schema': REPAIR_RETRY_SCHEMA, 'attempt_id': '', 'failed_request_id': 'REQ-failed',
                 'company_id': 'COMP-1', 'source_revision': source_revision(self.company),
                 'activated_at': '2026-11-19T12:00:00Z', 'release': release}
        retry['attempt_id'] = retry_attempt_id(retry)
        cycle = {'id': 'CYC-1', 'start_request_id': 'company-retry:' + retry['attempt_id'],
                 'companies': {'COMP-1': {'stage': 'complete'}},
                 'repair_retry': retry}
        result = record_cycle_outcomes(repo, cycle, [self.company], storage_confirmed=True)
        self.assertEqual(1, len(result))
        facts = repo.facts[0]
        self.assertEqual(retry['attempt_id'], facts['attempt_id'])
        self.assertEqual('REQ-failed', facts['failed_request_id'])
        self.assertEqual('REL-1', facts['release_version'])
        self.assertEqual(release_binding_sha256(release), facts['release_binding_sha256'])
        classified = classify_outcome(facts)
        self.assertEqual(retry['attempt_id'], classified['identity']['attempt_id'])
        self.assertEqual('REL-1', classified['identity']['release_version'])

    def test_retry_source_drift_records_stale_precedence_with_full_lineage(self):
        repo = Repository()
        release = {'schema': RELEASE_BINDING_SCHEMA, 'release_id': 'REL-1',
                   'source_manifest_sha256': '1' * 64,
                   'dependency_manifest_sha256': '2' * 64,
                   'config_sha256': '3' * 64}
        retry = {'schema': REPAIR_RETRY_SCHEMA, 'attempt_id': '', 'failed_request_id': 'REQ-failed',
                 'company_id': 'COMP-1', 'source_revision': source_revision(self.company),
                 'activated_at': '2026-11-19T12:00:00Z', 'release': release}
        retry['attempt_id'] = retry_attempt_id(retry)
        cycle = {'id': 'CYC-1', 'start_request_id': 'company-retry:' + retry['attempt_id'],
                 'companies': {'COMP-1': {
            'stage': 'partial', 'inventory_status': 'partial'}}, 'repair_retry': retry}
        changed = {**self.company, 'ATS / Source': 'Lever'}
        record_cycle_outcomes(repo, cycle, [changed], storage_confirmed=True)
        classified = classify_outcome(repo.facts[0])
        self.assertEqual('STALE_OR_PAUSED', classified['outcome'])
        self.assertEqual(retry['attempt_id'], classified['identity']['attempt_id'])

    def test_retry_outcome_rejects_missing_wrong_or_failed_request_identity(self):
        release = {'schema': RELEASE_BINDING_SCHEMA, 'release_id': 'REL-1',
                   'source_manifest_sha256': '1' * 64,
                   'dependency_manifest_sha256': '2' * 64,
                   'config_sha256': '3' * 64}
        retry = {'schema': REPAIR_RETRY_SCHEMA, 'attempt_id': '', 'failed_request_id': 'REQ-failed',
                 'company_id': 'COMP-1', 'source_revision': source_revision(self.company),
                 'activated_at': '2026-11-19T12:00:00Z', 'release': release}
        retry['attempt_id'] = retry_attempt_id(retry)
        for request_id in (None, 'company-retry:RTRY-unrelated', 'REQ-failed'):
            with self.subTest(request_id=request_id):
                repo = Repository()
                cycle = {'id': 'CYC-1', 'companies': {'COMP-1': {
                    'stage': 'complete', 'inventory_status': 'complete'}},
                         'repair_retry': retry}
                if request_id is not None:
                    cycle['start_request_id'] = request_id
                self.assertEqual([], record_cycle_outcomes(
                    repo, cycle, [self.company], storage_confirmed=True))
                self.assertEqual([], repo.facts)

    def test_retry_outcome_rejects_multi_company_cycle_scope(self):
        repo = Repository()
        release = {'schema': RELEASE_BINDING_SCHEMA, 'release_id': 'REL-1',
                   'source_manifest_sha256': '1' * 64,
                   'dependency_manifest_sha256': '2' * 64,
                   'config_sha256': '3' * 64}
        retry = {'schema': REPAIR_RETRY_SCHEMA, 'attempt_id': '', 'failed_request_id': 'REQ-failed',
                 'company_id': 'COMP-1', 'source_revision': source_revision(self.company),
                 'activated_at': '2026-11-19T12:00:00Z', 'release': release}
        retry['attempt_id'] = retry_attempt_id(retry)
        cycle = {'id': 'CYC-1', 'start_request_id': 'company-retry:' + retry['attempt_id'],
                 'companies': {
                     'COMP-1': {'stage': 'complete', 'inventory_status': 'complete'},
                     'COMP-2': {'stage': 'complete', 'inventory_status': 'complete'},
                 }, 'repair_retry': retry}
        self.assertEqual([], record_cycle_outcomes(
            repo, cycle, [self.company, {**self.company, 'Company ID': 'COMP-2'}],
            storage_confirmed=True))
        self.assertEqual([], repo.facts)

    def test_malformed_retry_lineage_cannot_produce_a_repair_outcome(self):
        repo = Repository()
        cycle = {'id': 'CYC-1', 'companies': {'COMP-1': {'stage': 'complete'}},
                 'repair_retry': {'attempt_id': 'RTRY-1', 'release': {'release_id': 'REL-1'}}}
        self.assertEqual(record_cycle_outcomes(repo, cycle, [self.company], storage_confirmed=True), [])
        self.assertEqual(repo.facts, [])
