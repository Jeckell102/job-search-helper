"""Verify archived disposable trace and manifests without running the controller."""
from hashlib import sha256
import json
from pathlib import Path
import stat

SOURCE = Path('/tmp/jsh-s6-controller-composition.dmfenead')
ROOT = SOURCE / 'run.nu_vp78a/exact_38.cnkcqw8y'
RED = SOURCE / 'run.jdj3ark2/exact_38.eh4coh0n'
FROZEN = Path('/tmp/jsh-consolidated-scope.20261121/RESULT.json')
BRIDGE = 'dev/wrapper-coder/tools/coordinator_receipt_host_bridge.py'
HOST = 'dev/wrapper-coder/tools/host_server.py'


def digest(data):
    return sha256(data).hexdigest()


def pin(path):
    return digest(path.read_bytes())


def obj(path):
    return json.loads(path.read_bytes())


def events(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def same_endpoint(path, expected, *, owner=None, mode=True):
    if expected is None:
        assert not path.exists() and not path.is_symlink(), path
        return
    attrs = path.lstat()
    assert stat.S_ISREG(attrs.st_mode) and attrs.st_nlink == 1, path
    assert pin(path) == expected['sha256'], path
    assert not mode or stat.S_IMODE(attrs.st_mode) == int(expected['mode'], 8), path
    assert owner is None or [attrs.st_uid, attrs.st_gid] == owner, path


def aggregate(rows, side):
    result = ''
    for name, row in sorted(rows.items()):
        fields = 'ABSENT' if row[side] is None else f"{row[side]['mode']} {row[side]['sha256']}"
        result += f'{fields} {name}\n'
    return digest(result.encode())


def main():
    capsule = ROOT / 'capsule'
    frozen = obj(FROZEN)
    assert pin(FROZEN) == '09e871ceb0cc91685461294abef1651766cbebcb52b5655a63940fde74db13e3'
    manifest = obj(capsule / 'manifest.json')
    rows = manifest['paths']
    assert len(rows) == 38 and set(rows) == set(frozen['paths'])
    assert BRIDGE not in rows and not (capsule / 'candidate').exists()
    for index, (name, row) in enumerate(sorted(rows.items())):
        original = frozen['paths'][name]
        assert row['owner'] == original['after']['owner']
        for side in ('before', 'after'):
            source = original[side]
            expected = {k: source[k] for k in ('mode','sha256')} if source is not None else None
            assert row[side] == expected
            archive = capsule / 'transaction' / f'{side}-{index:02d}'
            if name == HOST:
                assert not archive.exists()
                same_endpoint(capsule / f'wrapper-host-{side}.sealed', expected, mode=False)
            else:
                same_endpoint(archive, expected)
        same_endpoint(ROOT / 'project' / name, row['before'], owner=row['owner'])
        same_endpoint(capsule / 'candidate-unavailable' / name, row['after'], owner=row['owner'])
    before, after = (aggregate(rows, key) for key in ('before', 'after'))
    assert sum(row['before'] is None for row in rows.values()) == 10

    commands = events(ROOT / 'invocations.jsonl')
    assert [(c['command'][-1], c['returncode']) for c in commands] == [
        ('install', -9), ('install', 0), ('rollback', 0), ('rollback', 0)]
    assert all(not c['stderr'] for c in commands)
    assert all('systemctl' not in c['command'][0] and '/tmp/' in ' '.join(c['command']) for c in commands)
    for c, side in zip(commands[1:], ('INSTALLED', 'ROLLED_BACK', 'ROLLED_BACK')):
        outcome = json.loads(c['stdout'])
        assert outcome['phase'] == 'RELEASED' and outcome['source'] == outcome['receipt']['phase'] == side
        receipt = outcome['receipt']
        assert receipt['before_manifest_sha256'] == before and receipt['after_manifest_sha256'] == after
        assert receipt['source_manifest_sha256'] == pin(capsule / 'manifest.json') and receipt['wrapper_host_fenced']
        assert receipt['project'] == str(ROOT / 'project')
    assert commands[2]['stdout'] == commands[3]['stdout']
    journal = obj(capsule / 'controller.json')
    txn = obj(capsule / 'transaction/transaction.json')
    assert journal['phase'] == 'RELEASED' and journal['target'] == txn['phase'] == 'ROLLED_BACK'
    assert journal['receipt'] == json.loads(commands[-1]['stdout'])['receipt']
    for k, val in [('before_manifest_sha256', before), ('after_manifest_sha256', after),
                   ('source_manifest_sha256', pin(capsule / 'manifest.json'))]:
        assert txn[k] == val
    attests = events(ROOT / 'attestations.jsonl')
    assert len(attests) == len({e['nonce'] for e in attests}) == 106
    assert [e['target'] for e in attests if e['checkpoint'] == 'restored'] == ['INSTALLED', 'ROLLED_BACK']
    assert all(e['phase'] == 'RELEASING' and not e['marker_present'] and e['wrapper_active']
               for e in attests if e['checkpoint'] == 'restored')
    assert 'predecessor_guard_sha256' not in obj(capsule / 'plan.json')
    assert not (ROOT / 'project/.state/integration-release-journal.json').exists()
    assert not (capsule / 'service-hold').exists()
    assert not (ROOT / 'project/src/job_search_helper/__init__.so').exists()
    assert pin(ROOT / 'project' / BRIDGE) == 'efba3e77d3c4b9a9f85984ba345f58846309b301bc0b96aaad89b096e24c86ca'
    history = events(RED / 'invocations.jsonl')
    assert [c['returncode'] for c in history] == [-9, 0, 1]
    assert ('safe_wrapper_origins' in history[-1]['stderr']
            and 'acquiretm_membership_recipe.py' in history[-1]['stderr']
            and 'Host checker refused pre-publish' in history[-1]['stderr'])
    assert obj(RED / 'capsule/controller.json')['phase'] == 'PUBLISHING'
    assert obj(RED / 'capsule/transaction/transaction.json')['phase'] == 'ROLLED_BACK'
    assert rows['dev/wrapper-coder/tools/acquiretm_membership_recipe.py']['before'] is None
    paths = ['invocations.jsonl', 'attestations.jsonl', 'capsule/controller.json',
             'capsule/transaction/transaction.json', 'capsule/manifest.json']
    result = {'result': 'ACCEPT_DISPOSABLE_RELEASED_BOTH_DIRECTIONS', 'terminal_replay_receipt_equal': True,
              'before_aggregate': before, 'after_aggregate': after, 'archived_tool_invocations': 4,
              'verification_scope': 'SAVED_SCRATCH_ARTIFACTS_ONLY', 'corrected_trace': str(ROOT),
              'scratch_pins': {n: pin(ROOT / n) for n in paths},
              'initial_fixture_classification': 'INSTALL_RELEASED; INSTALLER_ROLLED_BACK; CONTROLLER_PUBLISHING'}
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
