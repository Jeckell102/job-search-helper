from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import csv
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper import local_cli as cli, database as database_module
from job_search_helper import assessment_service as assessment_module
from job_search_helper.assessment_service import AssessmentService
from job_search_helper.ats import Inventory
from job_search_helper.catalog_export import CatalogExporter
from job_search_helper.catalog_queries import CatalogQueries
from job_search_helper.database import Database, DatabaseError
from job_search_helper.local_screening import annual_base_max, evaluate
from job_search_helper.models import JobPosting, utc_now
from job_search_helper.policy import load_policy, parse_policy
from job_search_helper.repositories import ApplicationRepository, CatalogRepository
from job_search_helper.scan_service import ScanService


SALARY = {"minimum": 100000, "currency": "USD", "period": "annual"}


class PolicyTests(unittest.TestCase):
    def test_neutral_policy_has_no_personal_defaults(self):
        policy = parse_policy({})
        self.assertFalse(policy.enabled)
        self.assertEqual(policy.rules, {"titles": {"exclude": [], "prefer": []}, "salary": {},
                                       "locations": {"work_arrangements": []}})
        self.assertEqual(evaluate({"title": "Intern", "compensation_text": "USD 40000 annual base salary"}, policy)["result"], "not_evaluated")

    def test_equivalent_profiles_have_stable_fingerprints(self):
        first = parse_policy({"schema_version": 1, "titles": {"exclude": ["Intern", "Field-Service", "Intern"]},
                              "salary": SALARY, "locations": {"work_arrangements": ["remote", "hybrid"]}})
        second = parse_policy({"titles": {"exclude": ["field service", "intern"]},
                               "salary": dict(SALARY, minimum=100000.0), "locations": {"work_arrangements": ["hybrid", "remote"]}})
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertNotEqual(first.fingerprint, parse_policy({"salary": dict(SALARY, minimum=100001)}).fingerprint)

    def test_invalid_profiles_fail_closed(self):
        invalid = [{"travel": {}}, {"schema_version": True}, {"schema_version": 2}, {"titles": []},
                   {"titles": {"excludes": []}}, {"titles": {"exclude": "Intern"}},
                   {"titles": {"exclude": [""]}}, {"titles": {"prefer": ["regex:.*"]}},
                   {"titles": {"exclude": ["+++"]}}, {"titles": {"exclude": ["x" * 201]}},
                   {"titles": {"prefer": ["x"] * 201}}, {"salary": {"minimum": 100}},
                   {"salary": dict(SALARY, minimum=True)}, {"salary": dict(SALARY, minimum=-1)},
                   {"salary": dict(SALARY, minimum=float("nan"))}, {"salary": dict(SALARY, minimum=float("inf"))},
                   {"salary": dict(SALARY, minimum=10 ** 1000)}, {"salary": dict(SALARY, currency="EUR")},
                   {"salary": dict(SALARY, period="hourly")}, {"locations": {"work_arrangements": "remote"}},
                   {"locations": {"work_arrangements": ["maybe remote"]}}, {"locations": {"work_arrangements": [{}]}}]
        for document in invalid:
            with self.subTest(document=document), self.assertRaises(ValueError):
                parse_policy(document)

    def test_loading_is_explicit_workspace_relative_and_never_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "profile.toml").write_text('[titles]\nexclude = ["Intern"]\n')
            (root / "config").mkdir()
            (root / "config/profile.toml").write_text("malformed !!")
            (root / "title-blacklist.txt").write_text("regex:[invalid")
            (root / "title-review-list.txt").write_text("regex:[invalid")
            with patch.dict(os.environ, {"JSH_PROFILE": "missing.toml"}), \
                    patch.dict(sys.modules, {"job_search_helper.efficiency": None,
                                             "job_search_helper.core": None}):
                self.assertFalse(load_policy(root).enabled)
                self.assertTrue(load_policy(root, "profile.toml").enabled)
                with self.assertRaisesRegex(ValueError, "Cannot read profile"):
                    load_policy(root, "missing.toml")
                with self.assertRaisesRegex(ValueError, "Cannot read profile"):
                    load_policy(root, "config/profile.toml")
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(cli.main(["local", "policy", "--workspace", str(root), "--json"]), 0)
                self.assertFalse(json.loads(output.getvalue())["enabled"])
                self.assertFalse((root / "data").exists())

    def test_profile_size_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.toml"
            path.write_bytes(b"#" * (1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "exceeds"):
                load_policy(Path(directory), path)


class LocalEvaluatorTests(unittest.TestCase):
    def test_title_exclusion_outranks_preference_without_substring_matches(self):
        policy = parse_policy({"titles": {"exclude": ["Intern"], "prefer": ["Engineer"]}})
        for title, expected in (("Engineering Intern", "excluded"), ("Engineer Intern", "excluded"),
                                ("Internal Engineer", "no_exclusion"), ("Analyst", "needs_review"), ("", "needs_review"),
                                ("???", "needs_review")):
            with self.subTest(title=title):
                self.assertEqual(evaluate({"title": title}, policy)["result"], expected)

    def test_word_phrases_support_punctuation_and_unicode(self):
        policy = parse_policy({"titles": {"exclude": ["FIELD SERVICE"]}})
        result = evaluate({"title": "Ｆｉｅｌｄ-Service Technician"}, policy)
        self.assertEqual(result["result"], "excluded")
        self.assertEqual(result["evidence"][0]["value"], "Ｆｉｅｌｄ-Service Technician")

    def test_explicit_salary_forms_use_shared_amount_parser(self):
        cases = {"USD 80,000 - 95,000 annual base salary": 95000,
                 "Annual base salary: USD 80,000 to USD 100,000": 100000,
                 "Base pay: USD 90k - 120k per year": 120000,
                 "USD $120000 annual base pay": 120000,
                 "Annual base pay USD 90000": 90000,
                 "USD 90,000.00 - 120,000.00 annual base salary": 120000}
        for text, maximum in cases.items():
            with self.subTest(text=text):
                self.assertEqual(annual_base_max(text), maximum)

    def test_uncertain_pay_never_becomes_a_below_floor_exclusion(self):
        cases = ["", "$80,000 annual base salary", "CAD 80,000 annual base salary", "USD 80000 base salary",
                 "USD 50 hourly base pay", "USD 80000 annual OTE", "USD 80000 salary", "USD 80000 annual base salary plus bonus",
                 "USD 80000 annual base salary, EUR 90000 in Europe", "Starting from USD 80000 annual base pay",
                 "USD 80,000+ annual base salary", "USD 80000 annual base pay or more", "USD 95000 - 80000 annual base salary",
                 "USD 800 annual base salary", "USD 80000 annual base salary (historically)", "Not USD 80000 annual base salary",
                 "USD 80,00 annual base salary", "USD 80000 monthly base salary", "Product price USD 80000; annual base salary unknown",
                 "USD 10000000 annual base salary", "USD 10000k annual base salary"]
        policy = parse_policy({"salary": SALARY})
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(annual_base_max(text))
                self.assertEqual(evaluate({"compensation_text": text}, policy)["result"], "needs_review")

    def test_salary_maximum_boundary_is_not_an_offer_or_overall_fit(self):
        policy = parse_policy({"salary": SALARY})
        low = evaluate({"compensation_text": "USD 80000 - 99999 annual base salary"}, policy)
        boundary = evaluate({"compensation_text": "USD 80000 - 100000 annual base salary"}, policy)
        self.assertEqual(low["result"], "excluded")
        self.assertEqual(boundary["result"], "no_exclusion")
        self.assertIn("not a guaranteed offer", boundary["reason"])

    def test_work_arrangement_does_not_infer_remote_from_location_or_description(self):
        policy = parse_policy({"locations": {"work_arrangements": ["remote"]}})
        for arrangement, expected in (("Remote", "no_exclusion"), ("on-site", "excluded"), ("Hybrid", "excluded"),
                                      ("Remote possible", "needs_review"), ("", "needs_review")):
            with self.subTest(arrangement=arrangement):
                result = evaluate({"work_arrangement": arrangement, "location": "Remote", "description": "You must accept this job"}, policy)
                self.assertEqual(result["result"], expected)

    def test_missing_evidence_is_recorded_even_when_another_rule_excludes(self):
        policy = parse_policy({"salary": SALARY, "titles": {"exclude": ["Intern"]}})
        result = evaluate({"title": "Intern"}, policy)
        self.assertEqual(result["result"], "excluded")
        self.assertEqual({item["outcome"] for item in result["evidence"]}, {"fail", "unknown"})


class LocalAssessmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "data/job-search-helper.sqlite3"
        self.database = Database.initialize(self.path)
        self.addCleanup(self.database.close)
        self.connection = self.database.connection
        self.catalog = CatalogRepository(self.database)
        self.company = self.catalog.add_company("Fixture company")
        self.source = self.catalog.add_source(self.company, "lever", "fixture", "https://jobs.lever.co/fixture")
        self.posting = JobPosting(posting_id="001", title="Engineer Intern", work_arrangement="remote",
                                  compensation="USD 80000 - 95000 annual base salary", description="Evidence\n" * 10000,
                                  url="https://example.com/jobs/001")
        self.job = self.catalog.create_job(self.company, self.posting, source_id=self.source)
        self.application = ApplicationRepository(self.database).add(self.job, status="applied", date_applied="2026-09-25", notes="My decision")
        self.service = AssessmentService(self.database)
        self.policy = parse_policy({"titles": {"exclude": ["Intern"]}})

    def preserved(self):
        tables = ("companies", "jobs", "job_versions", "applications", "application_events", "job_observations", "job_scope_state", "scan_cycles")
        return {table: [tuple(row) for row in self.connection.execute("SELECT * FROM " + table)] for table in tables}

    def command(self, *args, as_json=True):
        output, errors = io.StringIO(), io.StringIO()
        arguments = [*args, "--workspace", str(self.root)] + (["--json"] if as_json else [])
        with redirect_stdout(output), redirect_stderr(errors), patch.dict(os.environ, {}, clear=True), \
                patch.dict("sys.modules", {"job_search_helper.cli": None, "job_search_helper.repository": None}):
            code = cli.main(arguments)
        return code, json.loads(output.getvalue()) if as_json else output.getvalue(), errors.getvalue()

    def test_preview_is_read_only_and_complete(self):
        before = self.path.read_bytes()
        with Database(self.path, readonly=True) as reader:
            result = AssessmentService(reader).screen(self.policy, all_jobs=True)
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse(result["applied"])
        self.assertEqual(result["counts"], {"new": 1, "unchanged": 0, "skipped": 0})
        self.assertEqual(result["items"][0]["result"], "excluded")
        self.assertIsNone(result["items"][0]["assessment_id"])

    def test_no_policy_does_not_write_or_clear_existing_assessments(self):
        self.service.screen(self.policy, all_jobs=True, apply=True)
        before = self.path.read_bytes()
        result = self.service.screen(parse_policy({}), all_jobs=True, apply=True)
        self.assertEqual(result["counts"]["skipped"], 1)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(self.service.history()["total"], 1)

    def test_saved_screening_preserves_jobs_source_evidence_and_application_decisions(self):
        before = self.preserved()
        result = self.service.screen(self.policy, all_jobs=True, apply=True)
        self.assertEqual(before, self.preserved())
        item = self.service.show(result["items"][0]["assessment_id"])
        self.assertEqual(item["policy"], self.policy.rules)
        self.assertEqual(item["evidence"][0]["value"], self.posting.title)
        self.assertEqual(item["actor"], "local-screen")
        self.assertTrue(item["evaluated_at"].endswith("Z"))
        self.assertFalse(item["stale"])

    def test_retry_does_not_duplicate_or_touch_database(self):
        first = self.service.screen(self.policy, job_ids=[self.job], apply=True)
        before = self.path.read_bytes()
        second = self.service.screen(self.policy, job_ids=[self.job, self.job], apply=True)
        self.assertEqual(second["counts"]["unchanged"], 1)
        self.assertEqual(first["items"][0]["assessment_id"], second["items"][0]["assessment_id"])
        self.assertEqual(before, self.path.read_bytes())

    def test_profile_change_and_switch_back_append_linked_history(self):
        before = self.preserved()
        other = parse_policy({"titles": {"prefer": ["Engineer"]}})
        for policy in (self.policy, other, self.policy):
            self.service.screen(policy, all_jobs=True, apply=True)
        items = self.service.history(job_id=self.job)["items"]
        self.assertEqual(len(items), 3)
        self.assertEqual([row["result"] for row in items], ["excluded", "no_exclusion", "excluded"])
        self.assertEqual(items[0]["supersedes_assessment_id"], items[1]["assessment_id"])
        self.assertEqual(items[1]["supersedes_assessment_id"], items[2]["assessment_id"])
        self.assertIsNone(items[2]["supersedes_assessment_id"])
        self.assertTrue(self.service.show(items[0]["assessment_id"])["current"])
        self.assertFalse(self.service.show(items[1]["assessment_id"])["current"])
        page = self.service.history(job_id=self.job, limit=1, offset=1)
        self.assertEqual(page["total"], 3)
        self.assertEqual(page["items"][0]["assessment_id"], items[1]["assessment_id"])
        self.assertEqual(before, self.preserved())
        self.assertEqual(self.connection.execute("SELECT count(*) FROM policy_profiles").fetchone()[0], 2)

    def test_changed_evidence_is_stale_until_explicit_reassessment(self):
        first = self.service.screen(self.policy, all_jobs=True, apply=True)["items"][0]["assessment_id"]
        version = self.catalog.store_version(self.job, replace(self.posting, title="Engineer"), observed_at=utc_now())
        self.connection.execute("UPDATE jobs SET current_version_id=? WHERE job_id=?", (version, self.job))
        query = CatalogQueries(self.database).job(self.job)
        self.assertEqual(query["screening_status"], "Needs Reassessment")
        self.assertTrue(self.service.show(first)["stale"])
        self.assertEqual(self.service.show(first)["title"], "Engineer Intern")
        self.service.screen(self.policy, all_jobs=True, apply=True)
        self.assertEqual(CatalogQueries(self.database).job(self.job)["screening_status"], "No Exclusion Found")
        self.assertEqual(self.service.history()["total"], 2)

    def test_evaluator_version_change_invalidates_projection_and_creates_new_assessment(self):
        self.service.screen(self.policy, all_jobs=True, apply=True)
        with patch.object(assessment_module, "EVALUATOR_VERSION", "future-test"):
            self.assertEqual(CatalogQueries(self.database).job(self.job)["screening_status"], "Needs Reassessment")
            result = self.service.screen(self.policy, all_jobs=True, apply=True)
            self.assertEqual(result["counts"]["new"], 1)
            self.assertFalse(CatalogQueries(self.database).job(self.job)["screening_stale"])

    def test_history_is_immutable_and_cross_job_version_is_rejected(self):
        self.service.screen(self.policy, all_jobs=True, apply=True)
        for table in ("policy_profiles", "assessments"):
            field = "created_at" if table == "policy_profiles" else "reason"
            for sql in (f"UPDATE {table} SET {field}='changed'", f"DELETE FROM {table}"):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    self.connection.execute(sql)
        other = self.catalog.create_job(self.company, replace(self.posting, posting_id="002"), source_id=self.source)
        row = self.service.history()["items"][0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("""INSERT INTO assessments (assessment_id, job_id, version_id, policy_fingerprint,
                evaluator_version, result, reason, evidence_json, actor, evaluated_at) VALUES
                ('bad', ?, ?, ?, 'test', 'excluded', '', '[]', 'test', ?)""",
                (other, row["version_id"], row["policy_fingerprint"], utc_now()))

    def test_failure_mid_batch_rolls_back_profiles_and_assessments(self):
        self.catalog.create_job(self.company, replace(self.posting, posting_id="002"), source_id=self.source)
        before = self.path.read_bytes()
        original = assessment_module.evaluate
        count = 0

        def fail_second(*args):
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError("injected failure")
            return original(*args)

        with patch.object(assessment_module, "evaluate", side_effect=fail_second), self.assertRaises(RuntimeError):
            self.service.screen(self.policy, all_jobs=True, apply=True)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(self.service.history()["total"], 0)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM policy_profiles").fetchone()[0], 0)

    def test_unknown_ids_invalid_selection_and_limits_refuse_without_writes(self):
        before = self.path.read_bytes()
        for parameters in ({}, {"all_jobs": True, "job_ids": [self.job]}, {"job_ids": [self.job, "missing"]}):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                self.service.screen(self.policy, apply=True, **parameters)
        for parameters in ({"limit": 0}, {"limit": 1001}, {"offset": -1}, {"job_id": "missing"}):
            with self.assertRaises(ValueError):
                self.service.history(**parameters)
        with self.assertRaises(ValueError):
            self.service.show("missing")
        self.assertEqual(before, self.path.read_bytes())

    def test_all_includes_closed_jobs_and_missing_version_is_skipped(self):
        self.connection.execute("UPDATE jobs SET lifecycle_status='closed' WHERE job_id=?", (self.job,))
        self.connection.execute("INSERT INTO jobs(job_id,company_id,origin,created_at,updated_at) VALUES ('empty',?,'manual',?,?)",
                                (self.company, utc_now(), utc_now()))
        result = self.service.screen(self.policy, all_jobs=True, apply=True)
        self.assertEqual(result["counts"], {"new": 1, "unchanged": 0, "skipped": 1})
        self.assertEqual(self.service.history()["total"], 1)

    def test_scan_after_exclusion_still_retains_all_jobs_and_evidence(self):
        self.service.screen(self.policy, all_jobs=True, apply=True)
        service = ScanService(self.database)
        cycle = service.start_cycle([self.company])
        attempt = service.begin_attempt(cycle, self.company)
        service.stage_inventory(attempt, Inventory("complete", [
            {"posting_id": "001", "title": "Engineer Intern", "description": "Updated full description"},
            {"posting_id": "002", "title": "Intern", "description": "New full description"}]))
        service.apply_inventory(attempt)
        self.assertEqual(self.database.check()["counts"]["jobs"], 2)
        self.assertEqual(self.catalog.get_job(self.job)["description"], "Updated full description")
        self.assertEqual(CatalogQueries(self.database).job(self.job)["screening_status"], "Needs Reassessment")
        self.assertEqual(ApplicationRepository(self.database).get(self.application)["notes"], "My decision")
        self.assertEqual(self.service.history()["total"], 1)

    def test_csv_uses_latest_screening_but_never_claims_fit_review(self):
        self.service.screen(self.policy, all_jobs=True, apply=True)
        target = self.root / "export"
        CatalogExporter(self.database).export(target, kinds=["jobs"])
        with (target / "Jobs.csv").open(encoding="utf-8-sig", newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(row["Screening Result"], "Excluded by Profile")
        self.assertEqual(row["Review Status"], "Not Evaluated")
        self.assertEqual(row["Fit Level"], "")
        self.assertEqual(row["Application Status"], "applied")
        self.assertIn("Excluded title", row["Screening / Review Reason"])
        version = self.catalog.store_version(self.job, replace(self.posting, title="Engineer"), observed_at=utc_now())
        self.connection.execute("UPDATE jobs SET current_version_id=? WHERE job_id=?", (version, self.job))
        CatalogExporter(self.database).export(self.root / "stale", kinds=["jobs"])
        with (self.root / "stale/Jobs.csv").open(encoding="utf-8-sig", newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(row["Screening Result"], "Needs Reassessment")

    def test_cli_policy_preview_apply_history_and_readable_dates(self):
        (self.root / "profile.toml").write_text('[titles]\nexclude = ["Intern"]\n')
        code, profile, _ = self.command("local", "policy", "--profile", "profile.toml")
        self.assertEqual(code, 0)
        self.assertTrue(profile["enabled"])
        code, neutral, _ = self.command("local", "policy")
        self.assertFalse(neutral["enabled"])
        code, preview, _ = self.command("local", "screen", "--all", "--profile", "profile.toml")
        self.assertEqual(code, 0)
        self.assertFalse(preview["applied"])
        code, saved, _ = self.command("local", "screen", "--job-id", self.job, "--profile", "profile.toml", "--apply")
        self.assertEqual(code, 0)
        identity = saved["items"][0]["assessment_id"]
        code, listed, _ = self.command("local", "assessments", "list", "--job-id", self.job)
        self.assertEqual(listed["total"], 1)
        code, shown, _ = self.command("local", "assessments", "show", identity)
        self.assertEqual(shown["assessment"]["policy"], self.policy.rules)
        code, text, _ = self.command("local", "assessments", "show", identity, as_json=False)
        self.assertIn(" UTC", text)
        self.assertIn("titles.exclude", text)
        self.assertNotIn("\x1b", text)
        code, text, _ = self.command("local", "jobs", "show", self.job, as_json=False)
        self.assertIn("Screening status: Excluded by Profile", text)

    def test_bad_profile_cli_refuses_before_writes(self):
        before = self.path.read_bytes()
        code, error, _ = self.command("local", "screen", "--all", "--profile", "missing.toml", "--apply")
        self.assertNotEqual(code, 0)
        self.assertFalse(error["ok"])
        self.assertEqual(before, self.path.read_bytes())

    def test_second_writer_cannot_change_evidence_during_saved_evaluation(self):
        original = assessment_module.evaluate
        with Database(self.path) as other:
            other.connection.execute("PRAGMA busy_timeout=10")

            def competing(*args):
                with self.assertRaises(sqlite3.OperationalError):
                    other.connection.execute("UPDATE jobs SET current_version_id=NULL WHERE job_id=?", (self.job,))
                return original(*args)

            with patch.object(assessment_module, "evaluate", side_effect=competing):
                self.service.screen(self.policy, all_jobs=True, apply=True)
        self.assertFalse(self.service.show(self.service.history()["items"][0]["assessment_id"])["stale"])

    def test_process_exit_before_commit_leaves_no_assessments(self):
        script = """
import os, sys
from job_search_helper.database import Database
from job_search_helper.assessment_service import AssessmentService
from job_search_helper.policy import parse_policy
with Database(sys.argv[1]) as database, database.transaction():
    AssessmentService(database).screen(parse_policy({'titles': {'exclude': ['Intern']}}), all_jobs=True, apply=True)
    os._exit(0)
"""
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        completed = subprocess.run([sys.executable, "-c", script, str(self.path)], cwd=self.root, env=environment,
                                   capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.service.history()["total"], 0)
        self.assertTrue(self.database.check()["ok"])

    def test_real_schema_two_upgrade_preserves_identity_jobs_and_applications(self):
        path = self.root / "old.sqlite3"
        with patch.object(database_module, "MIGRATIONS", database_module.MIGRATIONS[:2]), \
                patch.object(database_module, "SCHEMA_VERSION", 2):
            with Database.initialize(path) as old:
                repository = CatalogRepository(old)
                company = repository.add_company("Before upgrade")
                job = repository.create_job(company, self.posting)
                app = ApplicationRepository(old).add(job, notes="Keep these notes")
                identity, evidence = old.database_id, repository.get_job(job)
                old.backup(self.root / "before-upgrade.sqlite3")
        with self.assertRaisesRegex(DatabaseError, "upgrade"):
            Database(path)
        with Database.migrate(path) as upgraded:
            self.assertEqual(upgraded.database_id, identity)
            self.assertEqual(CatalogRepository(upgraded).get_job(job), evidence)
            self.assertEqual(ApplicationRepository(upgraded).get(app)["notes"], "Keep these notes")
            self.assertEqual(AssessmentService(upgraded).history()["total"], 0)
            self.assertTrue(upgraded.check()["ok"])


if __name__ == "__main__":
    unittest.main()
