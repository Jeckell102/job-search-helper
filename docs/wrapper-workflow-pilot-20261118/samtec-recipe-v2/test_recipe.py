import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import recipe

SOURCE = Path('/home/chris/job-search-helper_old/temp/pilot-samtec-20261118/assisted-candidate-1/repo') / recipe.TARGET_PATH

class RecipeTests(unittest.TestCase):
    def test_exact_selection_and_duplicate_keys(self):
        self.assertEqual(recipe.read_selection(json.dumps(recipe.SELECTIONS)), recipe.SELECTIONS)
        invalid = [None, [], {}, dict(recipe.SELECTIONS, url='https://evil.example'),
                   dict(recipe.SELECTIONS, listing='featured_jobs'), dict(recipe.SELECTIONS, listing='__import__("os")'),
                   dict(recipe.SELECTIONS, pagination=True), dict(recipe.SELECTIONS, range=None)]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                recipe.validate_selection(value)
        raw=json.dumps(recipe.SELECTIONS).replace('"listing":', '"listing":"full_search","listing":')
        with self.assertRaises(ValueError):recipe.read_selection(raw)
        with self.assertRaises(ValueError):recipe.read_selection(' '*4097)

    def test_source_and_helper_hashes_fail_closed(self):
        source=SOURCE.read_bytes()
        with self.assertRaises(ValueError):recipe.build(source+b'\n',recipe.SELECTIONS)
        with patch.object(Path,'read_bytes',return_value=b'untrusted implementation'):
            with self.assertRaises(ValueError):recipe.build(source,recipe.SELECTIONS)

    def test_exact_scoped_diff_and_authorship_no_install(self):
        source=SOURCE.read_bytes(); before=hashlib.sha256(source).hexdigest()
        result=recipe.build(source,recipe.SELECTIONS)
        helper=Path(recipe.__file__).with_name('samtec_helper.py.txt').read_text()
        detail=Path(recipe.__file__).with_name('samtec_detail.py.txt').read_text()
        content=result['content'].replace(detail, '', 1).replace(recipe.DETAIL_DISPATCH, '', 1)
        restored=content.replace(helper+recipe.DISPATCH,recipe.ENTRY,1).replace(recipe.NEW_ALLOWED,recipe.OLD_ALLOWED,1)
        self.assertEqual(restored.encode(),source)
        self.assertEqual(result['content'].count(recipe.ROUTE),1)
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(),before)
        self.assertFalse(result['receipt']['installed']);self.assertFalse(result['receipt']['live_validated'])
        self.assertIn('host-written',result['receipt']['authorship'])
        self.assertEqual(result['receipt']['binding']['company_id'],'COMP-0739')
        self.assertEqual(result['receipt']['output_sha256'],hashlib.sha256(result['content'].encode()).hexdigest())
        compile(result['content'],recipe.TARGET_PATH,'exec')

if __name__=='__main__':unittest.main()
