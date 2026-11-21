"""Passive proof of the native predecessor's accepted terminal target."""

from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys

STATE = Path('/home/chris/.local/state/job-search-helper-maintenance')
PROJECT = Path('/home/chris/job-search-helper_old')
CURRENT = 's4-freeform-20261120-01'
OLDER = 's4-atomic-machines-20261120-02'
EXPECTED = {
    'controller.json': '2e2c9747f0aa1c21bec1bd1fa1d796175d08ec16d9f304daf2af6a4ca21ca6c9',
    'transaction/transaction.json': '224651aa85035bda4ecf38d53d425776d7ed7f56fdbfa7bf7e1ef5476ca679e5',
    'exchange-private/exchange.json': '3d3b5f43d7e1990668ecb960f6bdb3948cac5e86d23290275af767a126c99140',
}


def identity(info):
    return [info.st_dev, info.st_ino]


def stable(info):
    return (*identity(info), info.st_ctime_ns, info.st_size)


def read(path):
    assert path.resolve() == path
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as fd:
        info = os.fstat(fd.fileno())
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        data = fd.read()
        assert stable(info) == stable(path.lstat())
        return data, info


def matches(path, spec, owner):
    if spec is None:
        return not os.path.lexists(path)
    if not path.exists():
        return False
    data, info = read(path)
    return (sha256(data).hexdigest() == spec['sha256']
            and stat.S_IMODE(info.st_mode) == int(spec['mode'], 8)
            and [info.st_uid, info.st_gid] == owner)


def predecessor(name, expected=None):
    bundle = STATE / name
    records = {}
    hashes = {}
    for path in EXPECTED:
        data, _ = read(bundle / path)
        records[path] = json.loads(data)
        hashes[path] = sha256(data).hexdigest()
    if expected is not None:
        assert hashes == expected
    controller = records['controller.json']
    installer = records['transaction/transaction.json']
    exchange = records['exchange-private/exchange.json']
    manifest, _ = read(bundle / 'manifest.json')
    manifest_hash = sha256(manifest).hexdigest()
    assert controller['phase'] == 'RELEASED' and controller['target'] == installer['phase']
    assert controller['receipt'] and controller['receipt']['phase'] == installer['phase']
    assert controller['receipt']['source_manifest_sha256'] == installer['source_manifest_sha256'] == manifest_hash
    rows = json.loads(manifest)['paths']
    endpoint = 'after' if controller['target'] == 'INSTALLED' else 'before'
    mismatches = [path for path, row in rows.items()
                  if not matches(PROJECT / path, row[endpoint], row['owner'])]
    return {
        'maintenance_id': name, 'controller_phase': controller['phase'], 'target': controller['target'],
        'restored_exchange': exchange['phase'] == 'restored' and bool(exchange['terminal_proof_sha256']),
        'terminal_source_paths': len(rows), 'current_source_mismatches': len(mismatches),
        'canonical_package_matches': identity((PROJECT / 'src/job_search_helper').lstat()) == controller['original'],
        'parked_guard_matches': identity((PROJECT / 'src/.s4-maintenance-package').lstat()) == controller['guard'],
        'terminal_hashes': hashes,
    }


current = predecessor(CURRENT, EXPECTED)
older = predecessor(OLDER)
assert current['target'] == 'INSTALLED' and current['restored_exchange']
assert current['canonical_package_matches'] and current['parked_guard_matches']
assert current['current_source_mismatches'] == 0
assert older['target'] == 'ROLLED_BACK' and older['current_source_mismatches'] > 0
assert not os.path.lexists(PROJECT / '.state/integration-release-journal.json')
result = {'current': current, 'older': older, 'production_maintenance_marker_absent': True}
assert len(sys.argv) == 2
output = Path(sys.argv[1])
assert output.parent == Path(__file__).resolve().parent
output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
