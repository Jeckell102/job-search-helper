from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper import cli, runner
from job_search_helper.cleanup import cleanup_blacklisted_history
from job_search_helper.core import excluded_title
from job_search_helper.efficiency import classify_title, _load_title_patterns
from job_search_helper.repository import MemoryRepository


class TitleScreeningTests(unittest.TestCase):
    def test_exclusions_win_over_relevant_function_with_case_and_punctuation(self):
        for title in ("STAFF Solutions Engineer", "Principal: Field Applications Engineer",
                      "Director of Field Engineering", "Solutions Engineering Director",
                      "Associate Director, Technical Training", "Software Engineer / Solutions Engineer"):
            with self.subTest(title=title):
                self.assertEqual(classify_title(title), "reject")
                self.assertTrue(excluded_title(title))

    def test_review_list_and_unknown_titles_do_not_imply_acceptance(self):
        for title in ("Solutions Engineer", "Field-Applications Engineer", "Systems Integration Engineer",
                      "Technical Program Manager", "Technical Account Manager",
                      "Implementation Manager", "Technical Product Marketing Manager"):
            with self.subTest(title=title):
                self.assertEqual(classify_title(title), "review")
                self.assertFalse(excluded_title(title))
        for title in ("", "Operations Manager", "Program Manager", "Support Engineer",
                      "Staffing Specialist", "Directorate Liaison", "Principalship Coordinator"):
            with self.subTest(title=title):
                self.assertEqual(classify_title(title), "ambiguous")

    def test_editable_lists_accept_comments_phrases_and_regex_and_fail_on_invalid_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "titles.txt"
            path.write_text("# comment\n\nsolutions engineer\nregex:\\bdeployment (lead|manager)\\b\n")
            patterns = _load_title_patterns(path)
            self.assertTrue(patterns[0].search("SOLUTIONS-ENGINEER"))
            self.assertFalse(patterns[0].search("Solutions Engineering"))
            self.assertTrue(patterns[1].search("Deployment Manager"))
            path.write_text("regex:[\n")
            with self.assertRaisesRegex(ValueError, "line 1"):
                _load_title_patterns(path)
            path.unlink()
            with self.assertRaisesRegex(ValueError, "Cannot read title list"):
                _load_title_patterns(path)

    def test_cleanup_preserves_manual_no_and_only_updates_identifiable_unlocked_exclusions(self):
        titles = ["Staff Solutions Engineer", "Principal Field Applications Engineer",
                  "Technical Support Director", "Solutions Engineer", "Operations Manager",
                  "Technical Program Manager", "Director of Field Engineering",
                  "Principal Customer Engineer", "Principal Customer Engineer"]
        rows = [{"Company": "Acme", "Job Title": title, "Job Key": str(index),
                 "Added to Opportunities?": "Yes", "Review Notes": "keep me"}
                for index, title in enumerate(titles)]
        rows[5]["Added to Opportunities?"] = "No"
        rows[6]["Review Status"] = "In Progress"
        for row in rows[7:]:
            row.pop("Job Key")
        repo = MemoryRepository({"Job History": rows})
        before = repo.read("Job History")
        preview = cleanup_blacklisted_history(repo)
        self.assertEqual(repo.read("Job History"), before)
        self.assertEqual(preview["spreadsheet_changes"], 0)
        self.assertEqual(preview["blacklisted_titles"], 6)
        self.assertEqual(preview["potentially_good_titles"], 2)
        self.assertEqual(preview["uncertain_titles"], 1)
        self.assertEqual(len(preview["potentially_good_not_already_no"]), 1)
        self.assertEqual(preview["locked_in_progress"], 1)
        self.assertEqual(preview["unresolved_identity"], 2)
        applied = cleanup_blacklisted_history(repo, apply=True)
        self.assertEqual(applied["updated"], 3)
        after = repo.read("Job History")
        for index, (old, new) in enumerate(zip(before, after)):
            self.assertEqual(new, {**old, "Added to Opportunities?": "No"} if index < 3 else old)
        self.assertEqual(cleanup_blacklisted_history(repo, apply=True)["updated"], 0)

    def test_scraper_cleanup_titles_applies_by_default_and_supports_preview_and_alias(self):
        for command in ("cleanup-titles", "--cleanup-titles"):
            with patch.object(runner.helper_cli, "main", return_value=0) as delegated:
                self.assertEqual(runner.main([command]), 0)
                delegated.assert_called_once_with(["cleanup-titles", "--apply", "--exclusive-writer"])
        with patch.object(runner.helper_cli, "main", return_value=0) as delegated:
            runner.main(["cleanup-titles", "--dry-run"])
            delegated.assert_called_once_with(["cleanup-titles", "--dry-run"])

    def test_cleanup_titles_cli_uses_read_only_repository_for_preview(self):
        with patch.object(cli, "get_repository") as repository, \
                patch.object(cli, "cleanup_blacklisted_history", return_value={}) as cleanup, \
                redirect_stdout(StringIO()):
            self.assertEqual(cli.main(["cleanup-titles", "--dry-run"]), 0)
        repository.assert_called_once_with(write=False, interactive=False)
        cleanup.assert_called_once_with(repository.return_value, apply=False)

    def test_help_describes_lists_and_command(self):
        with redirect_stdout(StringIO()) as output:
            runner.main(["--help"])
        self.assertIn("cleanup-titles", output.getvalue())
        self.assertIn("title-review-list.txt", output.getvalue())
        self.assertIn("Staff, Principal, and Director", output.getvalue())


if __name__ == "__main__":
    unittest.main()
