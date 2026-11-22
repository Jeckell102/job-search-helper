"""Run one observation-only public check of the exact paced Amphenol candidate."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent
CANDIDATE = ROOT / 'candidate'
PYTHON = '/home/chris/job-search-helper_old/.venv/bin/python'
EVALUATOR = ROOT / 'confirm_recipe_candidate.py'
PREPARATION = '7e0ca2034fc3be3003edce8bf77375ce0f6d74ce8754ab8822dd770b1378fa0c'


def verify(path, expected):
    if (path.resolve(strict=True) != path or not path.is_file()
            or path.stat().st_nlink != 1 or sha256(path.read_bytes()).hexdigest() != expected):
        raise ValueError(f'Unexpected source custody or hash for {path.name}')


def save(path, record):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'run'))
    parser.add_argument('reviewed_evaluator_sha256')
    args = parser.parse_args()
    os.umask(0o077)
    verify(ROOT / 'PREPARED.json', PREPARATION)
    verify(EVALUATOR, args.reviewed_evaluator_sha256)
    marker = ROOT / 'PUBLIC_RUN_STARTED.json'
    if os.path.lexists(marker):
        raise ValueError('This public qualification has already been selected')
    cache = ROOT / 'unpopulated-public-bytecode'
    if os.path.lexists(cache):
        raise ValueError('Expected a fresh source-only interpreter cache path')
    if args.action == 'inspect':
        print('Exact public qualification inputs verified')
        return 0

    pins = {'preparation_sha256': PREPARATION, 'evaluator_sha256': args.reviewed_evaluator_sha256}
    save(marker, {**pins, 'started_at_utc': datetime.now(timezone.utc).isoformat()})
    stdout, stderr = ROOT / 'PUBLIC_STDOUT.log', ROOT / 'PUBLIC_STDERR.log'
    with stdout.open('xb') as out, stderr.open('xb') as err:
        try:
            worker = subprocess.run(
                [PYTHON, '-I', '-B', '-X', f'pycache_prefix={cache}', str(EVALUATOR), str(CANDIDATE), PREPARATION],
                cwd=ROOT, stdout=out, stderr=err, timeout=900, check=False,
            )
            code, state = worker.returncode, 'EVALUATOR_EXITED'
        except subprocess.TimeoutExpired:
            code, state = 124, 'EVALUATOR_TIMEOUT'
        except KeyboardInterrupt:
            code, state = 130, 'EVALUATOR_INTERRUPTED'
    result = {**pins, 'ended_at_utc': datetime.now(timezone.utc).isoformat(), 'returncode': code, 'state': state,
              'log_sha256': {path.name: sha256(path.read_bytes()).hexdigest() for path in (stdout, stderr)}}
    save(ROOT / 'PUBLIC_RUN_TERMINAL.json', result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
