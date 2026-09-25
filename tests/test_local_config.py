from pathlib import Path
import tempfile
import unittest

from job_search_helper.config import load_settings


class LocalConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write_settings(self, content):
        path = self.root / "config/settings.toml"
        path.parent.mkdir(exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_empty_workspace_is_neutral_and_read_only(self):
        settings = load_settings(workspace=self.root, environ={})
        self.assertEqual(settings.database, self.root / "data/job-search-helper.sqlite3")
        self.assertEqual(settings.missing_threshold, 2)
        self.assertFalse(settings.browser_enabled)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_settings_and_paths_resolve_against_workspace(self):
        self.write_settings('[storage]\ndatabase = "private/catalog.sqlite3"\n[scan]\nworkers = 3\n')
        settings = load_settings(workspace=self.root, environ={})
        self.assertEqual(settings.database, self.root / "private/catalog.sqlite3")
        self.assertEqual(settings.workers, 3)

    def test_cli_overrides_environment_overrides_file(self):
        self.write_settings('[storage]\ndatabase = "file.sqlite3"\n')
        env = {"JSH_WORKSPACE": str(self.root), "JSH_DATABASE": "env.sqlite3"}
        self.assertEqual(load_settings(environ=env).database, self.root / "env.sqlite3")
        self.assertEqual(load_settings(database="cli.sqlite3", environ=env).database, self.root / "cli.sqlite3")

    def test_explicit_missing_file_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "Cannot read settings"):
            load_settings(workspace=self.root, settings_file="missing.toml", environ={})

    def test_explicit_environment_settings_file(self):
        path = self.root / "custom.toml"
        path.write_text('[scan]\nworkers = 2\n', encoding="utf-8")
        self.assertEqual(load_settings(workspace=self.root, environ={"JSH_SETTINGS": "custom.toml"}).workers, 2)

    def test_rejects_malformed_unknown_wrong_type_and_unbounded_settings(self):
        for content in (
            '[scan', '[personal]\nsalary=120000', '[scan]\nworkres=2', 'scan=3',
            '[scan]\nworkers=true', '[scan]\nworkers=6', '[scan]\nmissing_threshold=0',
            '[scan]\ntimeout_seconds=nan', '[scan]\ntimeout_seconds=inf',
            '[scan]\nhost_interval_seconds=-1', '[scan]\nbrowser_enabled="false"',
            '[storage]\ndatabase=""', '[storage]\ndatabase=5',
        ):
            with self.subTest(content=content):
                self.write_settings(content)
                with self.assertRaises(ValueError):
                    load_settings(workspace=self.root, environ={})

    def test_empty_explicit_database_rejected(self):
        with self.assertRaises(ValueError):
            load_settings(workspace=self.root, database="", environ={})
