"""Install only the queue command forwarder; keep rollback copy on MuleLab."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open('http://127.0.0.1:18790/api/status', timeout=8) as r:
    status = json.load(r)
if status['model_busy'] or status['foreground_waiting']:
    raise RuntimeError('Inference is busy; runtime update deferred.')
target = '/home/chris/AI/local-ai/wrapper_commands.py'
ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', 'jetson']
old = subprocess.check_output(ssh + ['cat ' + target])
if hashlib.sha256(old).hexdigest() != '282f489be0cc1215ae79482f569b277e9ac1c4ad6ab044bb922e61246d94785e':
    raise RuntimeError('Jetson forwarder changed; inspect before updating.')
archive = Path('/home/chris/job-search-helper_old/dev/wrapper-coder/repairs/persistent-workflow-20261118-115754')
(archive/'jetson-wrapper_commands-before.py').write_bytes(old)
new = (Path(__file__).parent/'jetson/wrapper_commands.py').read_bytes()
subprocess.run(ssh + ["python3 -c 'import pathlib,sys,os; p=pathlib.Path(\"/home/chris/AI/local-ai/wrapper_commands.py\"); t=p.with_suffix(\".py.new\"); t.write_bytes(sys.stdin.buffer.read()); os.chmod(t,p.stat().st_mode); t.replace(p)'"], input=new, check=True)
actual = subprocess.check_output(ssh + ['cat ' + target])
assert actual == new
subprocess.run(ssh + ['systemctl --user restart local-ai-orchestrator.service'], check=True)
print(json.dumps({'installed_sha256': hashlib.sha256(actual).hexdigest(), 'rollback': str(archive/'jetson-wrapper_commands-before.py')}))
