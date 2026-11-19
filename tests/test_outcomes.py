import unittest

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
)


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
    def test_stale_precedes_storage_and_failure_actions(self):
        result = classify_outcome(facts(
            source_current=False, storage_status="sync_failed",
            failure={"category": "adapter_regression"},
        ))
        self.assertEqual(result["outcome"], STALE_OR_PAUSED)
        self.assertEqual(result["action"], "stop_stale_work")

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

    def test_identity_and_classification_facts_are_strictly_bounded_text(self):
        with self.assertRaisesRegex(OutcomeFactsError, "company_id must be text"):
            classify_outcome(facts(company_id={"private": "body"}, failure={"category": "adapter_regression"}))
        with self.assertRaisesRegex(OutcomeFactsError, "company_id exceeds"):
            classify_outcome(facts(company_id="C" * 257, failure={"category": "adapter_regression"}))
        with self.assertRaisesRegex(OutcomeFactsError, "failure category must be text"):
            classify_outcome(facts(failure={"category": {"private": "body"}}))
        with self.assertRaisesRegex(OutcomeFactsError, "capability must be text"):
            classify_outcome(facts(capability=["qualified"], failure={"category": "adapter_regression"}))


if __name__ == "__main__":
    unittest.main()
