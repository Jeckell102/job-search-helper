"""Actual offline OS-sandbox acceptance check; no inference or production writes."""
import json
from pathlib import Path
import sys
import tempfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'wrapper-workflow-20261118/host'))
import coding_tools as code
import coordinator_acceptance as acceptance
from coordinator_store import Store

with tempfile.TemporaryDirectory(prefix='wrapper-acceptance-qa-') as tmp:
    root=Path(tmp)/'repo'
    for name in ('src','tests','docs'): (root/name).mkdir(parents=True)
    (root/'src/company.py').write_text('value = 0\n')
    (root/'tests/test_company.py').write_text('from company import value\ndef test_company():\n    assert value == 1\n')
    (root/'pyproject.toml').write_text('[tool.pytest.ini_options]\n')
    code.ROOT=root;code.BASE=Path(tmp);code.VENV=Path('/home/chris/job-search-helper_old/.venv')
    store=Store(Path(tmp)/'tasks')
    state=store.create('Inspect src/company.py tests/test_company.py',['tests/test_company.py'],'develop',authorization_version=1)
    state=acceptance.ensure_bundle(store,state,root)
    (root/'tests/test_company.py').write_text('def test_company(): pass\n')
    editable=code.run_tests('tests/test_company.py')
    frozen_bad=acceptance.verify_bundle(store,state,root)
    (root/'src/company.py').write_text('value = 1\n')
    frozen_good=acceptance.verify_bundle(store,state,root)
    assert editable['exit_code']==0,editable
    assert frozen_bad['exit_code']==1 and 'AssertionError' in frozen_bad['output'],frozen_bad
    assert frozen_good['exit_code']==0,frozen_good
    report=dict(result='PASS',editable_stub=editable,frozen_bad_source=frozen_bad,frozen_correct_source=frozen_good)
    (HERE/'real-acceptance-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: real systemd/Landlock/seccomp runner; editable stub passes, frozen assertion rejects broken source, corrected source passes.')
