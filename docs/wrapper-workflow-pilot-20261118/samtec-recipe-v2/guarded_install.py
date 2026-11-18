"""Review-only preparation. Default dry run; explicit --execute performs one guarded replacement."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

MAIN=Path('/home/chris/job-search-helper_old')
TARGET='src/job_search_helper/shared_boards.py'
EXPECTED_MAIN='f8ae5b420e11623e88dab381f8de19f069bad4ab6be341dff2845800b88391cf'
EXPECTED_NEW='2c08149e746b98f970d6ed98f2944dde3c51db0e3cb4b2f69c728b7a3c706847'
BASE=MAIN/'temp/pilot-samtec-20261118'
WORK=Path(__file__).resolve().parent.parent
HARNESS=WORK/'pilot-samtec-20261118'
CONTROLLER=WORK/'pilot-repair-v4-20261118'
sys.path.insert(0,str(CONTROLLER))
from rollout_controller import paused_database

def paused():
    paused_database(MAIN/'dev/wrapper-coder/tasks/tasks.sqlite3')

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def manifest(repo):return {str(p.relative_to(repo)):sha(p) for p in sorted((repo/'src').rglob('*.py'))}
def require(test,message):
    if not test:raise RuntimeError(message)
def fresh(report):
    when=datetime.fromisoformat(report['utc'].replace('Z','+00:00'))
    age=(datetime.now(timezone.utc)-when).total_seconds()
    require(0<=age<=3600,'Approval/evidence is not fresh within one hour.')
def atomic(path,data,mode):
    fd,name=tempfile.mkstemp(prefix='.samtec-install-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:
            out.write(data);out.flush();os.fsync(out.fileno());os.fchmod(out.fileno(),mode)
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(name):os.unlink(name)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--live-report',type=Path,required=True)
    parser.add_argument('--final-qa',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args();candidate=args.candidate.resolve();target=MAIN/TARGET
    paused()
    require(candidate.is_relative_to(BASE),'Candidate must be an isolated pilot repo.')
    require(not target.is_symlink() and target.is_file(),'Main target is not a regular file.')
    require(sha(target)==EXPECTED_MAIN,'Main target drift; no overwrite permitted.')
    candidate_bytes=(candidate/TARGET).read_bytes()
    require(hashlib.sha256(candidate_bytes).hexdigest()==EXPECTED_NEW,'Candidate is not the reviewed implementation.')
    current=manifest(MAIN);proposed=manifest(candidate)
    drift={key: {'main':current.get(key),'candidate':proposed.get(key)} for key in current.keys()|proposed.keys() if key!=TARGET and current.get(key)!=proposed.get(key)}
    require(not drift,'Other source files differ; revalidate on current source snapshot: '+json.dumps(drift,sort_keys=True))
    live=json.loads(args.live_report.read_text());qa=json.loads(args.final_qa.read_text())
    fresh(live);fresh(qa)
    require(live['result']=='PASS_LIVE_INTEGRITY_AND_PUBLIC_RECONCILIATION','Live validation has not passed.')
    require(live['sources']==proposed and live['sources_unchanged'] and live['stable_ids_urls'],'Live evidence source or stability mismatch.')
    require(live['public_reconciliation']['ok'] is True and len(live['passes'])==2 and all(all(p['checks'].values()) for p in live['passes']),'Live integrity gates failed.')
    require(qa['result']=='PASS_FINAL_INSTALL_QA' and qa['candidate_sha256']==EXPECTED_NEW and qa['sources']==proposed,'Final independent QA not bound to exact complete source snapshot.')
    require(qa['live_report_sha256']==sha(args.live_report),'Final QA does not bind this live report.')
    require(qa['checks'] and all(value is True for value in qa['checks'].values()),'Independent QA contains failing checks.')
    tests=qa['offline_tests']
    require(isinstance(tests,dict) and str(MAIN/'tests/test_shared_boards.py') in tests,'Required installed shared-provider tests absent.')
    for name,digest in tests.items():
        path=Path(name).resolve()
        require(path.is_relative_to((MAIN/'tests').resolve()) or path.is_relative_to(HARNESS.resolve()), 'Approved offline test is outside the fixed test roots.')
        require(path.name.startswith('test_') and path.suffix=='.py' and path.is_file() and sha(path)==digest,'Approved offline test missing or changed.')
    if not args.execute:
        print(json.dumps({'ready':True,'installed':False,'candidate_sha256':EXPECTED_NEW,'source_count':len(proposed)}));return
    output=BASE/('install-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]);output.mkdir()
    original=target.read_bytes();mode=target.stat().st_mode&0o777
    (output/'shared_boards.py.backup').write_bytes(original)
    receipt={'utc':datetime.now(timezone.utc).isoformat(),'main_before':EXPECTED_MAIN,'candidate_sha256':EXPECTED_NEW,'live_report_sha256':sha(args.live_report),'final_qa_sha256':sha(args.final_qa),'installed':False,'rollback':False,'tests':[]}
    def save():(output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    save()
    paused()
    require(manifest(MAIN)==current,'Source changed during install preflight.')
    try:
        atomic(target,candidate_bytes,mode);receipt['installed']=True;save()
        require(manifest(MAIN)==proposed,'Post-replacement source mismatch.')
        env=dict(os.environ,PYTHONPATH=str(MAIN/'src'),PYTHONDONTWRITEBYTECODE='1')
        for index,name in enumerate(tests):
            path=Path(name).resolve()
            command=[str(MAIN/'.venv/bin/python'),'-B','-m','unittest','discover','-s',str(path.parent),'-p',path.name]
            # Tests are fixed reviewed offline fixtures, never live scraping.
            result=subprocess.run(command,cwd=MAIN,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=300)
            log=output/f'test-{index+1}.log';log.write_bytes(result.stdout)
            receipt['tests'].append({'path':name,'sha256':tests[name],'exit_code':result.returncode,'log':log.name});save()
            require(result.returncode==0,'Installed offline verification failed.')
        require(manifest(MAIN)==proposed,'Source drift during installed tests.')
        receipt['result']='PASS_INSTALLED_OFFLINE_VERIFICATION';save()
    except BaseException as exc:
        receipt['error']=type(exc).__name__+': '+str(exc)
        if sha(target)==EXPECTED_NEW:
            atomic(target,original,mode);receipt['rollback']=sha(target)==EXPECTED_MAIN;receipt['installed']=False
        else:receipt['rollback_blocked']='Target changed concurrently; refuse to overwrite third-party changes.'
        receipt['result']='FAIL_INSTALL_VERIFICATION';save();raise
    print(json.dumps({'receipt':str(output/'receipt.json'),'result':receipt['result']}))

if __name__=='__main__':main()
