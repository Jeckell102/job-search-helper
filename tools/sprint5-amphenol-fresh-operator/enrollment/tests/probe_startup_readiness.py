from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
from hashlib import sha256
import io
import json
from pathlib import Path
import shlex
import sys
from tempfile import mkdtemp
from types import ModuleType

stage = Path('/tmp/jsh-amphenol-native-two-tool.HQkjpe8m')
sys.path[:0] = [str(Path.cwd()), str(stage)]
initial = len(sys.argv) == 2 and sys.argv[1] == 'initial'
if initial:
    import arm_initial as arm
else:
    import arm_under_review as arm
import deploy_two_tool_forward as updater
import fresh_operator_enrollment_input as inputs
import fresh_pilot_environment as env
import run_native_two_tool_forward as native

arm.HERE = stage
root = Path(mkdtemp(prefix='private-app-', dir=Path.cwd()))
native.BUNDLE = root / 'historical'
native.PROJECT = root
native.PROC = root / 'proc'
native.HISTORICAL_PINS = {}
native.DESTINATION = root / 'installed'
native.DESTINATION.mkdir()
unit_path = root / native.WRAPPER
unit_path.write_text('private unit fixture')
native.UNIT_SHA = sha256(unit_path.read_bytes()).hexdigest()

@dataclass
class Policy:
    systemctl: Path = Path('/private/fake-systemctl')
    wrapper_unit_file: Path = unit_path
    maintenance_id: str = 'before'
    ancillary_process_evidence: Path = Path('/private/fake-observer')

locks = []
@contextmanager
def track(name):
    locks.append(name)
    try:
        yield
    finally:
        assert locks.pop() == name

fixture = {'pid': 10, 'manager': {}, 'loaded': {}, 'ready': True, 'calls': []}

def set_proc(pid):
    directory = native.PROC / str(pid)
    directory.mkdir(parents=True)
    (directory / 'environ').write_bytes(b'\0'.join(f'{k}={v}'.encode() for k, v in fixture['loaded'].items()))

set_proc(10)

def system(op, *args):
    assert locks == ['deployment', 'scraper']
    if op == 'show-environment':
        return '\n'.join(f'{name}={shlex.quote(value)}' for name, value in fixture['manager'].items())
    fixture['calls'].append((op, *args))
    if op == 'set-environment':
        name, value = args[0].split('=', 1)
        assert name == env.ENROLLMENT
        fixture['manager'][name] = value
    elif op == 'restart':
        assert args == (native.WRAPPER,)
        fixture.update(pid=11, loaded=dict(fixture['manager']), ready=False)
        set_proc(11)
    else:
        raise AssertionError(op)

native.system = system

def verify_listener(policy, pid, proc):
    assert locks == ['deployment', 'scraper']
    assert pid == fixture['pid']
    if not fixture['ready']:
        fixture['ready'] = True
        raise ValueError('Wrapper listener has not bound yet')

def module(name, **attrs):
    sys.modules[name] = value = ModuleType(name)
    value.__dict__.update(attrs)

module('controller', lock=lambda path: track('scraper'))
module('host_checkpoint', unit_status=lambda *a: {
    'ActiveState': 'active', 'UnitFileState': 'enabled', 'FragmentPath': str(unit_path), 'MainPID': str(fixture['pid'])},
    verify_listener=verify_listener, verify_route_drain=lambda *a: None, verify_wrapper_process=lambda p, pid, proc: pid)
module('site_policy', load_policy=lambda *a: (Policy(),))
updater._deployment_lock = lambda path: track('deployment')
native.checked = lambda *a: b''
native.verify_source_selection = lambda *a: updater.TWO_TOOL_AFTER
native.retained_task = lambda: (updater.TERMINAL_TASK_SHA256, updater.TERMINAL_RECEIPT_SHA256, 0)
native.unit_field = lambda _, field: {'ActiveState': 'inactive', 'UnitFileState': 'disabled'}[field]
request_id = 'operator-amphenol-fixture'
chosen = {name: 'private-fixture-value' for name in env.ENROLLMENT_FIELDS}
chosen['request_id'] = request_id
inputs.read_fresh_operator_enrollment = lambda **args: dict(chosen)
receipt = native.DESTINATION / arm.INSTALL_RECEIPT
modes = {updater.HOST_RELATIVE: 0o600, updater.STORE_RELATIVE: 0o644}
receipt.write_bytes(updater._canonical_json({'status': 'TWO_TOOL_FORWARD_INSTALLED',
    'paths': {path: {'before_sha256': updater.TWO_TOOL_BEFORE[path], 'after_sha256': after,
                     'mode': f'{modes[path]:04o}'} for path, after in updater.TWO_TOOL_AFTER.items()},
    'predecessor': {'receipt_sha256': updater.PREDECESSOR_RECEIPT_SHA256}}))
receipt.chmod(0o600)
owner = root / (request_id + '.enrollment.json')
sys.argv = ['arm', 'arm', '--request-id', request_id, '--installed-receipt-sha256', sha256(receipt.read_bytes()).hexdigest()]
with redirect_stdout(io.StringIO()) as captured:
    arm.main()
assert json.loads(captured.getvalue())['state'] == 'FRESH_OPERATOR_ENVIRONMENT_PREFLIGHT'
assert not owner.exists() and not fixture['calls'] and not locks
sys.argv.append('--apply')
if initial:
    try:
        arm.main()
    except ValueError as error:
        assert str(error) == 'Wrapper listener has not bound yet'
        print('actual armer failed after a single transient post-restart listener sample')
    else:
        raise AssertionError('expected initial pin to report transient startup failure')
else:
    with redirect_stdout(io.StringIO()) as captured:
        arm.main()
    result = json.loads(captured.getvalue())
    assert result['state'] == 'FRESH_OPERATOR_ENROLLED' and result['wrapper_pid'] == 11
    print('corrected armer retried readback and confirmed the new ready wrapper')
assert [call[0] for call in fixture['calls']] == ['set-environment', 'restart']
assert owner.is_file() and fixture['loaded'] == fixture['manager'] and fixture['pid'] == 11
assert fixture['ready'] and not locks
print('private owner record, exact process scope and the single restart verified')
