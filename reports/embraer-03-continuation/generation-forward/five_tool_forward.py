"""One exact five-tool forward, preserving the held #03 owner and app runtime."""
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from types import MethodType

SERVICE='wrapper-development-host.service'
SCHEMA='embraer-03-five-tool-forward-v1'
PARENT='WRAP-250158dc79'
RELEASE='REL-2a5c7bb2ad922f73cf868d15'
PREFIX='dev/wrapper-coder/tools/'
PINS={
 'coordinator.py':('f7c302326b4d7b8ed85d54f08ae3ee1ab3f89ad74629cc1ccbd0fb6d2300c8e9','400cb4e55396e0f1ab2fbccf06f7aa427927f76c43e7f6514d23e508b1a171a9'),
 'coordinator_store.py':('16c442d8019d5173f188348890fd89fe224d2c4315fde67528ed26e25478134d','028bb731ddf9cfce1ec9e228dd1ab8d6c4511aae94117e2e1243778f6b57d1f4'),
 'coordinator_inference.py':('4d94acad23e879089dee088c04826ddef4b062b77316915bf493ee2db17db968','bed0b5ef0b8d0956ef9add345cb7e35a2c4cfbb3278f96b650ec326732b92808'),
 'embraer_operator_pilot.py':('9669ae6860acff34c24af4164f4fe7e5b859da53dd8187045befb97a85d1e41a','355a0beb0e81074ed27d79d5a8ef4c87b1bb07607f9004c6782262c916798fb0'),
 'embraer_compact_prompt.py':(None,'c9d1b67b7dae3aeaf49270ffd2ff18b2b82ea9341b35760f25599f9ec5a38ef4'),
}
PATHS=tuple(PREFIX+n for n in PINS)


def canonical(value):return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
def digest(value):return sha256(canonical(value)).hexdigest()
def require(value,message):
    if not value:raise ValueError(message)


def verify_generation_transition(before,after,*,expected_generation_delta):
    """Check the exact integer epoch and every other measured snapshot field.

    The caller must expose ``control_generation`` separately from the complete
    remaining protected rows. No generation or stored state is rewritten.
    """
    require(isinstance(before,dict) and isinstance(after,dict)
        and type(expected_generation_delta) is int and expected_generation_delta in (1,2),
        'Exact orderly maintenance generation accounting is required')
    old=before.get('control_generation');new=after.get('control_generation')
    require(type(old) is int and type(new) is int and old>=0
        and new==old+expected_generation_delta,'Unexpected maintenance control generation')
    protected_before={k:v for k,v in before.items() if k!='control_generation'}
    protected_after={k:v for k,v in after.items() if k!='control_generation'}
    require(canonical(protected_before)==canonical(protected_after),
        'Protected rows or controls changed outside the exact generation transition')
    return dict(schema='embraer-03-maintenance-generation-v1',before=old,after=new,
        expected_delta=expected_generation_delta,before_snapshot_sha256=digest(before),
        after_snapshot_sha256=digest(after),protected_sha256=digest(protected_before))


def validate_scope(scope):
    require(isinstance(scope,dict) and set(scope)==set(PATHS),'Exactly five approved wrapper paths are required')
    for relative,entry in scope.items():
        before,after=PINS[Path(relative).name]
        require(isinstance(entry,dict) and set(entry)=={'before','after'} and isinstance(entry['after'],dict)
            and set(entry['after'])=={'sha256','mode','uid','gid'},'Unknown source endpoint')
        a=entry['after'];b=entry['before']
        require(a['sha256']==after and type(a['mode']) is int and a['mode'] in (0o644,0o664)
            and a['uid']==os.geteuid() and a['gid']==os.getegid(),'After image/metadata differs from approved owner')
        require((before is None and b is None) or (isinstance(b,list) and len(b)==7 and b[5]==before
            and b[2:5]==[a['mode'],a['uid'],a['gid']]),'Before image/metadata differs from approved scope')
    return scope


def tree(project,reference):
    root=Path(project)/PREFIX.rstrip('/')
    require(root.resolve(strict=True)==root and root.is_dir(),'Physical wrapper tools required')
    result={}
    for parent,dirs,files in os.walk(root,followlinks=False):
        dirs[:]=sorted(n for n in dirs if n!='__pycache__')
        for name in sorted(dirs+files):
            path=Path(parent)/name;key=path.relative_to(root).as_posix()
            if key.endswith('.pyc'):continue
            info=path.lstat()
            require(not stat.S_ISLNK(info.st_mode),'Wrapper scope contains a symlink')
            if stat.S_ISDIR(info.st_mode):result[key]=['directory',info.st_dev,info.st_ino,stat.S_IMODE(info.st_mode),info.st_uid,info.st_gid]
            else:result[key]=reference(path)
    return result


def transition_record(value):
    require(isinstance(value,dict) and set(value)=={'schema','release_id','parent_task_id','scope','snapshot',
        'snapshot_sha256','predecessor','wrapper_before_sha256'},'Unknown five-file intent')
    require(value['schema']==SCHEMA and value['release_id']==RELEASE and value['parent_task_id']==PARENT
        and value['snapshot_sha256']==digest(value['snapshot']),'Five-file intent identity differs')
    validate_scope(value['scope'])
    return value


def verify_transition(project,intent,reference,*,terminal=None):
    transition_record(intent);scope=intent['scope'];actual={}
    current=tree(project,reference)
    for relative,entry in scope.items():
        path=Path(project)/relative;name=Path(relative).name
        ref=reference(path) if os.path.lexists(path) else None
        b=entry['before'];a=entry['after']
        require(ref is None and b is None or isinstance(ref,list) and len(ref)==7
            and ref[2:5]==[a['mode'],a['uid'],a['gid']] and ref[5] in PINS[name],
            'A scoped file changed outside its exact before/after images')
        actual[relative]=ref
        if b is None:current.pop(name,None)
        else:current[name]=b
    require(digest(current)==intent['wrapper_before_sha256'],'Unrelated wrapper source changed')
    if terminal is not None:
        require(terminal.get('transition')==intent and terminal.get('current_references')==actual
            and terminal.get('status') in ('INSTALLED','ROLLED_BACK'),'Terminal five-file receipt differs')
        expected={r:(e['after']['sha256'] if terminal['status']=='INSTALLED' else PINS[Path(r).name][0]) for r,e in scope.items()}
        require(all((actual[r][5] if actual[r] else None)==pin for r,pin in expected.items()),'Terminal file selection differs')
    return actual


def install_custody_projection(window,helper_projection,authority,project,reference):
    """Chain the measured current97/helper5f witness through only these five files.

    Call once on the already-verified current window before mutation. The
    original helper archive and original app-owner checks remain in use.
    """
    original_custody=window._wrapper_custody
    original_verify=helper_projection.verify
    helper_before=original_verify()
    archive_before=reference(helper_projection.archived)
    def verify():
        intent=authority.get('intent')
        if intent is None:return original_verify()
        transition_record(intent)
        require(intent['scope'][PREFIX+'embraer_operator_pilot.py']['before']==helper_before,
            'New helper transition does not extend the exact installed helper receipt')
        require(reference(helper_projection.archived)==archive_before,'Original source-owner archive changed')
        return verify_transition(project,intent,reference,terminal=authority.get('receipt'))[PREFIX+'embraer_operator_pilot.py']
    def custody(this,status):
        if authority.get('intent') is None:return original_custody(status)
        verify()
    helper_projection.verify=verify
    window._wrapper_custody=MethodType(custody,window)
    return verify


def _remove_exact(path,expected,reference):
    require(reference(path)==expected,'Refusing removal of changed newly added prompt')
    path.unlink()
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def apply_five_tool_forward(*,project,candidates,scope,receipt_directory,approved_snapshot_sha256,
        atomic,guard,snapshot,stop,stopped,start,ready,reference,authority,rollback_only=False,
        snapshot_transition=None):
    project=Path(project);root=Path(receipt_directory);scope=validate_scope(scope)
    require(project.resolve(strict=True)==project and root.resolve(strict=True)==root
        and root.is_dir() and stat.S_IMODE(root.stat().st_mode)==0o700,'Physical private transaction required')
    require(isinstance(candidates,dict) and set(candidates)==set(PATHS)
        and all(isinstance(candidates[r],bytes) and sha256(candidates[r]).hexdigest()==scope[r]['after']['sha256'] for r in PATHS),
        'Exact accepted five-file candidate is required')
    require(snapshot_transition is None or callable(snapshot_transition),'Invalid snapshot verifier')
    intent_path=root/'intent.json';receipt_path=root/'receipt.json'
    require(not os.path.lexists(receipt_path),'Terminal installation must not be replayed')
    require(isinstance(authority,dict) and not authority.get('receipt'),'Fresh terminal authority required')
    if intent_path.exists():
        require(rollback_only,'Interrupted installation requires explicit rollback')
        saved=transition_record(json.loads(atomic._read(intent_path)[0]))
        require(saved['scope']==scope and saved['snapshot_sha256']==approved_snapshot_sha256,
            'Interrupted transition differs from the approved snapshot/scope')
        authority['intent']=saved
    with atomic._deployment_lock(project),guard() as predecessor:
        current=snapshot();require(digest(current)==approved_snapshot_sha256,'Paused #03 snapshot changed')
        backups={r:root/(Path(r).name+'.before') for r in PATHS}
        if intent_path.exists():
            require(rollback_only,'Interrupted installation requires explicit rollback')
            intent=transition_record(json.loads(atomic._read(intent_path)[0]))
            require(intent['scope']==scope and intent['snapshot']==current and intent['predecessor']==predecessor,
                'Rollback differs from exact original custody')
        else:
            require(not rollback_only,'No owned transaction to roll back')
            before_tree=tree(project,reference)
            for r in PATHS:
                path=project/r;ref=reference(path) if os.path.lexists(path) else None
                require(ref==scope[r]['before'] and not os.path.lexists(backups[r]),'Approved source before-state changed')
                if ref is not None:atomic._write_new_private(backups[r],atomic._read(path)[0])
            intent=transition_record(dict(schema=SCHEMA,release_id=RELEASE,parent_task_id=PARENT,scope=scope,
                snapshot=current,snapshot_sha256=digest(current),predecessor=predecessor,wrapper_before_sha256=digest(before_tree)))
            atomic._write_new_private(intent_path,canonical(intent))
        authority['intent']=intent
        before={r:(atomic._read(backups[r])[0] if scope[r]['before'] is not None else None) for r in PATHS}
        require(all((sha256(before[r]).hexdigest() if before[r] is not None else None)==PINS[Path(r).name][0] for r in PATHS),
            'Exact original backups changed')
        terminal=False;attempted_stop=False
        def verified_snapshot(expected_delta):
            observed=snapshot()
            if snapshot_transition is None:
                require(observed==current,'Protected database rows changed; preserve rollback checkpoint')
                return {}
            proof=snapshot_transition(current,observed,expected_generation_delta=expected_delta)
            require(isinstance(proof,dict) and bool(proof),'Snapshot verifier did not return evidence')
            return {'snapshot_verification':dict(before_snapshot_sha256=digest(current),
                after_snapshot_sha256=digest(observed),expected_generation_delta=expected_delta,
                proof=proof)}
        def replace_all(rollback):
            verify_transition(project,intent,reference)
            for r in reversed(PATHS) if rollback else PATHS:
                path=project/r;payload=before[r] if rollback else candidates[r]
                if payload is None:
                    if os.path.lexists(path):_remove_exact(path,reference(path),reference)
                else:atomic._write_atomic(path,payload,scope[r]['after']['mode'])
            verify_transition(project,intent,reference)
        try:
            attempted_stop=True;stop(SERVICE);require(stopped() is True,'Wrapper has not settled')
            replace_all(rollback_only)
            start(SERVICE)
            expected={r:(PINS[Path(r).name][0] if rollback_only else scope[r]['after']['sha256']) for r in PATHS}
            restart=ready(expected,intent)
            checked=verified_snapshot(1)
            result=dict(schema=SCHEMA,status='ROLLED_BACK' if rollback_only else 'INSTALLED',transition=intent,
                current_references=verify_transition(project,intent,reference),restart=restart,**checked)
            verify_transition(project,intent,reference,terminal=result)
            raw=canonical(result)
            try:atomic._write_new_private(receipt_path,raw)
            except OSError:
                if atomic._visible_exact(receipt_path,raw):
                    terminal=True;authority['receipt']=result
                raise
            terminal=True;authority['receipt']=result
            return result
        finally:
            if attempted_stop and not terminal:
                try:stop(SERVICE)
                except Exception:pass
                require(stopped() is True,'Uncertain wrapper state: preserve exact rollback intent')
                replace_all(True);start(SERVICE)
                restart=ready({r:PINS[Path(r).name][0] for r in PATHS},intent)
                checked=verified_snapshot(2)
                result=dict(schema=SCHEMA,status='ROLLED_BACK',transition=intent,
                    current_references=verify_transition(project,intent,reference),restart=restart,**checked)
                verify_transition(project,intent,reference,terminal=result)
                atomic._write_new_private(receipt_path,canonical(result))
                authority['receipt']=result
