"""Release assembly must fail closed without changing installed inputs."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'wrapper-workflow-20261118'))
import release_bundle as r


class ReleaseBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.stage, self.installed, self.output = [self.base / s for s in ('stage', 'installed', 'release')]
        names = ['host/' + s for s in ('coordinator.py', 'coordinator_store.py', 'coordinator_workspace.py', 'coordinator_budget.py')]
        names += ['jetson/wrapper_commands.py', 'backlog/batch-1.json', 'WORKFLOW.md', 'deploy_campaign_update.py', 'release_bundle.py', 'rollout_controller.py']
        for name in names:
            p = self.stage / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('# fixture ' + name)
        for name in (*r.PREREQUISITE_FILES, 'resources/tokenizer.json', 'coordinator_vendor/library.py'):
            p = self.installed / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('prerequisite fixture')
        (self.installed / 'obsolete.py').write_text('must not carry into release')
        self.sources = r.source_manifest(self.stage)
        self.prerequisites = r.prerequisite_manifest(self.installed)
        self.before = r.tree(self.installed)

    def build(self):
        return r.build_release(self.stage, self.installed, self.output, self.sources, self.prerequisites)

    def test_clean_release_reproduces_all_sources_and_preserves_only_pinned_prerequisites(self):
        value = self.build()
        self.assertEqual(value, r.verify_release(self.output, self.sources, self.prerequisites))
        self.assertFalse((self.output / 'tools/obsolete.py').exists())
        self.assertTrue((self.output / 'tools/coordinator_workspace.py').is_file())
        self.assertTrue((self.output / 'jetson/wrapper_commands.py').is_file())
        self.assertEqual(r.tree(self.installed), self.before)

    def test_changed_or_missing_source_and_prerequisite_reject_before_build(self):
        for relative in ('host/coordinator_workspace.py', 'jetson/wrapper_commands.py'):
            p = self.stage / relative
            original = p.read_bytes()
            p.unlink()
            with self.assertRaises(ValueError):
                self.build()
            self.assertFalse(self.output.exists())
            p.write_bytes(original)
        p = self.installed / 'resources/tokenizer.json'
        p.write_text('changed')
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_postbuild_missing_extra_substitution_and_mode_drift_fail(self):
        self.build()
        path = self.output / 'tools/coordinator.py'
        path.write_text('substituted')
        with self.assertRaisesRegex(ValueError, 'changed='):
            r.verify_release(self.output, self.sources, self.prerequisites)
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'missing='):
            r.verify_release(self.output, self.sources, self.prerequisites)
        path.write_bytes((self.stage / 'host/coordinator.py').read_bytes())
        path.chmod(0o700)
        with self.assertRaises(ValueError):
            r.verify_release(self.output, self.sources, self.prerequisites)
        path.chmod(self.sources['host/coordinator.py']['mode'])
        (self.output / 'tools/unreviewed.py').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'extra='):
            r.verify_release(self.output, self.sources, self.prerequisites)

    def test_symlink_and_existing_destination_rejected(self):
        p = self.installed / 'coordinator_vendor/link.py'
        p.symlink_to(self.installed / 'obsolete.py')
        with self.assertRaises(ValueError):
            r.prerequisite_manifest(self.installed)
        p.unlink()
        self.output.mkdir()
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(r.tree(self.installed), self.before)

    def test_source_mutation_during_copy_fails_and_installed_tree_is_unchanged(self):
        original = r.checked_copy
        changed = False
        def race(source, target, expected):
            nonlocal changed
            original(source, target, expected)
            if not changed:
                changed = True
                (self.stage / 'host/coordinator.py').write_text('racing change')
        with patch.object(r, 'checked_copy', side_effect=race):
            with self.assertRaises(ValueError):
                self.build()
        self.assertEqual(r.tree(self.installed), self.before)


if __name__ == '__main__':
    unittest.main()
