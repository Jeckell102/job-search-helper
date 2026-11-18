import hashlib,json,subprocess,sys
from pathlib import Path
here=Path(__file__).resolve().parent
base=Path('/home/chris/job-search-helper_old/temp/pilot-samtec-20261118')
candidate=base/'compiled-candidate-1/repo'
qa=json.loads((here.parent/'pilot-samtec-recipe-20261118/INDEPENDENT_RECIPE_QA.json').read_text())
assert qa['result']=='PASS_STAGED_RECIPE_QA'
assert hashlib.sha256((candidate/'src/job_search_helper/shared_boards.py').read_bytes()).hexdigest()==qa['candidate_sha256']
offline=json.loads((base/'compiled-candidate-1/offline-tests.json').read_text());assert offline['ok'] and offline['result']['exit_code']==0
sys.path.insert(0,str(here.parent/'pilot-repair-v4-20261118'));from rollout_controller import paused_database
paused_database(Path('/home/chris/job-search-helper_old/dev/wrapper-coder/tasks/tasks.sqlite3'))
out=base/'live-recipe-1';out.mkdir(exist_ok=False)
cmd=['timeout','1200','bwrap','--die-with-parent','--unshare-pid','--unshare-ipc','--unshare-uts']
for x in ('/usr','/lib','/lib64','/bin','/etc','/run/systemd/resolve'):cmd+=['--ro-bind',x,x]
cmd+=['--proc','/proc','--dev','/dev','--tmpfs','/tmp','--dir','/home','--ro-bind','/home/chris/job-search-helper_old/.venv','/venv','--ro-bind',str(candidate),'/repo','--ro-bind',str(here),'/harness','--bind',str(out),'/output','--clearenv','--setenv','PATH','/usr/bin:/bin','--setenv','HOME','/tmp','--setenv','LANG','C.UTF-8','--chdir','/repo','/venv/bin/python','-B','/harness/validate_live.py','--repo','/repo','--output','/output/result']
(out/'invocation.json').write_text(json.dumps({'command':cmd,'candidate_sha256':qa['candidate_sha256'],'production_writes':False,'normal_dispatch':True,'transport_injected':False},indent=2))
r=subprocess.run(cmd);(out/'exit.json').write_text(json.dumps({'exit_code':r.returncode}));sys.exit(r.returncode)
