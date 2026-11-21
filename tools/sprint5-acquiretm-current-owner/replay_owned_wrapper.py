"""Recompile a source-only wrapper from an owned fixture and exact recorded choice."""
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json
import sqlite3
import sys


ROOT = Path(__file__).resolve().parent
FIXTURE = Path('/tmp/jsh-s5-owned-readback-proof.ddhsnqyo')
ORIGINAL = Path('/tmp/jsh-s5-amphenol-owned-replay/single-owned-choice-run')
APP = Path('/tmp/jsh-s5-owned-choice-readback.PpzW7IwU')
CHOICE_SHA256 = 'dc7235dbeb02bca5cecd94c0b2e652cdbfad1a6bd9a7a26fe731cf5cdb46409e'
SOURCE_SHA256 = '895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d'


def offline(event, _args):
    if event in {'socket.connect', 'socket.getaddrinfo'}:
        raise RuntimeError('Owned wrapper replay is offline')


def main():
    sys.addaudithook(offline)
    sys.path[:0] = [str(APP / 'src'), str(APP / 'dev/wrapper-coder/tools'),
                    str(ROOT / 'repair_recipe')]
    from acquiretm_membership_recipe import TARGET_PATH, build_current_owned
    from amphenol_recipe_choice_input import read_owned_choice_input

    choice_raw = (ORIGINAL / 'choice-receipt.json').read_bytes()
    assert sha256(choice_raw).hexdigest() == CHOICE_SHA256
    choice = json.loads(choice_raw)
    assert choice['status'] == 'CHOICE_ACCEPTED' and choice['calls'] == 1
    [receipt] = choice['inference']
    assert receipt['status'] == 'COMPLETED'
    coordinator_database = ORIGINAL / 'tasks/tasks.sqlite3'
    with closing(sqlite3.connect(coordinator_database.as_uri() + '?mode=ro', uri=True)) as store:
        [(status, raw)] = store.execute(
            'SELECT status,data FROM inference_receipts WHERE request_id=? AND task=?',
            (receipt['request_id'], choice['task_id'])).fetchall()
        assert status == 'COMPLETED'
        assert json.loads(raw)['response_digest'] == receipt['response_digest']

    receiver = SimpleNamespace(path=FIXTURE / 'coordinator/tasks.sqlite3')
    current = read_owned_choice_input(
        FIXTURE, receiver, outcome_id=choice['owned_binding']['outcome_id'], enabled=True)
    assert current['binding'] == choice['owned_binding']
    witness = json.loads(current['messages'][1]['content'])['W1']
    baseline = (ORIGINAL / 'queue-base' / TARGET_PATH).read_bytes()
    # The hash-pinned original receipt records acceptance only for this strategy.
    chosen = {'strategy': 'listing_membership_change', 'evidence': 'W1'}
    built = build_current_owned(baseline, chosen, current['binding']['board'],
                                witness, current['binding'])
    record = built['receipt']
    assert record['witness_sha256'] == current['binding']['witness_sha256']
    assert (ORIGINAL / 'candidate' / TARGET_PATH).read_bytes() == built['source'].encode()
    assert record['output_sha256'] == SOURCE_SHA256
    summary = {
        'result': 'ACCEPT_DISPOSABLE_CURRENT_OWNER_TO_WRAPPER_COMPOSITION',
        'outcome_id': current['binding']['outcome_id'],
        'archived_choice_sha256': CHOICE_SHA256,
        'witness_sha256': record['witness_sha256'],
        'source_sha256': SOURCE_SHA256,
        'new_model_calls': 0,
        'source_installed': False,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
