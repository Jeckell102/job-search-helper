"""Wait for the recorded provider floor, then execute one paced qualification."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parent
PREVIOUS = Path('/tmp/jsh-amphenol-qualification-retry.XzvXJ1qr')
ORIGINAL = Path('/tmp/jsh-fresh-amphenol-qualification.FdVVPAdT')
PYTHON = '/home/chris/job-search-helper_old/.venv/bin/python'


def pinned(path, digest):
    if path.resolve(strict=True) != path or not path.is_file():
        raise ValueError(f'Expected a physical file: {path.name}')
    data = path.read_bytes()
    if sha256(data).hexdigest() != digest:
        raise ValueError(f'Changed approved input: {path.name}')
    return data


def prepared(expected):
    record = json.loads(pinned(ROOT / 'CAPTURE_PREPARATION.json', expected))
    previous = pinned(PREVIOUS / 'QA_STDOUT.log', record['previous_429_log_sha256'])
    terminal = json.loads(previous.splitlines()[-1])
    candidate = Path(record['candidate_root'])
    bound = datetime.fromisoformat(record['not_before_utc'])
    if (terminal['stage'] != 'held_provider_rate_limit'
            or terminal['retry_not_before_utc'] != record['previous_provider_not_before_utc']
            or bound < datetime.fromisoformat(terminal['retry_not_before_utc'])
            or candidate != ORIGINAL / 'candidate' or record['detail_gap_seconds'] != 12.0):
        raise ValueError('The preparation is outside the exact held Amphenol candidate')
    pinned(candidate / 'src/job_search_helper/acquiretm.py', record['candidate_adapter_sha256'])
    pinned(ORIGINAL / 'PROPOSED_MANIFEST.json', record['manifest_file_sha256'])
    pinned(ROOT / 'confirm_recipe_candidate.py', record['paced_evaluator_sha256'])
    pinned(ROOT / 'run_once.py', record['launcher_sha256'])
    return record, candidate, bound


def save(name, evidence):
    with (ROOT / name).open('x', encoding='utf-8') as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'wait-and-run'))
    parser.add_argument('preparation_sha256')
    args = parser.parse_args()
    os.umask(0o077)
    record, candidate, bound = prepared(args.preparation_sha256)
    if args.action == 'inspect':
        print(json.dumps({'state': 'PACED_INPUTS_VERIFIED', 'not_before_utc': bound.isoformat(),
                          'detail_gap_seconds': record['detail_gap_seconds']}), flush=True)
        return 0

    print(json.dumps({'state': 'WAITING_FOR_PROVIDER_FLOOR', 'not_before_utc': bound.isoformat(),
                      'pid': os.getpid()}), flush=True)
    cancel = ROOT / 'CANCEL'
    while not cancel.exists():
        remaining = (bound - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(remaining, 15))
    if cancel.exists():
        return 130
    prepared(args.preparation_sha256)
    started = datetime.now(timezone.utc)
    if started < bound:
        raise ValueError('Provider cooldown is still in effect')
    save('RUN_STARTED.json', {'started_at_utc': started.isoformat(),
                             'preparation_sha256': args.preparation_sha256})
    if cancel.exists():
        save('RUN_TERMINAL.json', {'state': 'CANCELLED_BEFORE_PROVIDER'})
        return 130

    stdout, stderr = ROOT / 'QA_STDOUT.log', ROOT / 'QA_STDERR.log'
    try:
        with stdout.open('xb') as out, stderr.open('xb') as err:
            result = subprocess.run([PYTHON, '-I', '-B', str(ROOT / 'confirm_recipe_candidate.py'), str(candidate)],
                                    cwd=ROOT, stdout=out, stderr=err, timeout=900, check=False)
        state, code = 'EVALUATOR_EXITED', result.returncode
    except subprocess.TimeoutExpired:
        state, code = 'EVALUATOR_TIMEOUT', 124
    except KeyboardInterrupt:
        state, code = 'EVALUATOR_INTERRUPTED', 130
    evidence = {
        'state': state, 'returncode': code, 'ended_at_utc': datetime.now(timezone.utc).isoformat(),
        'preparation_sha256': args.preparation_sha256,
        'log_sha256': {path.name: sha256(path.read_bytes()).hexdigest() for path in (stdout, stderr)},
    }
    save('RUN_TERMINAL.json', evidence)
    print(json.dumps(evidence, sort_keys=True), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
