"""Materialize the accepted recipe into an isolated validation copy only."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

proof = Path(__file__).resolve().parent
stage = Path('/tmp/jsh-s5-acquiretm-membership-repair.20261121')
recipe = stage / 'repair_recipe' / 'acquiretm_membership_recipe.py'
witness = Path('/tmp/jsh-s5-amphenol-typed-live/result.json')
native = Path('/home/chris/job-search-helper_old')
candidate = Path('/tmp/jsh-s5-amphenol-recipe-live-candidate')


def digest(data):
    return hashlib.sha256(data).hexdigest()


choice = json.loads((proof / 'choice-receipt.json').read_text())
if (choice['status'] != 'CHOICE_ACCEPTED' or choice['calls'] != 1
        or not choice['model_response_sha256']
        or choice['recipe_sha256'] != digest(recipe.read_bytes())
        or choice['witness_sha256'] != digest(witness.read_bytes())):
    raise RuntimeError('Exact choice and reviewed recipe do not agree')
spec = importlib.util.spec_from_file_location('frozen_acquiretm_recipe', recipe)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
base = stage / 'src' / 'job_search_helper' / 'acquiretm.py'
output = module.build(base.read_bytes(), choice['selection'], witness.read_bytes())
source = output['source'].encode()
if digest(source) != '895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d':
    raise RuntimeError('Compiler result is not the independently reviewed candidate')

candidate.mkdir(mode=0o700)
shutil.copytree(stage / 'src', candidate / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
(candidate / module.TARGET_PATH).write_bytes(source)
(candidate / 'tests').mkdir()
for name in ('test_acquiretm.py', 'test_company_sources.py', 'test_inventory_source_validation.py'):
    source_test = native / 'tests' / name
    if name == 'test_acquiretm.py' and digest(source_test.read_bytes()) != '5bace6904b1630871477aa2b5b408a591813a834742a2bcca85c757c8dd5e908':
        raise RuntimeError('Original immutable acceptance tests drifted')
    shutil.copyfile(source_test, candidate / 'tests' / name)
for name in ('pyproject.toml', 'title-blacklist.txt', 'title-review-list.txt'):
    shutil.copyfile(native / name, candidate / name)
record = {**output['receipt'], 'model_choice_receipt_sha256': digest((proof / 'choice-receipt.json').read_bytes())}
(candidate / 'build-receipt.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
(candidate / 'reviewed.patch').write_text(output['diff'])
print(candidate)
