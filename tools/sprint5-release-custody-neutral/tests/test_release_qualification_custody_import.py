"""The release gate must not acquire a provider-specific capture dependency."""
import subprocess
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"


class ReleaseQualificationCustodyImportTests(unittest.TestCase):
    def test_release_qualification_imports_without_ordinary_raw_capture(self):
        program = """
import importlib, importlib.abc, sys
sys.path.insert(0, {source!r})
class BlockOrdinaryRaw(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'job_search_helper.ordinary_raw_capture':
            raise AssertionError('release qualification imported provider-specific raw capture')
        return None
sys.meta_path.insert(0, BlockOrdinaryRaw())
module = importlib.import_module('job_search_helper.release_qualification')
assert module.private.__name__ == 'job_search_helper.private_file_custody'
assert 'job_search_helper.ordinary_raw_capture' not in sys.modules
try:
    module.private.decode(b'{{')
except module.private.CustodyError as error:
    assert str(error) == 'invalid_capture_metadata' and error.__suppress_context__
else:
    raise AssertionError('malformed metadata was accepted')
""".format(source=str(SOURCE))
        completed = subprocess.run(
            [sys.executable, '-I', '-S', '-B', '-c', program], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == '__main__':
    unittest.main()
