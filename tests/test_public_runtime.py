"""Contract checks for the standalone public application."""
from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from job_search_helper import local_cli
from job_search_helper.compensation import parse_annual_base_max_usd
from job_search_helper.posting import canonicalize_url, job_key, material_hash, plain_text


class PublicRuntimeTests(unittest.TestCase):
    def test_entry_point_does_not_import_legacy_workflow(self):
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        result = subprocess.run([sys.executable, "-c", """
import sys
from job_search_helper import local_cli
assert local_cli.main([]) == 0
for name in ('cli', 'core', 'efficiency', 'engine', 'repository', 'runner', 'screening'):
    assert 'job_search_helper.' + name not in sys.modules, name
"""], env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_public_help_and_legacy_command_refusal(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(local_cli.main([]), 0)
        self.assertIn("init", output.getvalue())
        self.assertNotIn("authenticate", output.getvalue())
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            local_cli.main(["auth", "--write"])
        self.assertEqual(error.exception.code, 2)

    def test_interruption_has_documented_exit_code(self):
        with patch("job_search_helper.local_cli.execute", side_effect=KeyboardInterrupt), redirect_stderr(io.StringIO()):
            self.assertEqual(local_cli.main(["doctor"]), 130)

    def test_shared_identities_and_hashes_preserve_evidence_contract(self):
        self.assertEqual(canonicalize_url("https://example.com/job?utm_source=test&gh_jid=123"),
                         "https://example.com/job?gh_jid=123")
        self.assertEqual(job_key(" C-1 ", "Lever", "123", ""), "c-1:lever:123")
        self.assertEqual(plain_text("<p>Research &amp; development</p><script>hidden</script>"), "Research & development")
        self.assertEqual(material_hash({"title": "<b>Engineer</b>"}), material_hash({"title": "engineer"}))
        self.assertNotEqual(material_hash({"title": "Engineer"}), material_hash({"title": "Analyst"}))

    def test_shared_salary_parser_has_no_minimum_policy(self):
        self.assertEqual(parse_annual_base_max_usd("USD 40,000 - 50,000 annual base salary"), 50000)
        self.assertEqual(parse_annual_base_max_usd("Base USD 80k plus bonus USD 10k"), 80000)
        for value in ("CAD 80000 annual base", "USD 50 per hour", "USD 100000 OTE", "unknown"):
            with self.subTest(value=value):
                self.assertIsNone(parse_annual_base_max_usd(value))


if __name__ == "__main__":
    unittest.main()
