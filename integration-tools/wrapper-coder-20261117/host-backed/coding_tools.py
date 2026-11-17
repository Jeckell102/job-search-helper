"""Typed development tools, confined to a separate source-only checkout."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import tempfile
import threading
import time
import uuid

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE / 'repo'
VENV = BASE.parent.parent / '.venv'
LOCK = threading.Lock()
ALLOWED = {'src', 'tests', 'docs'}
EXTENSIONS = {'.py', '.md', '.txt', '.json', '.html', '.xml', '.toml', '.csv'}
MAX_FILE = 160000


def spec(name, description, props, required=()):
    return {'type': 'function', 'function': {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': props,
            'required': list(required), 'additionalProperties': False}}}
S = {'type': 'string'}
SCHEMAS = [
    spec('code_list', 'List development files matching a filename substring. Start here to locate relevant code/tests.', {'query': S}),
    spec('code_read', 'Read a source excerpt and its current SHA256. Use the hash for guarded edits.', {'path': S, 'start_line': {'type': 'integer'}}, ['path']),
    spec('code_edit', 'Replace one exact unique excerpt in an existing file after checking its SHA256. Read first.', {'path': S, 'sha256': S, 'old': S, 'new': S}, ['path', 'sha256', 'old', 'new']),
    spec('code_create', 'Create a new development source/test/document file. Never overwrites.', {'path': S, 'content': S}, ['path', 'content']),
    spec('code_test', 'Run up to eight named tests/test_*.py files offline in the Linux sandbox. No shell, network or host data access.', {'paths': S}, ['paths']),
    spec('code_diff', 'Show the current development changes against the last local commit.', {}),
    spec('code_commit', 'Commit development changes locally only when the user explicitly requests a commit. Does not push or install.', {'message': S}, ['message']),
]
NAMES = {s['function']['name'] for s in SCHEMAS}


def scope(messages):
    last = next((m['content'] for m in reversed(messages) if m.get('role') == 'user'), '').lower()
    write = bool(re.search(r'\b(edit|create|write|fix|implement|build|modify|update|add|replace|code_edit|code_create)\b', last))
    if re.search(r"\b(read.only|do not (?:edit|change|write)|don't (?:edit|change|write)|review only)\b", last):
        write = False
    names = {'code_list', 'code_read', 'code_diff'}
    if write:
        names |= {'code_edit', 'code_create', 'code_test'}
    if re.search(r'\b(test|tests|pytest|code_test)\b', last):
        names.add('code_test')
    if re.search(r'\b(commit|code_commit)\b', last) and not re.search(r"\b(do not|don't|without) commit", last):
        names.add('code_commit')
    return names


def schemas_for(messages):
    names = scope(messages)
    from assistant_tools import schemas_for as web_schemas
    return [s for s in SCHEMAS if s['function']['name'] in names] + [s for s in web_schemas(messages) if s['function']['name'] in ('web_search','web_read')]


def path_for(name, create=False):
    if not isinstance(name, str) or len(name) > 240 or '\\' in name:
        raise ValueError('Invalid path.')
    parts = PurePosixPath(name).parts
    if not parts or parts[0] not in ALLOWED or any(p in ('..', '.') or p.startswith('.') for p in parts):
        raise ValueError('Only src/, tests/, and docs/ development files are available.')
    p = ROOT
    for part in parts:
        p = p / part
        if p.is_symlink():
            raise ValueError('Symlinks are not allowed.')
    if p.suffix not in EXTENSIONS:
        raise ValueError('Unsupported source file type.')
    if p.exists() and (not p.is_file() or p.stat().st_nlink != 1 or p.stat().st_size > MAX_FILE):
        raise ValueError('Not a bounded regular source file.')
    if not create and not p.is_file():
        raise ValueError('File not found.')
    return p


def git(*args):
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(BASE), 'LANG': 'C.UTF-8',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0'}
    cmd = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgSign=false',
           '-c', 'user.name=Wrapper Developer', '-c', 'user.email=wrapper-dev@localhost',
           '-C', str(ROOT), *args]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=20)
    if r.returncode:
        raise ValueError(r.stderr[:1000])
    return r.stdout


def run_tests(paths):
    tests = paths.split()
    if not 1 <= len(tests) <= 8:
        raise ValueError('Provide one to eight test file paths separated by spaces.')
    for t in tests:
        p = path_for(t)
        if not t.startswith('tests/') or not p.name.startswith('test_') or p.suffix != '.py':
            raise ValueError('Only named tests/test_*.py files may run.')
    (BASE / 'runs').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='test-', dir=BASE / 'runs') as scratch:
        log = Path(scratch) / 'output.txt'
        unit = 'wrapper-test-' + uuid.uuid4().hex
        cmd = ['/usr/bin/systemd-run', '--user', '--quiet', '--wait', '--pipe', '--collect',
               '--unit=' + unit, '--property=MemoryMax=512M', '--property=TasksMax=24',
               '--property=RuntimeMaxSec=90', '--property=KillMode=control-group',
               '--property=NoNewPrivileges=true', '--property=UMask=0077',
               '/usr/bin/python3', '-I', str(Path(__file__).with_name('coding_sandbox.py')),
               str(ROOT), str(VENV), scratch, *tests]
        start = time.monotonic()
        with log.open('wb') as out:
            process = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True,
                env={'PATH': '/usr/bin:/bin', 'HOME': scratch, 'LANG': 'C.UTF-8',
                     'XDG_RUNTIME_DIR': '/run/user/' + str(os.getuid())})
            timed_out = False
            try:
                process.wait(timeout=95)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        with log.open('rb') as f:
            raw = f.read(12001)
        return {'exit_code': process.returncode, 'timed_out': timed_out,
                'seconds': round(time.monotonic()-start, 2), 'output': raw[:12000].decode(errors='replace'),
                'truncated': len(raw)>12000, 'sandbox': 'Landlock + seccomp; offline; separate 512 MiB/24-task/90-second cgroup'}


def execute(name, args, names):
    try:
        if name not in names:
            raise ValueError('This action is outside the current request.')
        schema = next(s['function']['parameters'] for s in SCHEMAS if s['function']['name'] == name)
        if not isinstance(args, dict) or set(args)-set(schema['properties']) or set(schema['required'])-set(args):
            raise ValueError('Missing or unexpected arguments.')
        for k, v in args.items():
            if schema['properties'][k]['type']=='string' and not isinstance(v, str) or schema['properties'][k]['type']=='integer' and type(v) is not int:
                raise ValueError('Invalid argument type.')
        with LOCK:
            result = _execute(name, args)
        return {'ok': True, 'result': result}
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        return {'ok': False, 'error': str(exc)[:1000]}


def _execute(name, args):
    if name == 'code_list':
        query = args.get('query', '').lower()
        if len(query)>100:
            raise ValueError('Query too long.')
        found=[]
        for folder in sorted(ALLOWED):
            for parent, dirs, files in os.walk(ROOT / folder, followlinks=False):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__' and not (Path(parent)/d).is_symlink()]
                for f in sorted(files):
                    p = Path(parent)/f
                    rel = p.relative_to(ROOT).as_posix()
                    if query in rel.lower() and p.suffix in EXTENSIONS and not p.is_symlink():
                        found.append(rel)
        return {'files': found[:100], 'total': len(found), 'truncated': len(found)>100}
    if name == 'code_read':
        p=path_for(args['path']); raw=p.read_bytes(); lines=raw.decode().splitlines()
        start=args.get('start_line',1)
        if start<1:
            raise ValueError('start_line must be positive.')
        excerpt='\n'.join(f'{i+start}: {line}' for i,line in enumerate(lines[start-1:start+119]))
        return {'path':args['path'],'sha256':hashlib.sha256(raw).hexdigest(), 'total_lines':len(lines),
                'text':excerpt[:10000], 'truncated':start+119<len(lines) or len(excerpt)>10000}
    if name == 'code_create':
        p=path_for(args['path'],True); raw=args['content'].encode()
        if len(raw)>MAX_FILE:
            raise ValueError('File too large.')
        p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('xb') as f:
            f.write(raw)
        return {'path':args['path'],'created':True,'sha256':hashlib.sha256(raw).hexdigest()}
    if name == 'code_edit':
        p=path_for(args['path']); raw=p.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=args['sha256']:
            raise ValueError('File changed; read it again before editing.')
        content=raw.decode(); old=args['old']
        if not old or content.count(old)!=1:
            raise ValueError('Old text must match exactly once.')
        updated=content.replace(old,args['new'],1).encode()
        if len(updated)>MAX_FILE:
            raise ValueError('File too large.')
        fd,tmp=tempfile.mkstemp(prefix='.edit-',dir=p.parent)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(updated)
            os.replace(tmp,p)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        return {'path':args['path'],'updated':True,'sha256':hashlib.sha256(updated).hexdigest()}
    if name == 'code_test':
        return run_tests(args['paths'])
    if name == 'code_diff':
        diff=git('diff','--no-ext-diff','--no-textconv','HEAD','--','src','tests','docs')
        return {'diff':diff[:12000],'truncated':len(diff)>12000,
                'new_files':git('ls-files','--others','--exclude-standard','--','src','tests','docs').splitlines()[:100]}
    if name == 'code_commit':
        message=args['message']
        if not 1<=len(message)<=200 or '\n' in message:
            raise ValueError('Use a one-line commit message up to 200 characters.')
        # Validate every candidate before staging. Tests cannot write source or .git.
        for p in git('ls-files','--modified','--others','--exclude-standard','--','src','tests','docs').splitlines():
            path_for(p)
        git('add','--','src','tests','docs')
        out=git('commit','-m',message)
        return {'output':out[:1500],'commit':git('rev-parse','HEAD').strip(),'pushed':False}
    raise ValueError('Unknown coding tool.')
