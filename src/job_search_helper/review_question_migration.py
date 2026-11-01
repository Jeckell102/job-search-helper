"""Explicit, audited promotion of prior third-pass questions to Opportunities.

This prepares durable delivery intent. Ordinary guarded writeback/publication
performs the changes and verifies them; this module never writes Sheet rows.
"""
from __future__ import annotations

import json
from pathlib import Path

from .review_runtime import assessment_signature, digest, encoded, identity
from .core import reconsiderations

EVENT = 'third_pass_questions_promoted'
_FIELDS = {'job_key', 'source_hash', 'expected_assessment_signature',
           'migration_id', 'user_instruction'}


def question_assessment_signature(assessment):
    """Stable assessment signature, excluding delivery and run administration."""
    return assessment_signature(assessment)


def _request(request):
    if not isinstance(request, dict) or set(request) != _FIELDS:
        raise ValueError('Promotion requires exact identity, expected assessment signature, migration ID and explicit user instruction')
    identity(request)
    if any(not isinstance(request[name], str) or not request[name].strip()
           for name in _FIELDS):
        raise ValueError('Every promotion request field must be nonblank text')
    return digest(request)


def _protected_manual(repo, key):
    if not getattr(repo, 'is_local', False):
        return False
    matches = repo.matches('Job History', {'Job Key': key})
    if len(matches) != 1:
        raise ValueError('Missing or duplicate History identity; cannot promote questions')
    return bool(repo.db.execute(
        "SELECT 1 FROM manual_choices WHERE tab='Job History' AND row_id=?",
        (matches[0][0],)).fetchone())


def promote_questions(runtime, run_id, requests, *, repo=None, lock_path=None):
    """Prepare an allowlisted set of saved third-pass manual outcomes.

    Every request is validated before any durable mutation. A stable migration
    ID makes a lost response resumable without resetting a later publication
    receipt or adding duplicate audit events. No claim ownership is required.
    """
    from .review_writeback import (history_row, opportunity_rows, plan,
                                   requires_opportunity, sheet_writer_lock)
    from .cli import get_repository, review_lock_name
    from .runner import _load_environment

    if not isinstance(requests, list) or not 1 <= len(requests) <= 100:
        raise ValueError('Promotion requires an explicit list of 1 to 100 identities')
    signatures = [_request(request) for request in requests]
    if len({identity(request) for request in requests}) != len(requests):
        raise ValueError('Duplicate promotion identity')
    if len({request['migration_id'] for request in requests}) != len(requests):
        raise ValueError('Duplicate migration ID in promotion request')
    _load_environment()
    owned_repo = repo is None
    if repo is None:
        repo = get_repository(write=False, interactive=False)
    lock_path = Path(lock_path) if lock_path is not None else runtime.queue.parent / review_lock_name()
    prepared = []
    try:
        with sheet_writer_lock(lock_path), runtime.transaction():
            # _owned renews a lease, so perform its read-only checks first.
            _, run = runtime._run(3, run_id)
            if not run or run['state'] != 'active' or run['lease_until'] <= runtime.clock():
                raise RuntimeError('Active third-pass maintenance run required')
            for request, request_signature in zip(requests, signatures):
                key, source = identity(request)
                previous_event = runtime.db.execute(
                    "SELECT detail FROM events WHERE event=? AND json_extract(detail,'$.migration_id')=? ORDER BY id LIMIT 1",
                    (EVENT, request['migration_id'])).fetchone()
                saved = runtime.db.execute(
                    'SELECT payload FROM decisions WHERE stage=3 AND job_key=? AND source_hash=?',
                    (key, source)).fetchone()
                if saved is None:
                    raise ValueError('Saved third-pass assessment required; second-pass outcomes cannot be promoted')
                result = json.loads(saved[0])
                if result.get('decision') != 'Needs Info':
                    raise ValueError('Only saved third-pass Needs Info can be promoted')
                if question_assessment_signature(result) != request['expected_assessment_signature']:
                    raise ValueError('Saved assessment signature changed; preserve and reconcile')
                if runtime.db.execute(
                    'SELECT 1 FROM conflicts WHERE stage=3 AND job_key=? AND source_hash=?',
                    (key, source)).fetchone():
                    raise ValueError('Conflicting third-pass assessment prevents promotion')
                old = history_row(repo, key)
                if old is None or old.get('Source Hash') != source:
                    raise ValueError('Missing History or changed source; cannot promote questions')
                marker = '[third-pass ' + digest([key, source])[:16] + ']'
                if marker not in str(old.get('Review Notes', '')):
                    raise ValueError('Original exact-identity third-pass marker required')
                if _protected_manual(repo, key):
                    raise ValueError('Protected manual choice supersedes the saved review')
                if str(old.get('Job Status', '')).casefold() == 'closed' or str(old.get('Reconsideration Status', '')).casefold() == 'frozen after 2' or reconsiderations(old) >= 2:
                    raise ValueError('Closed or frozen History cannot be promoted')
                matches = opportunity_rows(repo, old)
                stored = runtime.db.execute(
                    'SELECT payload FROM writeback WHERE job_key=? AND source_hash=?',
                    (key, source)).fetchone()
                prior_intent = json.loads(stored[0]) if stored else None
                publication = runtime.db.execute(
                    'SELECT * FROM review_publications WHERE stage=3 AND job_key=? AND source_hash=?',
                    (key, source)).fetchone()
                if previous_event:
                    audit = json.loads(previous_event[0])
                    if audit.get('request_signature') != request_signature or audit.get('request') != request:
                        raise ValueError('Migration ID already belongs to a different request')
                    if prior_intent != audit.get('intent') or not requires_opportunity(prior_intent or {}):
                        raise ValueError('Promoted intent changed; preserve and reconcile')
                    state = (old.get('Added to Opportunities?'), old.get('Review Status'), old.get('Decision'))
                    if state not in {('Manual Review', 'Manual Review', 'Needs Info'), ('Yes', 'Reviewed', 'Needs Info')}:
                        raise ValueError('Current manual choice or review state superseded the promotion')
                    prepared.append((request, request_signature, result, prior_intent,
                                     dict(publication) if publication else None, prior_intent, True))
                    continue
                if prior_intent is not None and (prior_intent.get('marker') != marker or
                        prior_intent.get('decision') != 'Needs Info' or
                        prior_intent.get('pass', 3) != 3):
                    raise ValueError('Existing write intent lacks exact third-pass provenance')
                if prior_intent and requires_opportunity(prior_intent):
                    raise ValueError('Questions already promoted; resume the original migration ID')
                intent = plan(runtime, repo, result, old, 3,
                              opportunity_matches=matches, authorized_manual_conversion=True)
                if not requires_opportunity(intent) or intent.get('marker') != marker:
                    raise ValueError('Promotion must create guarded third-pass Opportunity intent')
                prepared.append((request, request_signature, result, prior_intent,
                                 dict(publication) if publication else None, intent, False))
            # All identities, prior receipts and plans are now validated.
            runtime._owned(3, run_id)
            for request, request_signature, result, prior_intent, publication, intent, reused in prepared:
                if reused:
                    continue
                key, source = identity(request)
                audit = {'migration_id': request['migration_id'], 'request': request,
                         'request_signature': request_signature, 'maintenance_run_id': run_id,
                         'prior_assessment': result, 'prior_intent': prior_intent,
                         'prior_publication': publication, 'intent': intent}
                revised = {**result, 'writeback_status': 'Pending',
                           'writeback_detail': 'Explicit user promotion: unresolved questions require an Opportunity'}
                runtime.db.execute('UPDATE decisions SET payload=?,updated=? WHERE stage=3 AND job_key=? AND source_hash=?',
                                   (encoded(revised), runtime.clock(), key, source))
                runtime.db.execute('INSERT INTO writeback VALUES(?,?,?) ON CONFLICT(job_key,source_hash) DO UPDATE SET payload=excluded.payload',
                                   (key, source, encoded(intent)))
                runtime.db.execute('DELETE FROM review_publications WHERE stage=3 AND job_key=? AND source_hash=?', (key, source))
                runtime.event(3, key, source, EVENT, encoded(audit))
        runtime.export(3)
        runtime.checkpoint(3, run_id)
        return {'pass': 3, 'run_id': run_id, 'prepared': sum(not row[-1] for row in prepared),
                'reused': sum(row[-1] for row in prepared), 'next_action': 'WRITEBACK_REQUIRED',
                'identities': [{'job_key': row[0]['job_key'], 'source_hash': row[0]['source_hash'],
                                'migration_id': row[0]['migration_id']} for row in prepared]}
    finally:
        if owned_repo and hasattr(repo, 'close'):
            repo.close()
