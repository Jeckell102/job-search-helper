"""Observe exact retirement-compatible MuleLab source and native terminal receipt."""
import hashlib
import json
from pathlib import Path
import stat


BUNDLE = Path('/home/chris/.local/state/job-search-helper-maintenance/s5-operator-trigger-20261121-03')
PROJECT = Path('/home/chris/job-search-helper_old')
MANIFEST = '8c73be2432fdc49485f426f5be77d6588ea1e13f7b659595f6a4dad16710c57e'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def measure():
    raw_manifest = (BUNDLE / 'manifest.json').read_bytes()
    if digest(raw_manifest) != MANIFEST:
        raise ValueError('Native release manifest changed')
    plan = json.loads(raw_manifest)
    if len(plan['paths']) != 9:
        raise ValueError('Expected the exact nine-file operator bridge release')
    journal = BUNDLE / 'controller.json'
    if not journal.is_file():
        raise ValueError('The prepared retirement release has not been invoked')
    before = journal.read_bytes()
    state = json.loads(before)
    receipt = state.get('receipt') or {}
    if (state.get('phase'), state.get('target'), receipt.get('phase')) != ('RELEASED','INSTALLED','INSTALLED'):
        raise ValueError('The retirement-compatible source has not reached terminal INSTALLED')
    for relative, change in plan['paths'].items():
        file = PROJECT / relative
        attrs = file.lstat()
        expect = change['after']
        if (not stat.S_ISREG(attrs.st_mode) or [attrs.st_uid, attrs.st_gid] != change['owner']
                or f'{stat.S_IMODE(attrs.st_mode):04o}' != expect['mode']
                or digest(file.read_bytes()) != expect['sha256']
                or fingerprint(file.lstat()) != fingerprint(attrs)):
            raise ValueError(f'Terminal file differs from reviewed release: {relative}')
    if journal.read_bytes() != before:
        raise ValueError('Native controller changed during observation')
    return {'result': 'EXACT_TERMINAL_INSTALLED_SOURCE', 'source_count': len(plan['paths']),
            'manifest_sha256': MANIFEST, 'controller_sha256': digest(before)}


if __name__ == '__main__':
    print(json.dumps(measure(), sort_keys=True))
