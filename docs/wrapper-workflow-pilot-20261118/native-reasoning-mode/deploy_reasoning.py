import hashlib,json,subprocess,sys,time,urllib.request
from pathlib import Path
stage=Path(__file__).resolve().parent
base=Path('/home/chris/job-search-helper_old/dev/wrapper-coder')
sys.path.insert(0,str(stage.parent/'pilot-repair-v4-20261118'))
from rollout_controller import paused_database
paused_database(base/'tasks/tasks.sqlite3')
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def status():
 with opener.open('http://127.0.0.1:18790/api/status',timeout=10) as r:return json.load(r)
before=status();assert before['model_busy'] is False and before['foreground_waiting']==0
original=(stage/'wrapper_inference.original.py').read_bytes();updated=(stage/'wrapper_inference.py').read_bytes();compile(updated,'wrapper_inference.py','exec')
qa=json.loads((stage/'INDEPENDENT_REASONING_QA.json').read_text());assert qa['result']=='PASS_STAGED_BOUNDED_MODE_CHANGE' and qa['source_sha256']==hashlib.sha256(updated).hexdigest() and qa['original_sha256']==hashlib.sha256(original).hexdigest()
archive=Path('/home/chris/job-search-helper_old/temp/pilot-reasoning-mode-20261118');archive.mkdir(exist_ok=True)
(archive/'wrapper_inference.original.py').write_bytes(original);(archive/'wrapper_inference.py').write_bytes(updated)
remote="""import sys,json,hashlib,os,tempfile
from pathlib import Path
d=json.load(sys.stdin);p=Path('/home/chris/AI/local-ai/wrapper_inference.py')
assert hashlib.sha256(p.read_bytes()).hexdigest()==d['expected']
s=d['source'].encode();compile(s,str(p),'exec');st=p.stat()
fd,tmp=tempfile.mkstemp(prefix='.wrapper-runtime-',dir=p.parent)
try:
 with os.fdopen(fd,'wb') as f:
  f.write(s);f.flush();os.fsync(f.fileno());os.fchmod(f.fileno(),st.st_mode & 0o777);os.fchown(f.fileno(),st.st_uid,st.st_gid)
 assert hashlib.sha256(p.read_bytes()).hexdigest()==d['expected']
 os.replace(tmp,p)
 print(hashlib.sha256(p.read_bytes()).hexdigest())
finally:
 if os.path.exists(tmp):os.unlink(tmp)
"""
def replace(old,new):
 r=subprocess.run(['ssh','jetson','python3 -c '+__import__('shlex').quote(remote)],input=json.dumps({'expected':hashlib.sha256(old).hexdigest(),'source':new.decode()}),text=True,capture_output=True,timeout=30,check=True);assert r.stdout.strip()==hashlib.sha256(new).hexdigest()
def restart():subprocess.run(['ssh','jetson','systemctl --user restart local-ai-orchestrator.service'],check=True,timeout=30)
try:
 replace(original,updated)
 restart()
 for attempt in range(15):
  try:
   after=status();assert not after['model_busy'] and after['foreground_waiting']==0;break
  except Exception:
   if attempt==14:raise
   time.sleep(1)
except Exception:
 actual=subprocess.run(['ssh','jetson','sha256sum /home/chris/AI/local-ai/wrapper_inference.py'],capture_output=True,text=True,check=True,timeout=30).stdout.split()[0]
 if actual==hashlib.sha256(updated).hexdigest():replace(updated,original);restart()
 elif actual!=hashlib.sha256(original).hexdigest():raise RuntimeError('Unexpected runtime hash; preserve evidence and inspect manually')
 raise
receipt={'status':'DEPLOYED_IDLE','original_sha256':hashlib.sha256(original).hexdigest(),'installed_sha256':hashlib.sha256(updated).hexdigest(),'queue_controls_off':True,'model_busy_before':before['model_busy'],'model_busy_after':after['model_busy'],'default_think':False,'private_reasoning_excluded':True,'runtime_file':'/home/chris/AI/local-ai/wrapper_inference.py','time':time.time()}
(archive/'deployment.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
