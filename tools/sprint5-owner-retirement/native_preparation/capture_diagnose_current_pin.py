"""Capture the current protected-state fingerprints under Freeform's real leases."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys


PREDECESSOR = Path('/home/chris/.local/state/job-search-helper-maintenance/s4-freeform-20261120-01')
SITE = Path('/tmp/jsh-retirement-reviewed-capsule.0v3Nkcga/site-source')
PROOF = SITE.parent / 'OFFLINE_PAYLOAD_PROOF.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    path = args.output
    if not path.is_absolute() or not path.is_relative_to('/tmp/jsh-retirement-pilot-control') or path.exists():
        raise ValueError('Use a fresh private observation path')
    recorded = json.loads(PROOF.read_bytes())['hashes']['site-source/protected_state.py']
    if sha256((SITE / 'protected_state.py').read_bytes()).hexdigest() != recorded:
        raise ValueError('The independently reviewed witness source changed')
    sys.path.insert(0, str(PREDECESSOR))
    from controller import Controller, installer
    sys.path.insert(0, str(SITE))
    from protected_state import DATABASES, measure_for_private_review
    old = Controller(PREDECESSOR)
    with old.restoration_terminal() as terminal:
        if terminal['source'] != 'INSTALLED':
            raise RuntimeError('Expected the already reviewed installed Freeform predecessor')
        def versions():
            result = {}
            for name in DATABASES.values():
                for suffix in ('', '-wal', '-journal'):
                    item = old.project / (name + suffix)
                    try:
                        info = item.stat()
                        result[name + suffix] = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                    except FileNotFoundError:
                        result[name + suffix] = None
            return result
        first = versions()
        try:
            facts = measure_for_private_review(old.project)
        finally:
            after = versions()
            changed = [key for key in first if first[key] != after[key]]
            if changed:
                print(json.dumps({'changed_during_observation': changed}), flush=True)
        raw = installer.encode({'schema':'protected-site-witness-v1', 'project':str(old.project), 'witness':facts})
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({'result':'CAPTURED_UNDER_EXISTING_LEASES', 'fingerprint_count':len(facts),
                          'current_pin_sha256': sha256(raw).hexdigest(), 'predecessor': terminal}, sort_keys=True))


if __name__ == '__main__':
    main()
