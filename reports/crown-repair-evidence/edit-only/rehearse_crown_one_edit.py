"""Rehearse one next edit against a private copy of the settled Crown task."""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sqlite3
import sys
import time


LIVE = Path('/home/chris/job-search-helper_old/dev/wrapper-coder')
HERE = Path(__file__).resolve().parent


def rehearse():
    sys.path[:0] = [str(HERE / 'stage'), str(LIVE / 'tools'), '/home/chris/job-search-helper_old/src']
    from bounded_continuation import CROWN
    from coordinator_store import Store, task_state_digest
    from coordinator_inference import digest
    from coordinator_workspace import BATCH_SOURCE_OVERRIDE, workspace
    from crown_edit_prompt import render
    from coding_tools import SCHEMAS

    with TemporaryDirectory(prefix='jsh-crown-one-edit-') as directory:
        root = Path(directory)
        with (
            closing(sqlite3.connect((LIVE / 'tasks/tasks.sqlite3').as_uri() + '?mode=ro', uri=True)) as source,
            closing(sqlite3.connect(root / 'tasks.sqlite3')) as copy,
        ):
            source.backup(copy)
        revision = '0c48ba6bd8cb8cb50d50ffa7a5f5bfad375e624f8ed5421d0950b4ed9691e1d2'
        store = Store(root, company_revision_resolver=lambda cid: revision if cid == CROWN.company else None)
        parent = store.get(CROWN.parent)
        repair = parent['repair_provenance']
        with store.connect() as db:
            original = db.execute('SELECT state FROM tasks WHERE id=?', (CROWN.parent,)).fetchone()[0]
            old_receipts = Store._embraer_03_receipts_digest(db, CROWN.parent)
            record_sha, receipt_sha = db.execute(
                'SELECT record_sha256,receipt_sha256 FROM scrape_outcome_delivery_receipts WHERE outcome_id=?',
                (repair['outcome_id'],),
            ).fetchone()
            payload, = db.execute('SELECT payload FROM repair_intake WHERE repair_key=?', (repair['repair_key'],)).fetchone()
        now = time.time()
        auth = dict(
            schema=CROWN.schema, parent_task_id=CROWN.parent, parent_task_state_sha256=task_state_digest(parent),
            repair_key=repair['repair_key'], outcome_id=repair['outcome_id'], record_sha256=record_sha,
            receipt_sha256=receipt_sha, failure_fingerprint=json.loads(payload)['failure_fingerprint'],
            source_revision=revision, baseline_sha256=CROWN.baseline, issued_at=now,
            expires_at=parent['activated_at'] + 3600,
        )
        grant = store.authorize_embraer_03_continuation(auth, expected_control_generation=store.control_generation())
        assert grant['limits'] == CROWN.limits
        assert store.authorize_embraer_03_continuation(auth, expected_control_generation=store.control_generation()) == grant
        child = store.get(grant['task_id'])
        assert child['activated_at'] == parent['activated_at']
        baseline = LIVE / 'pilot-bases' / ('crown-' + CROWN.baseline)
        token = BATCH_SOURCE_OVERRIDE.set(baseline)
        try:
            with workspace(store, child, create=True):
                only_schema = next(s for s in SCHEMAS if s['function']['name'] == 'code_edit')
                assert len(render(root / child['id'] / 'repo', only_schema, child['manifest'])) == 2
            snap = store.activation_snapshot(child['id'])
            store.commit_activation(
                child['id'], {'status': 'QUEUED', 'stop_requested': False},
                expected_state_digest=snap['state_digest'], expected_control_generation=snap['control_generation'],
                max_calls=9, max_tokens=56000,
            )
        finally:
            BATCH_SOURCE_OVERRIDE.reset(token)
        assert store.claim_pilot(child['id'])
        session = store.start_inference_session(child['id'])
        reservation = store.reserve_inference(
            child['id'], phase='implement', prompt_digest='a' * 64, tools_digest='b' * 64,
            prompt_tokens=884, output_tokens=2000, expected_control_generation=store.control_generation(),
            session_id=session['inference_session_id'],
        )
        assert reservation['pre_counters'] == CROWN.reservation_counters
        rid = reservation['request_id']
        assert store.bind_inference_control(rid, dict(request_id=rid, request_fingerprint='c'*64, owner_generation='d'*64))
        args = dict(path=CROWN.target, sha256=parent['manifest'][CROWN.target], old='old', new='new')
        response = {
            'id': 'fixture', 'message': {'tool_calls': [{'function': {'name': 'code_edit', 'arguments': args}}]},
            'usage': {'prompt_eval_count': 884, 'eval_count': 1100, 'done_reason': 'tool_calls'},
        }
        settled = store.finalize_inference(
            rid, response,
            accepted_continuation_edit=dict(path=args['path'], sha256=args['sha256'], arguments_sha256=digest(args)),
        )
        assert settled['receipt']['status'] == 'COMPLETED'
        assert store.get(child['id'])['calls'] == 9
        assert store.get(child['id'])['activated_at'] == parent['activated_at']
        with store.connect() as db:
            assert db.execute('SELECT state FROM tasks WHERE id=?', (CROWN.parent,)).fetchone()[0] == original
            assert Store._embraer_03_receipts_digest(db, CROWN.parent) == old_receipts
        print('Exact child and single edit receipt rehearsed; parent bytes, clock and eight calls preserved.')


if __name__ == '__main__':
    rehearse()
