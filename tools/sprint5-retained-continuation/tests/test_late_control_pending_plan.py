import tempfile
import unittest

from job_search_helper.exact_control_before_prefix_recovery import preview_control_before_prefix_source_transition
from job_search_helper.exact_cycle_planner import _digest
from job_search_helper.late_control_pending_plan import build_late_control_pending_plan
from test_control_before_prefix_source_transition import SourceTransitionPreviewTests, CYCLE, COMPANY, URL


class LateControlPendingPlanTests(unittest.TestCase):
    def test_seals_only_suffix_with_explicit_mapping_and_hold(self):
        with tempfile.TemporaryDirectory() as root:
            repo, posting, legacy, controls, _key, _source = SourceTransitionPreviewTests().fixture(root)
            self.addCleanup(repo.close)
            payload = {"inventory_status": "complete", "jobs": [posting], "requested_url": URL}
            preview = preview_control_before_prefix_source_transition(
                repo, cycle_id=CYCLE, company_id=COMPANY, payload=payload,
                legacy_plan=legacy, cursor=1, controls=controls)
            auth = {"version": "late-control-pending-disposition-v1",
                    "preview_binding_digest": _digest(preview["plan"]["binding"]),
                    "observed_prefix_indices": [0], "pending_original_indices": [1, 2],
                    "held_original_indices": [3],
                    "remote_prefix_observation_digest": "a" * 64,
                    "pending_write_baseline_digest": "b" * 64}
            plan, report = build_late_control_pending_plan(
                repo, cycle_id=CYCLE, company_id=COMPANY, payload=payload,
                legacy_plan=legacy, cursor=1, accepted_preview=preview, authorization=auth, controls=controls)
            self.assertEqual(len(plan["local_operations"]), 2)
            self.assertEqual([item["original_index"] for item in plan["late_control_pending_plan"]["original_to_delta"]], [1, 2])
            self.assertFalse(plan["selected_legacy_control_before_prefix_recovery"]["remote_release_authorized"])
            self.assertFalse(report["whole_suffix_terminal"])

    def test_rejects_overlapping_or_incomplete_disposition(self):
        with tempfile.TemporaryDirectory() as root:
            repo, posting, legacy, controls, _key, _source = SourceTransitionPreviewTests().fixture(root)
            self.addCleanup(repo.close)
            payload = {"inventory_status": "complete", "jobs": [posting], "requested_url": URL}
            preview = preview_control_before_prefix_source_transition(repo, cycle_id=CYCLE, company_id=COMPANY, payload=payload, legacy_plan=legacy, cursor=1, controls=controls)
            auth = {"version": "late-control-pending-disposition-v1", "preview_binding_digest": _digest(preview["plan"]["binding"]),
                    "observed_prefix_indices": [0, 1], "pending_original_indices": [1, 2],
                    "held_original_indices": [3],
                    "remote_prefix_observation_digest": "a" * 64, "pending_write_baseline_digest": "b" * 64}
            with self.assertRaisesRegex(ValueError, "disposition_invalid"):
                build_late_control_pending_plan(repo, cycle_id=CYCLE, company_id=COMPANY, payload=payload, legacy_plan=legacy, cursor=1, accepted_preview=preview, authorization=auth, controls=controls)
