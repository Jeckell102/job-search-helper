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
    def tearDown(self):self.p.stop();self.temp.cleanup()
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
    def test_wrapper_profile_context(self):
        from profile_policy import resolve_profile
        self.assertEqual(resolve_profile('Wrapper Coder').context_tokens,12288)
        for name in ['Instant','Advanced','Pro']:self.assertEqual(resolve_profile(name).context_tokens,4096)


if __name__=='__main__':unittest.main()
