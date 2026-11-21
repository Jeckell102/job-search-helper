"""M3 outcomes enter the existing coordinator without dispatching work."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from coordinator_store import Store, canonical_scrape_outcome
from coordinator import Coordinator
import test_coordinator as coordinator_fixture


def outcome(**changes):
    identity = {
        'request_id': 'company-event:CEV-1', 'company_id': 'COMP-0001',
        'source_revision': 'rev-1', 'provider': 'greenhouse', 'adapter_version': 'adapter-1',
    }
    identity.update(changes.pop('identity', {}))
    identity = {key: value for key, value in identity.items() if value is not None}
    result = {
        'outcome': 'QUALIFIED_INTEGRATION_REPAIR', 'action': 'upsert_qualified_repair',
        'identity': identity, 'failure_fingerprint': 'a' * 64,
    }
    result.update(changes)
    immutable = {key: result[key] for key in ('identity', 'failure_fingerprint', 'outcome')}
    result['outcome_id'] = 'OUT-' + hashlib.sha256(
        json.dumps(immutable, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:24]
    return result


def facts(**changes):
    result = {
        'request_id': 'company-event:CEV-1', 'company_id': 'COMP-0001',
        'source_revision': 'rev-1', 'provider': 'greenhouse', 'adapter_version': 'adapter-1',
        'source_current': True, 'company_status': 'Active', 'storage_status': 'confirmed',
        'inventory_status': 'partial', 'capability': 'qualified',
        'failure': {'category': 'adapter_regression'},
    }
    result.update(changes)
    return result


class OutcomeIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.coordinator = Coordinator(base=self.temp.name)

    def test_qualified_outcome_creates_one_held_repair_without_a_task(self):
        item = facts()
        first = self.store.ingest_scrape_outcome(item)
        self.assertTrue(first['recorded'])
        self.assertEqual(first['status'], 'HELD_FOR_REPAIR_TRIAGE')
        self.assertFalse(self.store.ingest_scrape_outcome(item)['recorded'])
        held = self.store.held_repair_intake()
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0]['outcome']['outcome'], 'QUALIFIED_INTEGRATION_REPAIR')
        self.assertEqual(self.store.all(), [])

    def test_untrusted_fields_or_identifier_are_rejected(self):
        item = outcome()
        item['identity']['raw_private'] = 'should never enter coordinator storage'
        with self.assertRaisesRegex(ValueError, 'invalid identity'):
            canonical_scrape_outcome(item)
        with self.assertRaisesRegex(ValueError, 'Invalid trusted'):
            self.store.ingest_scrape_outcome(outcome())
        accepted = self.store.ingest_scrape_outcome({
            **facts(), 'outcome': 'FORGED', 'action': 'dispatch-everything',
            'identity': {}, 'outcome_id': 'OUT-forged',
        })
        self.assertEqual(accepted['status'], 'HELD_FOR_REPAIR_TRIAGE')
        self.assertNotEqual(accepted['outcome_id'], 'OUT-forged')

    def test_missing_provider_or_adapter_holds_without_a_repair_key(self):
        item = facts(provider=None)
        result = self.store.ingest_scrape_outcome(item)
        self.assertEqual(result['status'], 'HELD_MISSING_REPAIR_CAPABILITY')
        self.assertIsNone(result['repair_key'])
        self.assertEqual(self.store.held_repair_intake(), [])

    def test_repeated_attempts_attach_evidence_to_one_held_repair(self):
        first = self.store.ingest_scrape_outcome(facts(request_id='REQ-1'))
        second = self.store.ingest_scrape_outcome(facts(request_id='REQ-2'))
        self.assertTrue(first['recorded'])
        self.assertTrue(second['recorded'])
        self.assertEqual(first['repair_key'], second['repair_key'])
        held = self.store.held_repair_intake()
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0]['evidence_outcome_ids'], sorted([first['outcome_id'], second['outcome_id']]))

    def test_pre_evidence_relation_repair_reads_as_no_attached_evidence(self):
        item = facts()
        result = self.store.ingest_scrape_outcome(item)
        with self.store.connect() as db:
            db.execute('DELETE FROM repair_intake_evidence WHERE repair_key=?', (result['repair_key'],))
        held = self.store.held_repair_intake()
        self.assertEqual(held[0]['evidence_outcome_ids'], [])

    def test_command_intake_holds_a_qualified_repair_without_starting_worker(self):
        result = self.coordinator.command({'action': 'ingest-scrape-outcome', 'facts': facts()})

        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'HELD_FOR_REPAIR_TRIAGE')
        self.assertTrue(result['repair_key'])
        self.assertEqual(self.coordinator.store.all(), [])
        self.assertEqual(len(self.coordinator.store.held_repair_intake()), 1)
        self.assertIn('no worker was started', result['text'])

    def test_command_intake_rejects_extra_untrusted_wrapper_fields(self):
        with self.assertRaisesRegex(ValueError, 'exactly action and facts'):
            self.coordinator.command({'action': 'ingest-scrape-outcome', 'facts': facts(), 'start': True})
        self.assertEqual(self.coordinator.store.all(), [])

    def test_immutable_record_retry_does_not_reclassify_or_start_worker(self):
        record = outcome()
        result = self.coordinator.command({
            'action': 'ingest-scrape-outcome-record', 'record': record,
        })
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'HELD_FOR_REPAIR_TRIAGE')
        self.assertFalse(self.coordinator.command({
            'action': 'ingest-scrape-outcome-record', 'record': record,
        })['recorded'])
        self.assertEqual(self.coordinator.store.all(), [])

    def test_repaired_retry_supersedes_original_repair_even_when_original_arrived_first(self):
        original = self.store.ingest_scrape_outcome(facts())
        retry = self.store.ingest_scrape_outcome(facts(
            request_id='company-retry:RTRY-1', failed_request_id='company-event:CEV-1',
            attempt_id='RTRY-1', release_version='REL-1', release_binding_sha256='b' * 64, inventory_status='complete',
            failure={'category': 'none'}))
        self.assertEqual(retry['status'], 'VALIDATED_COMPLETE')
        held = {item['repair_key']: item for item in self.store.held_repair_intake()}
        self.assertEqual(held[original['repair_key']]['status'], 'SUPERSEDED_BY_REPAIRED_RETRY')
        replay = self.store.ingest_scrape_outcome(facts())
        self.assertFalse(replay['recorded'])
        self.assertEqual(replay['status'], 'SUPERSEDED_BY_REPAIRED_RETRY')

    def test_late_original_failure_cannot_reopen_after_repaired_retry(self):
        retry = self.store.ingest_scrape_outcome(facts(
            request_id='company-retry:RTRY-1', failed_request_id='company-event:CEV-1',
            attempt_id='RTRY-1', release_version='REL-1', release_binding_sha256='b' * 64, inventory_status='complete',
            failure={'category': 'none'}))
        late = self.store.ingest_scrape_outcome(facts())
        self.assertTrue(late['recorded'])
        self.assertEqual(late['status'], 'SUPERSEDED_BY_REPAIRED_RETRY')
        self.assertIsNone(late['repair_key'])
        self.assertEqual(self.store.held_repair_intake(), [])

    def test_competing_successor_for_same_failed_request_is_rejected(self):
        self.store.ingest_scrape_outcome(facts(
            request_id='company-retry:RTRY-1', failed_request_id='company-event:CEV-1',
            attempt_id='RTRY-1', release_version='REL-1', release_binding_sha256='b' * 64, inventory_status='complete',
            failure={'category': 'none'}))
        with self.assertRaisesRegex(ValueError, 'different repaired retry'):
            self.store.ingest_scrape_outcome(facts(
                request_id='company-retry:RTRY-2', failed_request_id='company-event:CEV-1',
                attempt_id='RTRY-2', release_version='REL-2', release_binding_sha256='c' * 64, inventory_status='complete',
                failure={'category': 'none'}))

    def test_failed_repaired_attempt_gets_fresh_repair_identity(self):
        original = self.store.ingest_scrape_outcome(facts())
        retry = self.store.ingest_scrape_outcome(facts(
            request_id='company-retry:RTRY-1', failed_request_id='company-event:CEV-1',
            attempt_id='RTRY-1', release_version='REL-1', release_binding_sha256='b' * 64))
        self.assertEqual(retry['status'], 'ROLLBACK_REQUIRED')
        self.assertNotEqual(retry['repair_key'], original['repair_key'])
        held = {item['repair_key']: item for item in self.store.held_repair_intake()}
        self.assertEqual(held[original['repair_key']]['status'], 'SUPERSEDED_BY_REPAIRED_RETRY')
        self.assertEqual(held[retry['repair_key']]['status'], 'ROLLBACK_REQUIRED')

    def test_partial_retry_lineage_is_rejected(self):
        item = outcome(identity={'attempt_id': 'RTRY-1', 'release_version': 'REL-1'})
        with self.assertRaisesRegex(ValueError, 'must bind attempt'):
            canonical_scrape_outcome(item)
        with self.assertRaisesRegex(ValueError, 'must bind attempt'):
            canonical_scrape_outcome(outcome(identity={'attempt_id': 'legacy-attempt'}))


class HeldRepairPromotionTests(coordinator_fixture.CoordinatorTests):
    def test_promoted_repair_enters_existing_isolated_pilot_without_opening_queue(self):
        self.co.workflow_version = 2
        self.co.store.company_revision_resolver = lambda company_id: 'rev-1'
        self.co.command({'action': 'queue-pause'})
        baseline = Path(self.tmp.name) / 'queue-base'
        shutil.copytree(self.root, baseline)
        (baseline / 'src/a.py').write_text('value = 2\n')
        with patch('coordinator_workspace.batch_source', return_value=baseline):
            repair, response = self.promoted()
            before = self.co.store.get(response['id'])
            self.assertEqual(before['status'], 'PAUSED')
            self.assertTrue(before.get('isolated_workspace'))
            self.assertFalse((self.co.store.base / response['id'] / 'repo').exists())
            self.assertEqual(self.promoted()[1]['id'], response['id'])
            self.co.command({'action': 'pilot-start', 'id': response['id']})
        state = self.co.store.get(response['id'])
        target = self.co.store.base / response['id'] / 'repo'
        self.assertEqual((target / 'src/a.py').read_text(), 'value = 2\n')
        self.assertEqual((self.root / 'src/a.py').read_text(), 'value = 1\n')
        self.assertEqual(state['status'], 'QUEUED')
        self.assertEqual(state['repair_provenance'], before['repair_provenance'])
        self.assertEqual(state['held_repair_key'], repair['repair_key'])
        self.assertEqual(state['integration_identity'], before['integration_identity'])
        self.assertEqual(state['edit_scope'], before['edit_scope'])
        self.assertEqual(state['tests'], ['tests/test_a.py'])
        self.assertEqual(state['assignment_baseline'], before['assignment_baseline'])
        self.assertEqual(len(self.co.store.all()), 1)
        self.assertEqual(self.co.store.pilot_task(), response['id'])
        self.assertFalse(self.co.store.queue_enabled())
        self.assertFalse(self.co.store.campaign_enabled())
        self.assertFalse(self.co.store.autopilot_enabled())
        self.assertEqual(self.co.store.receipts(response['id']), [])
        self.assertEqual(self.co.store.inference_receipts(response['id']), [])
        self.assertEqual(self.history, [])

    def promoted(self):
        repair = self.co.store.ingest_scrape_outcome(facts())
        response = self.co.command({
            'action': 'promote-repair', 'repair_key': repair['repair_key'], 'source_revision': 'rev-1', 'mode': 'develop',
            'objective': 'Develop the bounded Acme wrapper using src/a.py and run tests/test_a.py.',
            'integration': {
                'company_id': 'COMP-0001', 'company': 'Acme', 'configured_url': 'https://jobs.example.test/acme',
                'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'], 'ats': 'Greenhouse',
            },
        })
        return repair, response

    def test_promotion_creates_one_paused_task_not_a_runnable_task(self):
        repair, response = self.promoted()
        state = self.co.store.get(response['id'])
        self.assertEqual(state['status'], 'PAUSED')
        self.assertTrue(state['stop_requested'])
        self.assertEqual(state['held_repair_key'], repair['repair_key'])
        self.assertEqual(state['repair_provenance']['source_revision'], 'rev-1')
        self.assertIsNone(self.co.store.claim_queued())
        self.assertEqual(self.co.store.held_repair_intake()[0]['task_id'], state['id'])
        self.assertEqual(self.promoted()[1]['id'], state['id'])
        self.assertEqual(len(self.co.store.all()), 1)
        restarted = Store(self.co.store.base)
        restarted.recover()
        self.assertEqual(restarted.get(state['id'])['status'], 'PAUSED')
        self.assertEqual(restarted.held_repair_intake()[0]['task_id'], state['id'])

    def test_promotion_refuses_an_assignment_for_another_company(self):
        repair = self.co.store.ingest_scrape_outcome(facts())
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.co.command({
                'action': 'promote-repair', 'repair_key': repair['repair_key'], 'source_revision': 'rev-1', 'mode': 'develop',
                'objective': 'Develop another wrapper using src/a.py and run tests/test_a.py.',
                'integration': {
                    'company_id': 'COMP-0002', 'company': 'Other', 'configured_url': 'https://jobs.example.test/other',
                    'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'], 'ats': 'Greenhouse',
                },
            })

    def test_promotion_refuses_a_stale_source_revision(self):
        repair = self.co.store.ingest_scrape_outcome(facts())
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.co.command({
                'action': 'promote-repair', 'repair_key': repair['repair_key'], 'source_revision': 'rev-stale', 'mode': 'develop',
                'objective': 'Develop the bounded Acme wrapper using src/a.py and run tests/test_a.py.',
                'integration': {
                    'company_id': 'COMP-0001', 'company': 'Acme', 'configured_url': 'https://jobs.example.test/acme',
                    'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'], 'ats': 'Greenhouse',
                },
            })
        self.assertEqual(self.co.store.all(), [])

    def test_repeat_promotion_still_refuses_wrong_company_or_revision(self):
        repair, response = self.promoted()
        base = {
            'action': 'promote-repair', 'repair_key': repair['repair_key'], 'mode': 'develop',
            'objective': 'Develop the bounded Acme wrapper using src/a.py and run tests/test_a.py.',
            'integration': {
                'company_id': 'COMP-0001', 'company': 'Acme', 'configured_url': 'https://jobs.example.test/acme',
                'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'], 'ats': 'Greenhouse',
            },
        }
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.co.command({**base, 'source_revision': 'rev-stale'})
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.co.command({**base, 'source_revision': 'rev-1', 'integration': {
                **base['integration'], 'company_id': 'COMP-0002', 'company': 'Other',
            }})
        self.assertEqual(self.co.store.get(response['id'])['status'], 'PAUSED')

    def test_promoted_repair_needs_authoritative_current_company_revision_before_resume(self):
        repair, response = self.promoted()
        with self.assertRaisesRegex(ValueError, 'authoritative current Company revision'):
            self.co.command({'action': 'resume', 'id': response['id']})
        self.assertEqual(self.co.store.get(response['id'])['status'], 'PAUSED')
        self.co.store.company_revision_resolver = lambda company_id: 'rev-1'
        self.co.command({'action': 'resume', 'id': response['id']})
        self.assertEqual(self.co.store.get(response['id'])['status'], 'QUEUED')

    def test_stale_promoted_repair_cannot_resume_or_be_claimed(self):
        repair, response = self.promoted()
        self.co.store.company_revision_resolver = lambda company_id: 'rev-newer'
        with self.assertRaisesRegex(ValueError, 'authoritative current Company revision'):
            self.co.command({'action': 'resume', 'id': response['id']})
        self.co.store.update(response['id'], status='QUEUED', stop_requested=False)
        self.assertIsNone(self.co.store.claim_queued(response['id']))
        state = self.co.store.get(response['id'])
        self.assertEqual(state['status'], 'PAUSED')
        self.assertTrue(state['stop_requested'])
        self.assertIn('no longer current', state['reason'])

    def test_stale_promoted_repair_cannot_bypass_freshness_with_direct_step(self):
        repair, response = self.promoted()
        self.co.store.company_revision_resolver = lambda company_id: 'rev-newer'
        self.co.store.update(response['id'], status='QUEUED', stop_requested=False)
        self.co.step(response['id'])
        state = self.co.store.get(response['id'])
        self.assertEqual(state['status'], 'PAUSED')
        self.assertTrue(state['stop_requested'])
        self.assertEqual(self.co.store.receipts(response['id']), [])

    def test_unmatched_automatic_profile_keeps_repair_held_without_a_task(self):
        repair = self.co.store.ingest_scrape_outcome(facts())
        result = self.co.command({'action': 'prepare-held-repair', 'repair_key': repair['repair_key']})
        self.assertEqual(result['status'], 'HELD_FOR_ENGINEERING_REVIEW')
        self.assertEqual(self.co.store.all(), [])

    def test_matched_automatic_profile_creates_only_one_paused_task(self):
        repair = self.co.store.ingest_scrape_outcome(facts())
        self.co.repair_profile_selector = lambda held: {
            'profile_id': 'fixture-v1', 'source_revision': 'rev-1', 'mode': 'develop',
            'objective': 'Develop the bounded Acme wrapper using src/a.py and run tests/test_a.py.',
            'max_sessions': 2,
            'integration': {
                'company_id': 'COMP-0001', 'company': 'Acme',
                'configured_url': 'https://jobs.example.test/acme',
                'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'], 'ats': 'Greenhouse',
            },
        }
        first = self.co.command({'action': 'prepare-held-repair', 'repair_key': repair['repair_key']})
        state = self.co.store.get(first['id'])
        self.assertEqual(state['status'], 'PAUSED')
        self.assertTrue(state['stop_requested'])
        self.assertEqual(first['profile_id'], 'fixture-v1')
        self.assertTrue(state['isolated_workspace'])
        self.assertEqual(self.co.command({'action': 'prepare-held-repair', 'repair_key': repair['repair_key']})['id'], first['id'])
        self.assertEqual(len(self.co.store.all()), 1)


if __name__ == '__main__':
    unittest.main()
