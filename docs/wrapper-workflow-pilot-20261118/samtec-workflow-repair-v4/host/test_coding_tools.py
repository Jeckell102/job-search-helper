import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import coding_tools as c


class CodingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        for name in ['src','tests','docs']:(self.root/name).mkdir()
        self.p=patch.object(c,'ROOT',self.root);self.p.start()
        self.scope_token = c.EDIT_SCOPE.set(['src/a.py', 'src/b.py', 'docs/wrapper-development-test-protocol.md'])
    def tearDown(self):
        c.EDIT_SCOPE.reset(self.scope_token)
        self.p.stop();self.temp.cleanup()
    def test_missing_scope_cannot_create_or_edit(self):
        source = self.root / 'src/a.py'
        source.write_text('value = 1')
        token = c.EDIT_SCOPE.set(None)
        try:
            for name, args in (
                ('code_create', {'path': 'src/b.py', 'content': 'bad'}),
                ('code_edit', {'path': 'src/a.py', 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'old': '1', 'new': '2'}),
            ):
                result = c.execute(name, args, c.NAMES)
                self.assertFalse(result['ok'])
                self.assertIn('explicit approved edit scope', result['error'])
            self.assertEqual(source.read_text(), 'value = 1')
            self.assertFalse((self.root / 'src/b.py').exists())
        finally:
            c.EDIT_SCOPE.reset(token)

    def test_authenticated_manual_bridge_sets_and_clears_exact_scope(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('manual_scope_bridge', Path(c.__file__).with_name('host_server.py'))
        bridge = importlib.util.module_from_spec(spec)
        with patch.object(Path, 'read_text', return_value='test-token'):
            spec.loader.exec_module(bridge)
        token = c.EDIT_SCOPE.set(None)
        try:
            self.assertTrue(bridge.execute_manual('code_create', {'path': 'src/a.py', 'content': 'value = 1'}, {'code_create'})['ok'])
            self.assertIsNone(c.EDIT_SCOPE.get())
            self.assertFalse(bridge.execute_manual('code_create', {'path': 'src/b.py', 'content': 'bad'}, set())['ok'])
            self.assertFalse((self.root / 'src/b.py').exists())
            workspace = c.WORKSPACE.set(self.root)
            try:
                with self.assertRaisesRegex(ValueError, 'inherit'):
                    bridge.execute_manual('code_create', {'path': 'src/b.py', 'content': 'bad'}, {'code_create'})
            finally:
                c.WORKSPACE.reset(workspace)
        finally:
            c.EDIT_SCOPE.reset(token)

    def test_required_protocol_is_readable_but_not_model_editable(self):
        p=self.root/'docs/wrapper-development-test-protocol.md';p.write_text('required steps')
        r=c.execute('code_read', {'path': 'docs/wrapper-development-test-protocol.md'}, c.NAMES)
        self.assertTrue(r['ok'])
        for name in ['docs/wrapper-development-test-protocol.md', 'docs//wrapper-development-test-protocol.md']:
            r=c.execute('code_edit', {'path':name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'old':'required','new':'optional'}, c.NAMES)
            self.assertFalse(r['ok'])
        self.assertEqual(p.read_text(),'required steps')

    def test_path_escape_and_hidden_files(self):
        for path in ['../config/key','src/../../key','/etc/passwd','src/.env','tests/x.sh','src/../tests/x.py']:
            with self.assertRaises(ValueError):c.path_for(path,True)
    def test_symlink_and_hardlink(self):
        outside=self.root/'outside.py';outside.write_text('private')
        (self.root/'src/link.py').symlink_to(outside)
        with self.assertRaises(ValueError):c.path_for('src/link.py')
        (self.root/'src/hard.py').hardlink_to(outside)
        with self.assertRaises(ValueError):c.path_for('src/hard.py')
    def test_create_read_guard_edit_and_no_overwrite(self):
        a=c.execute('code_create',{'path':'src/a.py','content':'x = 1\n'},c.NAMES);self.assertTrue(a['ok'])
        self.assertFalse(c.execute('code_create',{'path':'src/a.py','content':'bad'},c.NAMES)['ok'])
        read=c.execute('code_read',{'path':'src/a.py'},c.NAMES)['result']
        args={'path':'src/a.py','sha256':read['sha256'],'old':'x = 1','new':'x = 2'}
        self.assertTrue(c.execute('code_edit',args,c.NAMES)['ok'])
        self.assertFalse(c.execute('code_edit',args,c.NAMES)['ok'])
        self.assertEqual((self.root/'src/a.py').read_text(),'x = 2\n')
    def test_read_only_authorization(self):
        names=c.scope([{'role':'user','content':'Review only; do not edit the wrapper.'}])
        self.assertNotIn('code_edit',names)
        self.assertFalse(c.execute('code_create',{'path':'src/a.py','content':'x'},names)['ok'])
        self.assertNotIn('code_commit',c.scope([{'role':'user','content':'Fix and test the wrapper without commit'}]))
    def test_test_path_arguments(self):
        for value in ['', '-c exploit.py', 'src/a.py', 'tests/../../evil.py', 'tests/x.py --override-ini=x']:
            with self.assertRaises(ValueError):c.run_tests(value)
    def test_argument_validation(self):
        for args in [{'path':1},{'path':'src/a.py','extra':1},{'path':'src/a.py','start_line':True}]:
            self.assertFalse(c.execute('code_read',args,c.NAMES)['ok'])
    def test_unique_edit_and_size_limit(self):
        p=self.root/'src/a.py';p.write_text('xx')
        args={'path':'src/a.py','sha256':hashlib.sha256(b'xx').hexdigest(),'old':'x','new':'y'}
        self.assertFalse(c.execute('code_edit',args,c.NAMES)['ok'])
        self.assertFalse(c.execute('code_create',{'path':'src/b.py','content':'x'*(c.MAX_FILE+1)},c.NAMES)['ok'])

if __name__=='__main__':unittest.main()
