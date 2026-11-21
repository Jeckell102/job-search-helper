"""Read-only audit fence for the ordinary installed observe-only command."""
import atexit,json,os,sys
counts={'write_attempts':0,'network_attempts':0,'subprocess_attempts':0,'mutation_attempts':0}
write_flags=os.O_WRONLY|os.O_RDWR|os.O_APPEND|os.O_CREAT|os.O_TRUNC
mutations={'os.remove','os.rename','os.rmdir','os.mkdir','os.chmod','os.chown','os.link','os.symlink','os.truncate','os.utime'}
def guard(event,args):
    if event=='open':
        mode=args[1] if len(args)>1 else None;flags=args[2] if len(args)>2 else 0
        if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags&write_flags):
            counts['write_attempts']+=1;raise PermissionError('observe-only write refused')
    if event.startswith('socket.'):
        counts['network_attempts']+=1;raise PermissionError('observe-only network refused')
    if event in {'subprocess.Popen','os.exec','os.posix_spawn','os.system'}:
        counts['subprocess_attempts']+=1;raise PermissionError('observe-only child process refused')
    if event in mutations:
        counts['mutation_attempts']+=1;raise PermissionError('observe-only mutation refused')
sys.addaudithook(guard)
print('OBSERVE_AUDIT_ACTIVE',file=sys.stderr,flush=True)
atexit.register(lambda:print('OBSERVE_AUDIT_RESULT '+json.dumps(counts,sort_keys=True),file=sys.stderr,flush=True))
