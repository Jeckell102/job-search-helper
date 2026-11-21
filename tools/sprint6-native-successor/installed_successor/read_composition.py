"""Verify only saved disposable successor artifacts."""
from hashlib import sha256
import json
from pathlib import Path
import stat

ROOT = Path('/tmp/jsh-s6-successor-composition.u3xj5z8t')
FINAL = ROOT / 'run.wge725_m/installed_predecessor.q128upmr'
PINS = {'controller.py': 'b02b48c3bb10ce39b80b8ea0dfe7ffc7d6db6e12f85e4945451c5b7c9b8e7189',
        'installer.py': 'ecf2bc46541f3477c3cc0878ddfa83729ba12e691ed580895cdb51bb22a4f984',
        'gate.py': '7df4121796ce400461be9b4329984bc6f1ced83858588d3a63d4e5258d286537'}
BRIDGE = 'dev/wrapper-coder/tools/coordinator_receipt_host_bridge.py'


def sha(raw):
    return sha256(raw).hexdigest()


def pin(path):
    return sha(path.read_bytes())


def obj(path):
    return json.loads(path.read_bytes())


def check(path, value, owner):
    if value is None:
        assert not path.exists() and not path.is_symlink(), path
        return
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and pin(path) == value['sha256'], path
    assert stat.S_IMODE(info.st_mode) == int(value['mode'], 8) and (info.st_uid, info.st_gid) == tuple(owner), path


def main():
    result = obj(ROOT / 'RESULT.json')
    assert result['all_predecessor_after_bytes_restored'] and result['current_rollback_source_verified']
    old, new, project = (FINAL / name for name in ('capsule', 'successor', 'project'))
    assert {f: pin(new / f) for f in PINS} == PINS
    old_phase, new_phase, old_man, new_man = [obj(path) for path in (
        old/'controller.json', new/'controller.json', old/'manifest.json', new/'manifest.json')]
    assert old_man['schema'] == 'sprint-4-source-manifest-v1'
    assert new_man['schema'] == 'sprint-6-consolidated-source-manifest-v1'
    assert (old_phase['phase'], old_phase['target'], old_phase['receipt']['phase']) == ('RELEASED', 'INSTALLED', 'INSTALLED')
    assert (new_phase['phase'], new_phase['target'], new_phase['receipt']['phase']) == ('RELEASED', 'ROLLED_BACK', 'ROLLED_BACK')
    old_paths, new_paths = old_man['paths'], new_man['paths']
    assert len(old_paths) == 47 and len(new_paths) == 38 and BRIDGE in old_paths and BRIDGE not in new_paths
    for name, row in old_paths.items():
        check(project / name, row['after'], row['owner'])
    for name, row in new_paths.items():
        check(project / name, row['before'], row['owner'])
    assert sum(row['before'] is None for row in new_paths.values()) == 10
    assert not (new / 'candidate').exists() and (new / 'candidate-unavailable').is_dir()

    observed = obj(new/'predecessor-guard.json')['observed']
    assert obj(new/'plan.json')['predecessor_guard_sha256'] == pin(new/'predecessor-guard.json')
    assert observed['installed_continuity_sha256'] == pin(old/'protected-continuity.json')
    assert observed['installer_journal_sha256'] == pin(old/'transaction/transaction.json')
    assert observed['terminal_release']['controller_journal_sha256'] == pin(old/'controller.json')
    assert observed['restored_exchange']['journal_sha256'] == pin(old/'exchange-private/exchange.json')
    parked = project / 'src/.s4-maintenance-package'
    original_guard = observed['guard']
    for name, fpath in (('directory', parked), ('marker', parked/'__init__.py')):
        st = fpath.lstat()
        assert [st.st_dev, st.st_ino, stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid] == original_guard[name]
    assert pin(parked/'__init__.py') == original_guard['marker_sha256']
    assert new_phase['guard'] == old_phase['guard'] == original_guard['directory'][:2]
    bridge = project / BRIDGE
    assert pin(bridge) == 'efba3e77d3c4b9a9f85984ba345f58846309b301bc0b96aaad89b096e24c86ca'
    records = [json.loads(line) for line in (FINAL/'invocations.jsonl').read_bytes().splitlines()]
    assert [(item['command'][-1], item['returncode']) for item in records] == [('install',0), ('install',0), ('rollback',0)]
    assert all(not item['stderr'] for item in records)
    for item, expected in zip(records, ('INSTALLED','INSTALLED','ROLLED_BACK')):
        value = json.loads(item['stdout'])
        assert (value['phase'], value['source'], value['receipt']['phase']) == ('RELEASED', expected, expected)
    assert json.loads(records[-1]['stdout'])['receipt'] == new_phase['receipt']
    assert obj(new/'transaction/transaction.json')['phase'] == 'ROLLED_BACK'
    print(json.dumps({'result': 'ACCEPT_DISPOSABLE_LATEST_TERMINAL_ROLLBACK', 'predecessor_after_paths': len(old_paths),
                      'current_before_paths': len(new_paths), 'restored_absences': 10, 'guard_exact': True,
                      'bridge_sha256': pin(bridge), 'untouched_predecessor_reference_pins_match': True,
                      'current_terminal_sha256': pin(new/'controller.json'),
                      'current_installer_journal_sha256': pin(new/'transaction/transaction.json'),
                      'captured_invocations_sha256': pin(FINAL/'invocations.jsonl'),
                      'coordinator_result_sha256': pin(ROOT/'RESULT.json')}, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
