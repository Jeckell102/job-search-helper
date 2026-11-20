from __future__ import annotations

from pathlib import Path
import stat
import tempfile
import unittest

from job_search_helper.exact_cycle_planner import _digest, _exact_plan_digest
from job_search_helper.publication_receipts import record_fingerprints
from job_search_helper.retained_session_store import (
    RESERVED, SYNC_CONFIRMED, SYNC_PENDING, RetainedSessionStore,
)


def plan(operation_count=1):
    local = [{"tab": "Companies", "identity": {"Company ID": "COMP-NEW"},
              "expected": {}, "values": {"Scan State": "Complete"}}]
    projection = [{"tab": "Companies", "identity": {"Company ID": "COMP-NEW"},
                   "expected": {}, "on_insert": {}, "values": {"Scan State": "Complete"},
                   "append_notes": {}, "append_if_missing": False}
                  for _ in range(operation_count)]
    value = {"exact_plan_version": 2, "cycle_id": "CYC-NEW", "company_id": "COMP-NEW",
             "inventory_payload_digest": _digest({"jobs": []}), "publication_profile": "compact-v1",
             "publication_schema": {"Companies": ["Company ID", "Scan State"]},
             "local_operations": local, "remote_projection": projection,
             "final": {"stage": "complete"}, "final_projection": {"stage": "complete"}}
    value["publication_schema_digest"] = _digest(value["publication_schema"])
    value["local_operations_digest"] = _digest(local)
    value["local_expected_records"] = record_fingerprints(local)
    value["local_expected_records_digest"] = _digest(value["local_expected_records"])
    value["remote_projection_digest"] = _digest(projection)
    value["remote_records"] = record_fingerprints(projection)
    value["remote_records_digest"] = _digest(value["remote_records"])
    value["local_finalization_digest"] = _digest({"operations": local, "final": value["final"]})
    value["final_projection_digest"] = _digest(value["final_projection"])
    value["plan_digest"] = _exact_plan_digest(value)
    return value


def admission():
    return {"request_id": "REQ-1", "event_id": "EVT-1", "exception_cycle_id": "CYC-OLD",
            "cycle_id": "CYC-NEW", "company_id": "COMP-NEW", "source_revision": "SRC-1",
            "manifest_digest": "manifest", "start_binding_digest": "binding"}


def exact_scope(sealed_plan):
    operations = sealed_plan["remote_projection"]
    rows = []
    for index, operation in enumerate(operations):
        sent = {header: operation["values"].get(header, "")
                for header in operation["values"]}
        rows.append({"tab": operation["tab"], "row_id": index + 10,
                     "identity": dict(operation["identity"]),
                     "fields": sorted(sent), "sent": sent,
                     "operation": operation})
    return {"operations": operations, "rows": rows,
            "projection_digest": _digest(operations)}


class FakeSynchronizer:
    """Small offline stand-in with SheetsSynchronizer.readback_exact_scope's shape."""
    def __init__(self):
        self.commits = []

    def commit(self, scope):
        self.commits.append(scope["projection_digest"])

    def readback_exact_scope(self, scope, *, receipt_id, intent_id,
                             intent_projection_digest):
        rows = [{"tab": evidence["tab"], "row_id": evidence["row_id"],
                 "identity": dict(evidence["identity"]), "fields": list(evidence["fields"]),
                 "sent": dict(evidence["sent"]), "actual": dict(evidence["sent"])}
                for evidence in scope["rows"]]
        acknowledgement_id = _digest({"receipt_id": receipt_id, "intent_id": intent_id,
                                      "projection_digest": scope["projection_digest"],
                                      "observed": rows})
        return {"receipt_id": receipt_id, "intent_id": intent_id,
                "intent_projection_digest": intent_projection_digest,
                "projection_digest": scope["projection_digest"], "rows": rows,
                "acknowledgement_id": acknowledgement_id}


class RetainedSessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "private" / "retained.sqlite3"

    def store(self):
        return RetainedSessionStore(self.path)

    def test_freeze_is_private_idempotent_and_restart_safe(self):
        with self.store() as store:
            first = store.freeze("reservation", admission=admission(), inventory={"jobs": []}, plan=plan())
            again = store.freeze("reservation", admission=admission(), inventory={"jobs": []}, plan=plan())
        self.assertEqual(RESERVED, first["state"])
        self.assertEqual(first, again)
        self.assertEqual(0o600, stat.S_IMODE(self.path.stat().st_mode))
        with self.store() as reopened:
            self.assertEqual(first, reopened.load("reservation"))
            self.assertFalse(hasattr(reopened, "list"))

    def test_changed_identity_or_frozen_content_is_refused(self):
        with self.store() as store:
            store.freeze("reservation", admission=admission(), inventory={"jobs": []}, plan=plan())
            changed = admission(); changed["source_revision"] = "SRC-2"
            with self.assertRaisesRegex(ValueError, "reservation_changed"):
                store.freeze("reservation", admission=changed, inventory={"jobs": []}, plan=plan())
            changed_inventory_plan = plan()
            changed_inventory_plan["inventory_payload_digest"] = _digest({"jobs": ["new"]})
            changed_inventory_plan["plan_digest"] = _exact_plan_digest(changed_inventory_plan)
            with self.assertRaisesRegex(ValueError, "reservation_changed"):
                store.freeze("reservation", admission=admission(), inventory={"jobs": ["new"]}, plan=changed_inventory_plan)
            mismatched = plan(); mismatched["inventory_payload_digest"] = "forged"
            mismatched["plan_digest"] = _exact_plan_digest(mismatched)
            with self.assertRaisesRegex(ValueError, "inventory_plan_mismatch"):
                store.freeze("other", admission=admission(), inventory={"jobs": []}, plan=mismatched)

    def test_claim_is_pre_dispatch_and_lost_response_is_readback_only_after_restart(self):
        with self.store() as store:
            sealed = plan(); scope = exact_scope(sealed)
            store.freeze("reservation", admission=admission(), inventory={"jobs": []}, plan=sealed)
            pending = store.freeze_remote_intent("reservation", exact_scope=scope)
            self.assertEqual(SYNC_PENDING, pending["state"])
            self.assertEqual(pending, store.freeze_remote_intent("reservation", exact_scope=scope))
            claim = store.claim_chunk("reservation", operation_count=1)
            self.assertTrue(claim["dispatch_allowed"])
            fake = FakeSynchronizer(); fake.commit(claim["exact_scope"])
            retry = store.claim_chunk("reservation", operation_count=1)
            self.assertFalse(retry["dispatch_allowed"])
            self.assertTrue(retry["retry_requires_readback"])
        with self.store() as reopened:
            pending = reopened.load("reservation")
            self.assertEqual("CLAIMED", pending["chunks"][0]["state"])
            chunk_confirmed = reopened.confirm_chunk_readback(
                "reservation", claim_id=claim["claim_id"],
                readback=fake.readback_exact_scope(
                    claim["exact_scope"], receipt_id=pending["receipt_id"],
                    intent_id=pending["intent_id"],
                    intent_projection_digest=claim["exact_scope"]["projection_digest"]))
            self.assertEqual(chunk_confirmed, reopened.confirm_chunk_readback(
                "reservation", claim_id=claim["claim_id"],
                readback=fake.readback_exact_scope(
                    claim["exact_scope"], receipt_id=pending["receipt_id"],
                    intent_id=pending["intent_id"],
                    intent_projection_digest=claim["exact_scope"]["projection_digest"])))
            full = fake.readback_exact_scope(scope, receipt_id=pending["receipt_id"],
                                             intent_id=pending["intent_id"],
                                             intent_projection_digest=scope["projection_digest"])
            confirmed = reopened.confirm_readback("reservation", readback=full)
            self.assertEqual(SYNC_CONFIRMED, confirmed["state"])
            self.assertEqual(confirmed, reopened.confirm_readback("reservation", readback=full))

    def test_refuses_forged_or_incomplete_readback_and_arbitrary_cursor(self):
        with self.store() as store:
            sealed = plan(); scope = exact_scope(sealed)
            store.freeze("reservation", admission=admission(), inventory={"jobs": []}, plan=sealed)
            session = store.freeze_remote_intent("reservation", exact_scope=scope)
            with self.assertRaises(AttributeError):
                store.advance_cursor("reservation", intent_id="forged", remote_cursor=1)
            claim = store.claim_chunk("reservation", operation_count=1)
            fake = FakeSynchronizer()
            forged = fake.readback_exact_scope(claim["exact_scope"], receipt_id=session["receipt_id"],
                                               intent_id=session["intent_id"],
                                               intent_projection_digest=claim["exact_scope"]["projection_digest"])
            forged["receipt_id"] = "forged"
            with self.assertRaisesRegex(ValueError, "readback_binding_changed"):
                store.confirm_chunk_readback("reservation", claim_id=claim["claim_id"], readback=forged)
            changed = {"receipt_id": session["receipt_id"], "intent_id": session["intent_id"],
                       "intent_projection_digest": session["projection_digest"],
                       "projection_digest": session["projection_digest"], "rows": session["projection"],
                       "acknowledgement_id": "fabricated"}
            with self.assertRaisesRegex(ValueError, "readback_changed"):
                store.confirm_chunk_readback("reservation", claim_id=claim["claim_id"], readback=changed)
            with self.assertRaisesRegex(ValueError, "remote_incomplete"):
                store.confirm_readback(
                    "reservation", readback=fake.readback_exact_scope(
                        scope, receipt_id=session["receipt_id"], intent_id=session["intent_id"],
                        intent_projection_digest=scope["projection_digest"]))
            complete = store.confirm_chunk_readback(
                "reservation", claim_id=claim["claim_id"],
                readback=fake.readback_exact_scope(
                    claim["exact_scope"], receipt_id=session["receipt_id"], intent_id=session["intent_id"],
                    intent_projection_digest=claim["exact_scope"]["projection_digest"]))
            self.assertEqual(1, complete["remote_cursor"])

    def test_confirmed_claims_advance_only_contiguously(self):
        with self.store() as store:
            sealed = plan(2); scope = exact_scope(sealed)
            store.freeze("reservation", admission=admission(), inventory={"jobs": []}, plan=sealed)
            session = store.freeze_remote_intent("reservation", exact_scope=scope)
            first = store.claim_chunk("reservation", operation_count=1)
            fake = FakeSynchronizer(); fake.commit(first["exact_scope"])
            store.confirm_chunk_readback(
                "reservation", claim_id=first["claim_id"],
                readback=fake.readback_exact_scope(
                    first["exact_scope"], receipt_id=session["receipt_id"], intent_id=session["intent_id"],
                    intent_projection_digest=first["exact_scope"]["projection_digest"]))
            second = store.claim_chunk("reservation", operation_count=1)
            self.assertEqual(1, second["start_cursor"])
            self.assertNotEqual(first["claim_id"], second["claim_id"])
            self.assertEqual(scope["operations"][1:], second["exact_scope"]["operations"])
