"""One public helper command contract for package and checkout entrypoints."""
from unittest.mock import patch
import unittest

class LauncherTests(unittest.TestCase):
    def test_start_uses_scraper_defaults_and_other_commands_keep_helper_routing(self):
        from job_search_helper import launcher
        with patch('job_search_helper.runner.main', return_value=17) as scraper, patch('job_search_helper.cli.main', return_value=23) as helper:
            self.assertEqual(launcher.main(['start', '--resume']), 17)
            scraper.assert_called_once_with(['start', '--resume'])
            helper.assert_not_called()
            self.assertEqual(launcher.main(['status']), 23)
            helper.assert_called_once_with(['status'])

    def test_package_entrypoint_uses_shared_dispatch(self):
        import tomllib
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((root / 'pyproject.toml').read_text())
        self.assertEqual(project['project']['scripts']['job-search-helper'], 'job_search_helper.launcher:main')
