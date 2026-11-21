from pathlib import Path
import hashlib,json,os,stat,subprocess,time
ROOT=Path('/tmp/jsh-installed-observe-qa.20261121');PROJECT=Path('/home/chris/job-search-helper_old');STATE=PROJECT/'.state'
SOURCES=['job-search-scraper','release_admission_bootstrap.py','src/job_search_helper/runner.py','src/job_search_helper/sync_cli.py','src/job_search_helper/company_events.py','src/job_search_helper/repair_retry_status.py','src/job_search_helper/sqlite_repository.py']
FILES=['state.db','jobs.sqlite3','inventories.sqlite3','retained-sessions.sqlite3','retained-work-starts.sqlite3','scraper.lock','writer.lock','review-writeback.lock','retained-publication.lock','next-scan.json','last-scan-request.json','integration-release-journal.json']
DIRS=['company-event-bridge','operator-company-requests','operator-amphenol-observations','repair-retry','review-queue','scrape-first-pass']
def save(name,x):(ROOT/name).write_text(json.dumps(x,sort_keys=True,indent=2)+'\n')
def sig(info):return {'device':info.st_dev,'inode':info.st_ino,'mode':stat.S_IMODE(info.st_mode),'size':info.st_size,'mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns,'nlink':info.st_nlink}
def file(path):
    try:before=path.lstat()
    except FileNotFoundError:return {'absent':True}
    if not stat.S_ISREG(before.st_mode):return {'metadata':sig(before),'regular':False}
    h=hashlib.sha256()
    with path.open('rb') as f:
        opened=os.fstat(f.fileno())
        while b:=f.read(4*1024*1024):h.update(b)
        after_fd=os.fstat(f.fileno())
    after=path.lstat()
    return {'metadata':sig(after),'sha256':h.hexdigest(),'stable_read':sig(before)==sig(opened)==sig(after_fd)==sig(after)}
def snapshot():
    rows={}
    for n in FILES:
        names=[n]+([n+'-wal',n+'-shm',n+'-journal'] if n.endswith(('.db','.sqlite3')) else [])
        for name in names:rows[name]=file(STATE/name)
    for name in DIRS:
        path=STATE/name
        if not path.exists():rows[name]={'absent':True};continue
        rows[name]={'directory':True,'metadata':sig(path.lstat())}
        for p in sorted(path.rglob('*')):
            if p.is_dir() and not p.is_symlink():rows[str(p.relative_to(STATE))]={'directory':True,'metadata':sig(p.lstat())}
            else:rows[str(p.relative_to(STATE))]=file(p)
    return {'entries':rows,'state_top_names':sorted(p.name for p in STATE.iterdir()),'sources':{n:file(PROJECT/n) for n in SOURCES}}
start=time.time();before=snapshot();save('BEFORE.json',before);print('initial_snapshot_saved',flush=True)
env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1';env['PYTHONPATH']=str(ROOT/'guard')
command=['./job-search-scraper','storage','intake-observe']
execution=subprocess.run(command,cwd=PROJECT,env=env,text=True,capture_output=True,timeout=60)
(ROOT/'stdout.txt').write_text(execution.stdout);(ROOT/'stderr.txt').write_text(execution.stderr)
print('normal_command_returned',execution.returncode,flush=True)
after=snapshot();save('AFTER.json',after)
changes={k:{'before':before['entries'].get(k),'after':after['entries'].get(k)} for k in set(before['entries'])|set(after['entries']) if before['entries'].get(k)!=after['entries'].get(k)}
source_changes=[k for k in SOURCES if before['sources'][k]!=after['sources'][k]]
unstable=[k for surface in [before,after] for k,v in surface['entries'].items() if v.get('stable_read') is False]
lines=execution.stderr.splitlines();audit=[json.loads(l.removeprefix('OBSERVE_AUDIT_RESULT ')) for l in lines if l.startswith('OBSERVE_AUDIT_RESULT ')]
result={'command':command,'exit':execution.returncode,'elapsed_total_seconds':round(time.time()-start,2),'observation':json.loads(execution.stdout),'audit_loaded':lines.count('OBSERVE_AUDIT_ACTIVE')==1,'audit':audit,'physical_entries':len(before['entries']),'changed_components':changes,'changed_source_files':source_changes,'unstable_reads':unstable,'state_namespace_unchanged':before['state_top_names']==after['state_top_names'],'atime_excluded':True}
assert result['audit_loaded'] and len(audit)==1 and all(v==0 for v in audit[0].values()),result
assert execution.returncode in [0,1]
assert result['observation']['state'] in ['COMPANY_INTAKE_OBSERVATION','STATUS_SNAPSHOT_BUSY']
result['result']='PASS_INSTALLED_OBSERVE_NO_EFFECTS' if not changes and not source_changes and not unstable and result['state_namespace_unchanged'] else 'OBSERVED_WITH_CONCURRENT_CHANGE_LIMITATION'
save('RESULT.json',result);print(json.dumps({k:v for k,v in result.items() if k!='changed_components'},sort_keys=True),flush=True)
