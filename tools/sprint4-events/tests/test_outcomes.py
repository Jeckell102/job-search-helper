import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_search_helper.outcomes import (
    BLOCKED,
    COMPLETE,
    OutcomeFactsError,
    QUALIFIED_INTEGRATION_REPAIR,
    STALE_OR_PAUSED,
    STORAGE_OR_SYNC_FAILURE,
    TEMPORARY,
    UNCLASSIFIED_HOLD,
    UNKNOWN_CAPABILITY_HOLD,
    classify_outcome,
    validate_public_outcome_record,
)
from job_search_helper.repository import RepositoryError
from job_search_helper.engine import State
from job_search_helper.sqlite_repository import SQLiteRepository


def facts(**changes):
    value = {
        "request_id": "company-event:CEV-1", "company_id": "COMP-1", "source_revision": "rev-1",
        "company_event_id": "CEV-1", "cycle_id": "CYC-1", "attempt_id": "ATT-1",
        "provider": "greenhouse", "adapter_version": "adapter-1", "source_current": True,
        "company_status": "Active", "storage_status": "confirmed", "inventory_status": "partial",
        "capability": "qualified", "failure": {},
    }
    value.update(changes)
    return value


class OutcomeClassificationTests(unittest.TestCase):
    def test_retained_identity_does_not_admit_repaired_release_fields(self):
        from job_search_helper.retained_work_orchestrator import _cycle_id

        reservation = "1" * 64
        event = "CEV-" + "a" * 32
        retained = facts(
            request_id="company-event:" + event, company_event_id=event,
            source_revision="b" * 64, cycle_id=_cycle_id(reservation),
            retained_reservation_sha256=reservation, attempt_id=None,
        )
        self.assertIsNotNone(validate_public_outcome_record(classify_outcome(retained)))
        for changed in (
            {"cycle_id": "CYC-R000000000000"},
            {"request_id": "company-event:wrong"},
            {"retained_reservation_sha256": None},
            {"attempt_id": "foreign"},
        ):
            with self.subTest(changed=changed), self.assertRaisesRegex(OutcomeFactsError, "retained outcome"):
                classify_outcome(dict(retained, **changed))

    def test_sealed_mapping_identity_is_required_and_changes_outcome_id(self):
        base = facts(capability='sealed', failure={'category': 'same_provider_source_mapping'},
                     capability_id='rippling-shared-v1', capability_digest='a' * 64,
                     mapping_digest='b' * 64, configuration_digest='c' * 64)
        accepted = classify_outcome(base)
        self.assertEqual(QUALIFIED_INTEGRATION_REPAIR, accepted['outcome'])
        for key in ('capability_id', 'capability_digest', 'mapping_digest', 'configuration_digest'):
            self.assertEqual(base[key], accepted[key])
            self.assertNotIn(key, accepted['identity'])
        changed = classify_outcome(dict(base, configuration_digest='d' * 64))
        self.assertNotEqual(accepted['outcome_id'], changed['outcome_id'])
        with self.assertRaises(OutcomeFactsError):
            classify_outcome(dict(base, mapping_digest=None))
        with self.assertRaises(OutcomeFactsError):
            classify_outcome(facts(capability_id='rippling-shared-v1'))
        for nested in ({'identity': {'capability_id': 'rippling-shared-v1'}},
                       {'extension': {'mapping_digest': 'b' * 64}}):
            with self.subTest(nested=nested), self.assertRaisesRegex(
                    OutcomeFactsError, 'top-level'):
                classify_outcome(dict(base, **nested))

    def test_public_mapping_record_grammar_is_exact_and_digest_bound(self):
        source = facts(capability='sealed', failure={'category': 'same_provider_source_mapping'},
                       capability_id='rippling-shared-v1', capability_digest='a' * 64,
                       mapping_digest='b' * 64, configuration_digest='c' * 64)
        record = classify_outcome(source)
        self.assertEqual(record, validate_public_outcome_record(record))
        changed = classify_outcome(dict(source, configuration_digest='d' * 64))
        self.assertNotEqual(record['outcome_id'], changed['outcome_id'])
        capability = ('capability_id', 'capability_digest', 'mapping_digest', 'configuration_digest')
        bad = [
            {key: value for key, value in record.items() if key != 'mapping_digest'},
            dict(record, capability_digest='A' * 64),
            dict(record, repair_category='adapter_regression'),
            dict(record, extra='no'),
            dict(record, identity={**record['identity'], 'configuration_digest': 'c' * 64}),
            dict(record, identity={**record['identity'], 'capability_identity': {'id': 'x'}}),
        ]
        for value in bad:
            with self.subTest(value=value):
                self.assertIsNone(validate_public_outcome_record(value))
        for key in capability:
            self.assertIn(key, record)
            self.assertNotIn(key, record['identity'])

    def test_public_legacy_record_validation_preserves_exact_output_and_id(self):
        for source in (facts(failure={'category': 'adapter_regression'}),
                       facts(source_current=False, current_source_revision='rev-new'),
                       facts(failure={'category': 'temporary_transport'})):
            record = classify_outcome(source)
            self.assertEqual(record, validate_public_outcome_record(record))
            self.assertEqual(classify_outcome(source)['outcome_id'], record['outcome_id'])

    def test_stale_precedes_storage_and_failure_actions(self):
        result = classify_outcome(facts(
            source_current=False, storage_status="sync_failed",
            failure={"category": "adapter_regression"},
        ))
        self.assertEqual(result["outcome"], STALE_OR_PAUSED)
        self.assertEqual(result["action"], "stop_stale_work")

    def test_all_paused_or_removed_status_spellings_are_stale(self):
        for status in ('pause', 'paused', 'remove', 'removed', 'withdrawn'):
            with self.subTest(status=status):
                self.assertEqual(STALE_OR_PAUSED,
                                 classify_outcome(facts(company_status=status))['outcome'])

    def test_storage_failure_precedes_complete_or_repair(self):
        result = classify_outcome(facts(
            storage_status="sync_failed", inventory_status="complete",
            failure={"category": "adapter_regression"},
        ))
        self.assertEqual(result["outcome"], STORAGE_OR_SYNC_FAILURE)
        self.assertEqual(result["action"], "reconcile_storage_only")

    def test_complete_and_verified_zero_need_no_repair(self):
        self.assertEqual(classify_outcome(facts(inventory_status="complete"))["outcome"], COMPLETE)
        self.assertEqual(classify_outcome(facts(inventory_status="zero", zero_openings_verified=True))["outcome"], COMPLETE)
        self.assertEqual(classify_outcome(facts(inventory_status="zero"))["outcome"], UNCLASSIFIED_HOLD)

    def test_access_and_identity_blocks_hold(self):
        for category in ("authentication", "captcha", "access_denied", "uncertain_employer", "ambiguous_identity"):
            self.assertEqual(classify_outcome(facts(failure={"category": category}))["outcome"], BLOCKED)

    def test_temporary_problems_retry_without_code_repair(self):
        for category in ("timeout", "rate_limit", "temporary_transport", "temporary_provider", "server_error"):
            result = classify_outcome(facts(failure={"category": category, "http_status": 503}))
            self.assertEqual(result["outcome"], TEMPORARY)
            self.assertEqual(result["action"], "retry_with_bounded_backoff")

    def test_explicit_regression_requires_qualified_capability(self):
        accepted = classify_outcome(facts(failure={"category": "adapter_regression"}))
        self.assertEqual(accepted["outcome"], QUALIFIED_INTEGRATION_REPAIR)
        held = classify_outcome(facts(capability="unknown", failure={"category": "adapter_regression"}))
        self.assertEqual(held["outcome"], UNKNOWN_CAPABILITY_HOLD)

    def test_unknown_provider_is_engineering_hold(self):
        result = classify_outcome(facts(capability="new_provider", failure={"category": "unsupported"}))
        self.assertEqual(result["outcome"], UNKNOWN_CAPABILITY_HOLD)
        self.assertEqual(result["action"], "hold_for_engineering")

    def test_unclassified_incomplete_result_never_invents_a_repair(self):
        result = classify_outcome(facts(failure={"category": "odd_result"}))
        self.assertEqual(result["outcome"], UNCLASSIFIED_HOLD)
        self.assertEqual(result["action"], "hold_without_invented_repair")

    def test_missing_or_invalid_source_freshness_holds_without_a_repair(self):
        for value in (None, "yes", 1):
            item = facts(failure={"category": "adapter_regression"})
            if value is None:
                item.pop("source_current")
            else:
                item["source_current"] = value
            result = classify_outcome(item)
            self.assertEqual(result["outcome"], UNCLASSIFIED_HOLD)
            self.assertEqual(result["action"], "hold_for_source_freshness")

    def test_identity_is_stable_and_bounded(self):
        one = classify_outcome(facts(failure={"category": "timeout", "exception_type": "TimeoutError", "http_status": 504,
                                      "raw_error": "private detail one"}))
        two = classify_outcome(facts(failure={"category": "timeout", "exception_type": "TimeoutError", "http_status": 504,
                                      "raw_error": "private detail two"}))
        self.assertEqual(one["outcome_id"], two["outcome_id"])
        self.assertEqual(one["failure_fingerprint"], two["failure_fingerprint"])
        self.assertEqual(one["identity"]["company_event_id"], "CEV-1")

    def test_missing_identity_and_invalid_http_status_are_rejected(self):
        with self.assertRaisesRegex(OutcomeFactsError, "source_revision"):
            classify_outcome(facts(source_revision=""))
        with self.assertRaisesRegex(OutcomeFactsError, "http_status"):
            classify_outcome(facts(failure={"category": "timeout", "http_status": 999}))

    def test_release_retry_outcome_cannot_use_release_id_without_full_binding_digest(self):
        with self.assertRaisesRegex(OutcomeFactsError, "retry outcome identity requires"):
            classify_outcome(facts(
                failed_request_id="REQ-failed", release_version="REL-1",
                failure={"category": "timeout"},
            ))
        complete = classify_outcome(facts(
            failed_request_id="REQ-failed", release_version="REL-1",
            release_binding_sha256="a" * 64, failure={"category": "timeout"},
        ))
        self.assertEqual(complete["identity"]["release_binding_sha256"], "a" * 64)

    def test_identity_and_classification_facts_are_strictly_bounded_text(self):
        with self.assertRaisesRegex(OutcomeFactsError, "company_id must be text"):
            classify_outcome(facts(company_id={"private": "body"}, failure={"category": "adapter_regression"}))
        with self.assertRaisesRegex(OutcomeFactsError, "company_id exceeds"):
            classify_outcome(facts(company_id="C" * 257, failure={"category": "adapter_regression"}))
        with self.assertRaisesRegex(OutcomeFactsError, "failure category must be text"):
            classify_outcome(facts(failure={"category": {"private": "body"}}))
        with self.assertRaisesRegex(OutcomeFactsError, "capability must be text"):
            classify_outcome(facts(capability=["qualified"], failure={"category": "adapter_regression"}))


class DurableOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = SQLiteRepository(Path(self.temp.name) / "jobs.sqlite3", "test-sheet", initialize=True)
        self.addCleanup(self.repo.close)

    def test_classified_outcome_is_idempotent_and_reviewable_without_dispatch(self):
        source_facts = facts(failure={"category": "adapter_regression"})
        outcome = classify_outcome(source_facts)
        first = self.repo.record_scrape_outcome(source_facts)
        self.assertTrue(first["recorded"])
        self.assertFalse(self.repo.record_scrape_outcome(source_facts)["recorded"])
        self.assertEqual(self.repo.scrape_outcomes(company_id="COMP-1"), [first["outcome"]])
        self.assertEqual(self.repo.pending_company_events("intake"), [])

    def test_stale_outcome_is_durable_but_reserved_repair_consumer_never_receives_it(self):
        stale = facts(source_current=False, source_revision='rev-frozen',
                      current_source_revision='rev-now',
                      failure={'category': 'adapter_regression'})
        saved = self.repo.record_scrape_outcome(stale)['outcome']
        self.assertEqual(saved['outcome'], STALE_OR_PAUSED)
        self.assertEqual(saved['identity']['source_revision'], 'rev-frozen')
        self.assertEqual(saved['comparison']['current_source_revision'], 'rev-now')
        self.assertEqual(self.repo.scrape_outcomes(company_id='COMP-1'), [saved])
        self.assertEqual(self.repo.pending_scrape_outcomes('repair-coordinator'), [])
        self.assertEqual(self.repo.pending_scrape_outcomes('audit'), [saved])
        with self.assertRaisesRegex(RepositoryError, 'may not acknowledge'):
            self.repo.acknowledge_scrape_outcome(saved['outcome_id'], 'repair-coordinator')
        # Reopen proves that withholding is a durable consumer policy, not an
        # in-memory suppression that could replay after a restart.
        path = self.repo.path
        self.repo.close()
        self.repo = SQLiteRepository(path, 'test-sheet', initialize=True)
        self.addCleanup(self.repo.close)
        self.assertEqual(self.repo.pending_scrape_outcomes('repair-coordinator'), [])
        self.assertEqual(self.repo.pending_scrape_outcomes('audit'), [saved])

    def test_outcome_limit_rejects_boolean_values(self):
        for reader in (self.repo.scrape_outcomes,
                       lambda **kwargs: self.repo.pending_scrape_outcomes('audit', **kwargs)):
            with self.subTest(reader=reader):
                with self.assertRaisesRegex(RepositoryError, 'limit'):
                    reader(limit=True)

    def test_qualified_outcome_retains_its_immutable_repair_category(self):
        saved = self.repo.record_scrape_outcome(facts(failure={"category": "adapter_regression"}))['outcome']
        self.assertEqual(saved['repair_category'], 'adapter_regression')
        self.assertEqual(self.repo.scrape_outcomes(company_id='COMP-1')[0]['repair_category'], 'adapter_regression')

    def test_caller_cannot_forge_an_action_or_store_raw_private_identity(self):
        source_facts = facts(failure={"category": "timeout", "http_status": 503})
        source_facts.update({"outcome_id": "OUT-forged", "outcome": "FORGED",
                             "action": "dispatch-everything",
                             "identity": {"raw_private": "X" * 10000}})
        stored = self.repo.record_scrape_outcome(source_facts)["outcome"]
        self.assertNotEqual(stored["outcome_id"], "OUT-forged")
        self.assertEqual(stored["action"], "retry_with_bounded_backoff")
        self.assertNotIn("raw_private", stored["identity"])

    def test_generic_writer_rejects_reserved_mapping_category_and_identity(self):
        forged = facts(failure={'category': 'same_provider_source_mapping'}, capability='sealed',
                       capability_id='rippling-shared-v1', capability_digest='a' * 64,
                       mapping_digest='b' * 64, configuration_digest='c' * 64)
        with self.assertRaisesRegex(RepositoryError, 'sealed'):
            self.repo.record_scrape_outcome(forged)
        self.assertEqual([], self.repo.scrape_outcomes())

    def test_sealed_writer_accepts_only_ids_and_rejects_forged_caller_objects(self):
        state = State(Path(self.temp.name) / 'state.db')
        state.save_cycle({'id': 'CYC-owned', 'companies': {'COMP-0066': {
            'stage': 'failed', 'inventory_status': 'failed',
            'outcome_source_revision': 'r' * 64}}})
        state.close()
        company = {'Company ID': 'COMP-0066', 'Company Status': 'Active',
                   'Official Careers URL': 'https://example.test/jobs',
                   'ATS / Source': 'Rippling'}
        self.repo.matches = lambda tab, identity: [(1, company)] if tab == 'Companies' else []
        forged_cycle = {'id': 'CYC-owned', 'companies': {'COMP-0066': {
            'source_configuration_defect': {'forged': True}}}}
        with self.assertRaises(TypeError):
            self.repo.record_sealed_source_configuration_outcome(
                forged_cycle, company, forged_cycle['companies']['COMP-0066'],
                storage_confirmed=True)
        with self.assertRaisesRegex(RepositoryError, 'unavailable'):
            self.repo.record_sealed_source_configuration_outcome(
                'CYC-owned', 'COMP-0066', storage_confirmed=True)
        self.assertEqual([], self.repo.scrape_outcomes())

    def test_sealed_writer_rejects_non_boolean_storage_claims_before_any_write(self):
        for forged in ('forged', 1, None):
            with self.subTest(forged=forged), self.assertRaisesRegex(
                    RepositoryError, 'must be explicit'):
                self.repo.record_sealed_source_configuration_outcome(
                    'CYC-forged', 'COMP-0066', storage_confirmed=forged)
        self.assertEqual([], self.repo.scrape_outcomes())

    def test_terminal_unknown_cannot_be_upgraded_by_later_sealed_restart(self):
        unknown = facts(request_id='CYC-unknown', company_id='COMP-unknown', source_revision='rev-unknown',
                        cycle_id='CYC-unknown', capability='unknown',
                        failure={'category': 'unknown'})
        first = self.repo.record_scrape_outcome(unknown)
        self.repo.close()
        state = State(Path(self.temp.name) / 'state.db')
        state.save_cycle({'id': 'CYC-unknown', 'companies': {'COMP-unknown': {
            'stage': 'failed', 'inventory_status': 'failed',
            'outcome_source_revision': 'rev-unknown'}}})
        state.close()
        self.repo = SQLiteRepository(
            Path(self.temp.name) / 'jobs.sqlite3', 'test-sheet', initialize=True)
        self.addCleanup(self.repo.close)
        company = {'Company ID': 'COMP-unknown', 'Company Status': 'Active',
                   'Official Careers URL': 'https://jobs.example.test', 'ATS / Source': 'Greenhouse'}
        self.repo.matches = lambda tab, identity: [(1, company)] if tab == 'Companies' else []
        sealed = {'capability': 'sealed', 'failure': {'category': 'same_provider_source_mapping'},
                  'capability_id': 'rippling-shared-v1', 'capability_digest': 'a' * 64,
                  'mapping_digest': 'b' * 64, 'configuration_digest': 'c' * 64}
        with patch('job_search_helper.scrape_outcome_producer._sealed_mapping_evidence', return_value=sealed):
            result = self.repo.record_sealed_source_configuration_outcome(
                'CYC-unknown', 'COMP-unknown', storage_confirmed=True)
        self.assertFalse(result['recorded'])
        self.assertEqual(first['outcome_id'], result['outcome_id'])
        self.assertEqual(1, len(self.repo.scrape_outcomes(company_id='COMP-unknown')))

    def test_sealed_mapping_serializes_identity_fields_at_top_level(self):
        sealed = facts(capability='sealed', failure={'category': 'same_provider_source_mapping'},
                       capability_id='rippling-shared-v1', capability_digest='a' * 64,
                       mapping_digest='b' * 64, configuration_digest='c' * 64)
        # Private-only helper models the repository-owned sealed writer after
        # it has rebuilt facts; public generic entry rejects this input.
        saved = self.repo._record_scrape_outcome(sealed)['outcome']
        for key in ('capability_id', 'capability_digest', 'mapping_digest', 'configuration_digest'):
            self.assertEqual(sealed[key], saved[key])
            self.assertNotIn(key, saved['identity'])
        self.assertEqual(
            {'outcome_id', 'outcome', 'action', 'identity', 'failure_fingerprint',
             'repair_category', 'capability_id', 'capability_digest', 'mapping_digest',
             'configuration_digest'}, set(saved))

    def test_readonly_legacy_database_without_outcome_table_reads_empty(self):
        self.repo.db.execute("DROP TABLE scrape_outcomes")
        with self.repo.transaction():
            self.repo.set_meta("ready", "yes")
        self.repo.close()
        self.repo = SQLiteRepository(Path(self.temp.name) / "jobs.sqlite3", "test-sheet", readonly=True)
        self.addCleanup(self.repo.close)
        self.assertEqual(self.repo.scrape_outcomes(), [])


if __name__ == "__main__":
    unittest.main()
