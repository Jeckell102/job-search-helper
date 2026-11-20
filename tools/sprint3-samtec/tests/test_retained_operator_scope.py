import copy
from contextlib import closing
import json
import sqlite3
import unittest

from job_search_helper.retained_operator_scope import historical_work_evidence, queued_membership_evidence


class RetainedOperatorScopeTest(unittest.TestCase):
    def setUp(self):
        older = [{"id": f"CYC-OLD-{n}", "status": "In Progress", "companies": {}}
                 for n in range(18)]
        self.rows = [{
            "id": "CYC-ACTIVE", "status": "In Progress", "supersedes": [row["id"] for row in older],
            "companies": {"COMP-0739": {"company": "Samtec", "stage": "queued"}},
        }, *older]

    def seal(self, rows):
        return queued_membership_evidence(rows, cycle_id="CYC-ACTIVE",
                                          company_id="COMP-0739", company_name="Samtec")

    def test_seal_includes_superseded_rows_and_is_order_independent(self):
        evidence = self.seal(self.rows)
        self.assertEqual(len(evidence["unfinished_cycle_ids"]), 19)
        self.assertEqual(self.seal(reversed(self.rows)), evidence)
        changed = copy.deepcopy(self.rows)
        changed[-1]["companies"]["COMP-0001"] = {"company": "Other", "stage": "queued"}
        self.assertNotEqual(self.seal(changed)["cycles_sha256"], evidence["cycles_sha256"])

    def test_extra_blocker_and_duplicate_cycle_hold(self):
        with self.assertRaisesRegex(ValueError, "effective_blocker_changed"):
            self.seal(self.rows + [{"id": "CYC-NEW", "status": "In Progress", "companies": {}}])
        with self.assertRaisesRegex(ValueError, "cycle_identity_invalid"):
            self.seal(self.rows + [self.rows[-1]])

    def test_unknown_membership_shape_or_other_owner_holds(self):
        changed = copy.deepcopy(self.rows)
        changed[0]["companies"]["COMP-0739"]["attempt_id"] = "existing-attempt"
        with self.assertRaisesRegex(ValueError, "unstarted_membership_unverified"):
            self.seal(changed)
        changed = copy.deepcopy(self.rows)
        changed[-1]["companies"]["COMP-0739"] = {"company": "Samtec", "stage": "queued"}
        with self.assertRaisesRegex(ValueError, "unstarted_membership_unverified"):
            self.seal(changed)

    def test_neither_a_started_nor_an_absent_member_passes(self):
        for entry in ({"company": "Samtec", "stage": "inventory"}, None):
            changed = copy.deepcopy(self.rows)
            if entry is None:
                del changed[0]["companies"]["COMP-0739"]
            else:
                changed[0]["companies"]["COMP-0739"] = entry
            with self.subTest(entry=entry), self.assertRaisesRegex(ValueError, "unstarted_membership_unverified"):
                self.seal(changed)

    def historical_databases(self):
        inventory = self.enterContext(closing(sqlite3.connect(":memory:")))
        jobs = self.enterContext(closing(sqlite3.connect(":memory:")))
        inventory.executescript("""
            CREATE TABLE inventories (cycle, company, payload);
            CREATE TABLE sync_plans (cycle, company, payload);
            CREATE TABLE publication_receipts (receipt_id, binding);
            INSERT INTO inventories VALUES ('CYC-ACTIVE', 'COMP-SARONIC', 'original');
        """)
        jobs.executescript("""
            CREATE TABLE exact_local_applications (cycle, company, apply_id);
            CREATE TABLE exact_local_apply_chunks (apply_id, content);
            CREATE TABLE exact_local_acknowledgements (apply_id, content);
        """)
        return inventory, jobs

    def test_historical_seal_checks_superseded_cycles_and_other_members(self):
        inventory, jobs = self.historical_databases()
        scope = self.seal(self.rows)
        original = historical_work_evidence(inventory, jobs, scope)
        inventory.execute("UPDATE inventories SET payload='changed'")
        self.assertNotEqual(historical_work_evidence(inventory, jobs, scope), original)
        inventory.execute("INSERT INTO sync_plans VALUES ('CYC-OLD-3', 'COMP-0739', 'prior')")
        with self.assertRaisesRegex(ValueError, "prior_company_work"):
            historical_work_evidence(inventory, jobs, scope)

    def test_selected_receipt_without_cycle_identity_holds(self):
        inventory, jobs = self.historical_databases()
        inventory.execute("INSERT INTO publication_receipts VALUES (?,?)", ("prior", json.dumps(
            {"company_id": "COMP-0739", "request_id": "earlier"})))
        with self.assertRaisesRegex(ValueError, "prior_company_receipt"):
            historical_work_evidence(inventory, jobs, self.seal(self.rows))

    def test_unclassified_historical_table_fails_closed(self):
        inventory, jobs = self.historical_databases()
        inventory.execute("CREATE TABLE unexpected (cycle, payload)")
        with self.assertRaisesRegex(ValueError, "historical_table_unclassified"):
            historical_work_evidence(inventory, jobs, self.seal(self.rows))

    def test_historical_application_acknowledgement_is_sealed(self):
        inventory, jobs = self.historical_databases()
        scope = self.seal(self.rows)
        jobs.execute("INSERT INTO exact_local_applications VALUES ('CYC-ACTIVE','COMP-SARONIC','old')")
        original = historical_work_evidence(inventory, jobs, scope)
        jobs.execute("INSERT INTO exact_local_acknowledgements VALUES ('old','late')")
        self.assertNotEqual(historical_work_evidence(inventory, jobs, scope), original)

    def test_publication_table_creation_keeps_only_private_cycle_outside_history(self):
        inventory, jobs = self.historical_databases()
        scope = self.seal(self.rows)
        original = historical_work_evidence(inventory, jobs, scope)
        jobs.execute("CREATE TABLE retained_publications (cycle, company, payload)")
        jobs.execute("INSERT INTO retained_publications VALUES ('PRIVATE','COMP-0739','new')")
        self.assertEqual(historical_work_evidence(inventory, jobs, scope), original)
        jobs.execute("INSERT INTO retained_publications VALUES ('CYC-ACTIVE','COMP-SARONIC','changed')")
        self.assertNotEqual(historical_work_evidence(inventory, jobs, scope), original)
        jobs.execute("INSERT INTO retained_publications VALUES ('CYC-ACTIVE','COMP-0739','prior')")
        with self.assertRaisesRegex(ValueError, "prior_company_work"):
            historical_work_evidence(inventory, jobs, scope)
