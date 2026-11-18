import ast
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import recipe

BASE=Path('/home/chris/job-search-helper_old/temp/pilot-samtec-20261118/assisted-candidate-1/repo/src/job_search_helper/shared_boards.py')
STAGE=Path(__file__).parent

class IndependentRecipeTests(unittest.TestCase):
    def test_strict_unknown_missing_wrong_and_code_values(self):
        for bad in [None,[],True,{},dict(recipe.SELECTIONS,host='evil.test'),dict(recipe.SELECTIONS,listing='featured_jobs'),dict(recipe.SELECTIONS,range=True),dict(recipe.SELECTIONS,container={'class':'jv-job-list'}),dict(recipe.SELECTIONS,pagination='__import__("os")')]:
            with self.subTest(value=bad),self.assertRaises(ValueError):recipe.validate_selection(bad)
    def test_raw_json_duplicate_keys_size_and_nonobject_rejected(self):
        raw=json.dumps(recipe.SELECTIONS)
        for bad in [raw[:-1]+',"listing":"full_search"}',raw+' x','[]','null','true',' '*4097,raw.encode()]:
            with self.subTest(value=str(bad)[:100]),self.assertRaises((ValueError,TypeError)):recipe.read_selection(bad)
    def test_exact_base_hash_required(self):
        original=BASE.read_bytes()
        for bad in [original+b'\n',original.replace(b'samtec',b'other',1),original.decode()]:
            with self.assertRaises(ValueError):recipe.build(bad,recipe.SELECTIONS)
    def test_helper_tamper_rejected(self):
        original=BASE.read_bytes()
        with patch.object(recipe.Path,'read_bytes',return_value=b'print("tampered")'),self.assertRaises(ValueError):recipe.build(original,recipe.SELECTIONS)
    def test_actual_receipt_selection_deterministically_builds_identical_output(self):
        response=Path('/home/chris/job-search-helper_old/temp/pilot-samtec-20261118/recipe-selection-1/response.json')
        raw=json.loads(response.read_text())['message']['tool_calls'][0]['function']['arguments']['content']
        selected=recipe.read_selection(raw);before=BASE.read_bytes();built=recipe.build(before,selected);again=recipe.build(before,selected)
        self.assertEqual(built,again);self.assertEqual(before,BASE.read_bytes());self.assertEqual(selected,recipe.SELECTIONS)
        candidate=(STAGE/'acceptance_repo/src/job_search_helper/shared_boards.py').read_bytes()
        self.assertEqual(built['content'].encode(),candidate)
        receipt=json.loads((STAGE/'build-receipt.json').read_text())
        self.assertEqual(receipt['ai_selection_response_sha256'],hashlib.sha256(response.read_bytes()).hexdigest())
        for key,value in built['receipt'].items():self.assertEqual(receipt[key],value)
        self.assertEqual(receipt['binding'],{'company_id':'COMP-0739','company':'Samtec','ats':'Jobvite','host':'jobs.jobvite.com','slug':'samtec'})
    def test_only_bound_guard_and_samtec_helper_dispatch_added(self):
        before=ast.parse(BASE.read_text());after=ast.parse(recipe.build(BASE.read_bytes(),recipe.SELECTIONS)['content'])
        helpers=[n for n in after.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in {'_samtec_html_listing','_SamtecListingPage'}]
        self.assertEqual(len(helpers),2)
        after.body=[n for n in after.body if n not in helpers]
        for tree in (before,after):
            node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='allowed')
            node.body=[n for n in node.body if not (isinstance(n,ast.If) and isinstance(n.test,ast.BoolOp) and ast.unparse(n.test).startswith("b.name == 'Jobvite' and b.slug == 'samtec'"))]
        listing=next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name=='html_listing')
        self.assertEqual(ast.unparse(listing.body[0]),"if b.name == 'Jobvite' and b.slug == 'samtec':\n    return _samtec_html_listing(b, t)")
        listing.body.pop(0)
        self.assertEqual(ast.dump(before),ast.dump(after))

if __name__=='__main__':unittest.main(verbosity=2)
