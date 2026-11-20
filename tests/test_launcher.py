"""One public helper command contract for package and checkout entrypoints."""
from unittest.mock import patch
import unittest

class LauncherTests(unittest.TestCase):
    def test_start_uses_scraper_defaults_and_other_commands_keep_helper_routing(self):
        from job_search_helper import launcher
        with patch.object(launcher.os, 'execv', side_effect=SystemExit(17)) as scraper, patch('job_search_helper.cli.main', return_value=23) as helper:
            with self.assertRaises(SystemExit) as exit_status:
                launcher.main(['start', '--resume'])
            self.assertEqual(exit_status.exception.code, 17)
            self.assertEqual(scraper.call_args.args[1][-2:], ['start', '--resume'])
            helper.assert_not_called()
            self.assertEqual(launcher.main(['status']), 23)
            helper.assert_called_once_with(['status'])

    def test_package_entrypoint_uses_shared_dispatch(self):
        import tomllib
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((root / 'pyproject.toml').read_text())
        self.assertEqual(project['project']['scripts']['job-search-helper'], 'job_search_helper.launcher:main')
