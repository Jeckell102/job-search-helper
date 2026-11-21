import sys,os
def guard(event,args):
    if event.startswith("socket.") or event in {"subprocess.Popen","os.exec","os.posix_spawn","os.system"}:raise AssertionError("offline only")
    if event=="open" and isinstance(args[0],(str,bytes)):
        p=os.fsdecode(args[0])
        if p.startswith("/home/chris/job-search-helper_old/"):raise AssertionError("native project forbidden")
sys.addaudithook(guard)
import pytest
raise SystemExit(pytest.main(["-q","-p","no:cacheprovider","tests"]))
