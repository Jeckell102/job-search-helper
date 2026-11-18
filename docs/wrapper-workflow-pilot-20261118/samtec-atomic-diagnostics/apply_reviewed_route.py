import hashlib,json,shutil,sys
from pathlib import Path
base=Path('/home/chris/job-search-helper_old/dev/wrapper-coder');src=base/'tasks/WRAP-756e8b251b/repo'
stage=Path(__file__).resolve().parent
out=Path('/home/chris/job-search-helper_old/temp/pilot-samtec-20261118/assisted-candidate-1');out.mkdir(exist_ok=False);repo=out/'repo';repo.mkdir()
response=Path('/home/chris/job-search-helper_old/temp/pilot-samtec-20261118/atomic-route-thinking-2/response.json')
qa=json.loads((stage/'atomic-route-thinking-2-QA.json').read_text());assert qa['result']=='PASS_BOUNDED_PROPOSAL' and qa['response_sha256']==hashlib.sha256(response.read_bytes()).hexdigest()
proposal=json.loads(response.read_text())['message']['tool_calls'][0]['function'];args=proposal['arguments'];assert proposal['name']=='code_edit'
assert hashlib.sha256((src/args['path']).read_bytes()).hexdigest()==args['sha256']==qa['source_sha256']
for name in ('src','tests','docs'):
 shutil.copytree(src/name,repo/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
for name in ('pyproject.toml','pytest.ini','setup.cfg','setup.py'):
 if (src/name).is_file():shutil.copy2(src/name,repo/name)
sys.path.insert(0,str(base/'tools'));import coding_tools
w=coding_tools.WORKSPACE.set(repo);s=coding_tools.EDIT_SCOPE.set({'paths':[args['path']]})
try:result=coding_tools.execute('code_edit',args,{'code_edit'})
finally:coding_tools.EDIT_SCOPE.reset(s);coding_tools.WORKSPACE.reset(w)
assert result['ok'],result
receipt={'classification':'operator-assisted AI-authored route patch; not integration acceptance','parent_task':'WRAP-756e8b251b','source_task_unchanged':hashlib.sha256((src/args['path']).read_bytes()).hexdigest()==args['sha256'],'proposal_sha256':hashlib.sha256(response.read_bytes()).hexdigest(),'qa':qa['result'],'tests':f"{qa['passed']}/{qa['total']}",'result':result,'candidate':str(repo)}
(out/'route-application.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
