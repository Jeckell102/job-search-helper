"""Pure-function and CLI safety checks: no credentials, internet, or Google writes."""
from __future__ import annotations

import argparse
import base64
from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch
import zlib

from job_search_helper import cli
from job_search_helper import runner
from job_search_helper.ats import Inventory
from job_search_helper.core import (
    POLICY_VERSION, canonicalize_url, changed_fields, excluded_title, job_key,
    material_hash, pack_snapshot, plain_text, reconsiderations,
    unpack_snapshot, validate_decision,
)
from job_search_helper.engine import Engine, State
from job_search_helper.repository import MemoryRepository


POSTING = {
    "title": "Field Solutions Lead", "location": "Remote US",
    "work_arrangement": "Remote", "compensation": "USD 150,000–190,000 annual base",
    "description": "Lead customer discovery, deployments and troubleshooting. No coding or clearance required.",
}


def assessment(**changes):
    value = {
        "job_key": "comp-1:greenhouse:123", "description_hash": material_hash(POSTING),
        "decision": "accept", "fit_level": "Possible",
        "narrative": "Customer discovery matches the approved profile. Reviewed requirements contain no mandatory clearance or code authorship.",
        "reviewer": "Offline test", "policy_version": POLICY_VERSION,
        "mandatory_clearance": False, "code_authoring_required": False,
        "primary_test_automation": False, "base_max_usd": 190000,
    }
    value.update(changes)
    return value


class CoreTests(unittest.TestCase):
    def test_canonical_url_preserves_greenhouse_identity(self):
        first = canonicalize_url("https://EXAMPLE.com/careers?utm_source=x&gh_jid=123&gh_src=z#top")
        second = canonicalize_url("https://example.com/careers?gh_jid=124")
        self.assertEqual(first, "https://example.com/careers?gh_jid=123")
        self.assertNotEqual(first, second)

    def test_unknown_query_identity_is_not_discarded(self):
        self.assertEqual(
            canonicalize_url("https://example.com/job?source=42&jobId=123&utm_campaign=x"),
            "https://example.com/job?jobId=123&source=42",
        )

    def test_url_requires_http_and_no_embedded_credentials(self):
        for value in ("file:///tmp/job", "javascript:alert(1)", "https://user:password@example.com/job", "[https://example.com](https://example.com)"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonicalize_url(value)

    def test_job_keys_include_provider_and_posting_identity(self):
        first = job_key("COMP-1", "Greenhouse", "123", "https://example.com/job")
        self.assertEqual(first, "comp-1:greenhouse:123")
        self.assertNotEqual(first, job_key("COMP-1", "Lever", "123", "https://example.com/job"))
        self.assertNotEqual(first, job_key("COMP-1", "Greenhouse", "124", "https://example.com/job"))

    def test_url_fallback_keys_ignore_only_tracking(self):
        first = job_key("COMP-1", "Greenhouse", "", "https://example.com/?gh_jid=1&utm_source=x")
        self.assertEqual(first, job_key("COMP-1", "Greenhouse", "", "https://example.com/?gh_jid=1"))
        self.assertNotEqual(first, job_key("COMP-1", "Greenhouse", "", "https://example.com/?gh_jid=2"))

    def test_job_requires_stable_company_and_identity(self):
        for args in (("", "Lever", "1", ""), ("COMP-1", "Lever", "", "")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                job_key(*args)

    def test_ambiguous_titles_remain_for_review(self):
        for title in ("Product Marketing Manager", "Field Applications Engineer", "Staff Solutions Engineer",
                      "Manager, Field Engineering", "Mobile Communications Specialist", "Maintenance Operations Lead",
                      "Quality Audit Program Manager", "Medical Device Field Specialist", "Mission Controller",
                      "Systems Engineer", "Technical Support Manager"):
            with self.subTest(title=title):
                self.assertFalse(excluded_title(title))

    def test_keeper_words_do_not_override_clear_exclusions(self):
        for title in ("Payroll Operations Manager", "Legal Counsel, Product", "Software Engineer, Customer Support",
                      "Field Test Automation Engineer", "Talent Acquisition Program Manager", "Graphic Designer",
                      "Senior Staff Engineer, Survivability Materials", "Staff Engineer", "Electrical Engineer",
                      "Mechanical Engineer", "Materials Engineer"):
            with self.subTest(title=title):
                self.assertTrue(excluded_title(title))

    def test_html_normalization_removes_script_style(self):
        self.assertEqual(plain_text("<p>Hello&nbsp;world</p><script>ignore()</script><style>x{}</style><p>Team</p>"), "Hello world Team")
        self.assertEqual(plain_text("&lt;p&gt;Hello world&lt;/p&gt;"), "Hello world")

    def test_hash_normalizes_markup_case_and_whitespace(self):
        first = dict(POSTING, description="<p>Lead  customers</p>")
        second = dict(POSTING, description="lead customers")
        self.assertEqual(material_hash(first), material_hash(second))
        self.assertEqual(changed_fields(first, second), [])

    def test_hash_tracks_compensation_and_responsibilities(self):
        for change in ({"description": "Write production firmware"}, {"compensation": "USD 90000 annual base"}, {"location": "Ohio"}):
            new = dict(POSTING, **change)
            with self.subTest(change=change):
                self.assertNotEqual(material_hash(POSTING), material_hash(new))
                self.assertEqual(changed_fields(POSTING, new), list(change))

    def test_snapshot_roundtrip_retains_evidence(self):
        value = {"v": 1, "evaluated": POSTING, "pending": dict(POSTING, title="New title"), "evaluations": [{"decision": "accept", "note": "Résumé – verified"}]}
        self.assertEqual(unpack_snapshot(pack_snapshot(value)), value)
        self.assertEqual(unpack_snapshot("")["evaluations"], [])

    def test_snapshot_corruption_refuses_silent_reset(self):
        for value in ("not-a-snapshot", "JSH1:!!!", "JSH1:AAAA", 123):
            with self.subTest(value=value), self.assertRaises(ValueError):
                unpack_snapshot(value)

    def test_snapshot_rejects_unknown_version_and_invalid_shapes(self):
        for value in ({"v": 2, "evaluations": []}, {"v": 1, "evaluations": "bad"}, {"v": 1, "evaluations": ["bad"]}, {"v": 1, "evaluations": [], "pending": 5}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                unpack_snapshot(pack_snapshot(value))

    def test_snapshot_limits_uncompressed_evidence(self):
        with self.assertRaises(ValueError):
            pack_snapshot({"v": 1, "evaluations": [], "huge": "x" * 2_000_001})

    def test_snapshot_limits_compressed_cell_size(self):
        noise = base64.b64encode(random.Random(42).randbytes(90_000)).decode()
        with self.assertRaises(ValueError):
            pack_snapshot({"v": 1, "evaluations": [], "noise": noise})

    def test_snapshot_limits_decompression(self):
        raw = json.dumps({"v": 1, "evaluations": [], "huge": "x" * 2_100_000}).encode()
        compressed = "JSH1:" + base64.b64encode(zlib.compress(raw)).decode()
        with self.assertRaises(ValueError):
            unpack_snapshot(compressed)

    def test_reconsideration_counts_do_not_reset_corruption(self):
        self.assertEqual(reconsiderations({"Reconsideration Count": "2"}), 2)
        self.assertEqual(reconsiderations(None), 0)
        for value in ("bad", -1, "1.5", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                reconsiderations({"Reconsideration Count": value})

    def test_valid_acceptance_and_missing_salary(self):
        validate_decision(assessment(), POSTING, {})
        validate_decision(assessment(base_max_usd=None), POSTING, {})
        validate_decision(assessment(base_max_usd=120000), POSTING, {})

    def test_acceptance_requires_false_for_every_hard_blocker(self):
        for field in ("mandatory_clearance", "code_authoring_required", "primary_test_automation"):
            for value in (True, None, 0, "false"):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    validate_decision(assessment(**{field: value}), POSTING, {})
            missing = assessment()
            del missing[field]
            with self.subTest(field=field, value="missing"), self.assertRaises(ValueError):
                validate_decision(missing, POSTING, {})

    def test_below_floor_acceptance_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_decision(assessment(base_max_usd=119999), POSTING, {})
        validate_decision(assessment(decision="reject", base_max_usd=100000), POSTING, {})

    def test_salary_must_be_number_not_bool_nan_or_string(self):
        for value in (True, "180000", -1, float("nan"), float("inf"), 10_000_001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_decision(assessment(base_max_usd=value), POSTING, {})

    def test_decision_must_match_current_hash_and_policy(self):
        for changes in ({"description_hash": "stale"}, {"policy_version": "old"}, {"reviewer": ""}, {"narrative": ""}, {"fit_level": "No Match"}, {"decision": "maybe"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_decision(assessment(**changes), POSTING, {})

    def test_changed_baseline_needs_explicit_material_judgment(self):
        previous = {"evaluated": dict(POSTING, compensation="USD 120000 annual base")}
        with self.assertRaises(ValueError):
            validate_decision(assessment(), POSTING, previous)
        validate_decision(assessment(material_change=False), POSTING, previous)
        validate_decision(assessment(material_change=True), POSTING, previous)

    def test_missing_description_stays_needs_info(self):
        pending = dict(POSTING, description="")
        decision = assessment(description_hash=material_hash(pending))
        with self.assertRaises(ValueError):
            validate_decision(decision, pending, {})
        decision["decision"] = "needs_info"
        validate_decision(decision, pending, {})


class CliTests(unittest.TestCase):
    def test_scraper_help_lists_available_commands(self):
        for args in ([], ["help"], ["--help"], ["-h"]):
            with self.subTest(args=args), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runner.main(args), 0)
                text = output.getvalue()
                self.assertIn("Usage: ./job-search-scraper <command>", text)
                self.assertIn("start        Start or resume the automated scraper.", text)
                self.assertIn("--fetch-workers N", text)
                self.assertIn("--assignment-window N", text)
                self.assertIn("--sheet-request-interval SECONDS", text)
                self.assertIn("./job-search-helper cleanup-blacklist", text)

    def test_scraper_unknown_command_points_to_help(self):
        with redirect_stderr(io.StringIO()) as output:
            self.assertEqual(runner.main(["bogus"]), 2)
            self.assertIn("Run ./job-search-scraper help", output.getvalue())

    def test_scraper_start_still_runs_start_command(self):
        with patch.object(runner, "run_start", return_value=0) as start:
            self.assertEqual(runner.main(["start"]), 0)
            start.assert_called_once_with(fetch_workers=1, assignment_window=25, sheet_request_interval=1.1)

    def test_scraper_start_passes_parallel_options(self):
        with patch.object(runner, "run_start", return_value=0) as start:
            self.assertEqual(runner.main([
                "start", "--fetch-workers", "4", "--assignment-window", "25",
                "--sheet-request-interval", "0.8",
            ]), 0)
            start.assert_called_once_with(fetch_workers=4, assignment_window=25, sheet_request_interval=0.8)

    def test_start_requires_an_explicit_scope(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.parser().parse_args(["start"])
        self.assertTrue(cli.parser().parse_args(["start", "--all"]).all)
        self.assertEqual(cli.parser().parse_args(["start", "--company-id", "COMP-1", "--company-id", "COMP-2"]).company_id, ["COMP-1", "COMP-2"])

    def test_all_and_specific_company_are_mutually_exclusive(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.parser().parse_args(["start", "--all", "--company-id", "COMP-1"])

    def test_apply_requires_exclusive_writer(self):
        with self.assertRaises(ValueError):
            cli.require_single_writer(argparse.Namespace(workers=1, apply=True, exclusive_writer=False))
        cli.require_single_writer(argparse.Namespace(workers=1, apply=True, exclusive_writer=True))

    def test_multiple_workers_are_refused_even_without_apply(self):
        for workers in (0, 2, -1):
            with self.subTest(workers=workers), self.assertRaises(ValueError):
                cli.require_single_writer(argparse.Namespace(workers=workers, apply=False, exclusive_writer=True))

    def test_apply_dry_run_conflict_never_opens_repository(self):
        with patch.object(cli, "get_repository") as repository, redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["start", "--all", "--apply", "--dry-run"]), 2)
            repository.assert_not_called()

    def test_known_backup_is_refused_before_authorization(self):
        with patch.dict(os.environ, {"SPREADSHEET_ID": "1avssxbKDXMrKS0oFHNAfhbQ2HWNz3T_jkn4DSUEmqv0"}), patch.object(cli, "authorize") as auth:
            with self.assertRaises(ValueError):
                cli.get_repository(write=True)
            auth.assert_not_called()

    def test_environment_is_not_shell_evaluated(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            path = Path(temporary) / "example.env"
            path.write_text("# comment\nJSH_VALUE='$(touch SHOULD_NOT_EXIST)'\nJSH_NUMBER=42\n", encoding="utf-8")
            cli.load_environment(path)
            self.assertEqual(os.environ["JSH_VALUE"], "$(touch SHOULD_NOT_EXIST)")
            self.assertEqual(os.environ["JSH_NUMBER"], "42")
            self.assertFalse((Path(temporary) / "SHOULD_NOT_EXIST").exists())

    def test_environment_rejects_malformed_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "example.env"
            for value in ("source script.sh", "BAD NAME=value", "NAME='unclosed"):
                path.write_text(value, encoding="utf-8")
                with self.subTest(value=value), self.assertRaises(ValueError):
                    cli.load_environment(path)

    def test_test_command_uses_project_tests_regardless_of_cwd(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "PROJECT_ROOT", Path(temporary)), patch.object(cli.subprocess, "call", return_value=0) as run:
            self.assertEqual(cli.main(["test"]), 0)
            args, kwargs = run.call_args
            self.assertIn(str(Path(temporary) / "tests"), args[0])
            self.assertEqual(kwargs["cwd"], Path(temporary))
            self.assertEqual(kwargs["env"]["PYTHONPATH"], str(Path(temporary) / "src"))

    def test_status_does_not_create_state(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "PROJECT_ROOT", Path(temporary)), patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["status"]), 0)
            self.assertEqual(json.loads(output.getvalue())["cycles"], [])
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_dry_start_neither_changes_source_repo_nor_saves_state(self):
        source = MemoryRepository({"Companies": [{"Company": "Fixture Company", "Company ID": "COMP-1", "Company Status": "Active", "ATS / Source": "Greenhouse", "Official Careers URL": "https://boards.greenhouse.io/fixture"}]})
        before = copy.deepcopy(source.tables)
        def offline_engine(repo, state, dry_run=False, batch_size=25):
            return Engine(repo, state, dry_run=dry_run, batch_size=batch_size, fetcher=lambda *args: Inventory("blocked", reason="Offline test block"))
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "PROJECT_ROOT", Path(temporary)), patch.dict(os.environ, {}, clear=True), patch.object(cli, "get_repository", return_value=source) as repository, patch.object(cli, "Engine", side_effect=offline_engine), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as error:
            self.assertEqual(cli.main(["start", "--company-id", "COMP-1", "--dry-run"]), 0, error.getvalue())
            self.assertEqual(source.tables, before)
            self.assertFalse((Path(temporary) / ".state").exists())
            repository.assert_called_once_with(write=False, interactive=False)

    def test_dry_resume_clones_and_preserves_saved_state(self):
        source = MemoryRepository()
        class ModifyingEngine:
            def __init__(self, repo, state, dry_run=False, batch_size=25):
                self.state = state
                if not dry_run:
                    raise AssertionError("Expected dry run")
            def resume(self, cycle_id, retry_blocked=False):
                self.state.save_cycle({"id": cycle_id, "status": "changed-in-memory"})
                return {"cycle": cycle_id}
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "PROJECT_ROOT", Path(temporary)), patch.dict(os.environ, {}, clear=True):
            database = Path(temporary) / ".state" / "state.db"
            state = State(database)
            state.save_cycle({"id": "CYCLE-1", "status": "original"})
            state.close()
            before = database.read_bytes()
            with patch.object(cli, "get_repository", return_value=source), patch.object(cli, "Engine", ModifyingEngine), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as error:
                self.assertEqual(cli.main(["resume", "--cycle", "CYCLE-1", "--dry-run"]), 0, error.getvalue())
            self.assertEqual(database.read_bytes(), before)
            check = State(database, readonly=True)
            try:
                self.assertEqual(check.cycle("CYCLE-1")["status"], "original")
            finally:
                check.close()


if __name__ == "__main__":
    unittest.main()
