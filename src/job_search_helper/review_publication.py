"""Publish saved review outcomes through the guarded, scoped Sheets outbox.

Local assessment delivery and remote publication are separate durable facts.
No queue discovery, model calls, or general scraper backlog is published here.
"""
from collections import Counter
import json
from pathlib import Path

from .repository import RepositoryError, _equivalent
from .sheet_profile import profile_schemas
from .sheets_sync import SheetsSynchronizer, unique_rows
from .review_writeback import requires_opportunity, preserved_rejection


def publication_counts(runtime, stage, run_id=None):
    """Include pre-upgrade locally Written outcomes with no publication receipt."""
    params = [stage]
    owner = ''
    if run_id is not None:
        owner = " AND json_extract(d.payload,'$.run_id')=?"
        params.append(run_id)
    controls = runtime.db.execute("SELECT value FROM metadata WHERE key='sheet_controls'").fetchone()
    local_target = controls and json.loads(controls[0]).get('delivery_target') == 'local_database'
    join = 'LEFT JOIN' if local_target else 'JOIN'
    rows = runtime.db.execute("""SELECT COALESCE(p.state,'Pending'),COUNT(*)
      FROM decisions d JOIN writeback w USING(job_key,source_hash)
      """ + join + """ review_publications p USING(stage,job_key,source_hash)
      WHERE d.stage=? AND json_extract(d.payload,'$.writeback_status')='Written'
      AND NOT EXISTS (SELECT 1 FROM conflicts c WHERE c.stage=d.stage
        AND c.job_key=d.job_key AND c.source_hash=d.source_hash)""" + owner + ' GROUP BY 1', params)
    return dict(rows)


def _receipt(runtime, stage, key, source, state, detail):
    existing=runtime.db.execute('SELECT state,detail FROM review_publications WHERE stage=? AND job_key=? AND source_hash=?',
                                (stage,key,source)).fetchone()
    if existing and (tuple(existing)==(state,detail) or
                     state=='Pending' and existing[0] in {'Written','Acknowledged','Conflict'}):
        return
    with runtime.transaction():
        # Admission/failure from a contending publisher cannot downgrade another
        # process's verified receipt written after our candidate snapshot.
        previous=runtime.db.execute('SELECT state,detail FROM review_publications WHERE stage=? AND job_key=? AND source_hash=?',
                                    (stage,key,source)).fetchone()
        if previous and (tuple(previous)==(state,detail) or
                         state=='Pending' and previous[0] in {'Written','Acknowledged','Conflict'}):
            return
        runtime.db.execute('''INSERT INTO review_publications VALUES(?,?,?,?,?,?)
          ON CONFLICT(stage,job_key,source_hash) DO UPDATE SET
          state=excluded.state,detail=excluded.detail,updated=excluded.updated''',
          (stage, key, source, state, detail, runtime.clock()))
        runtime.event(stage, key, source, 'publication_' + state, detail)


def _same_values(row, values):
    try:
        return all(_equivalent(h, row.get(h, ''), value) for h, value in values.items())
    except (ValueError, TypeError):
        # An unrelated legacy Opportunity may have a placeholder or malformed
        # URL. It cannot match an exact identity and must not stop the batch.
        return False


def _acknowledged_baseline(local, intent):
    """A pre-upgrade publisher acknowledgement is retained as historical proof."""
    matches = local.matches('Job History', {'Job Key': intent['job_key']})
    if len(matches) != 1 or matches[0][1].get('Source Hash') != intent['source_hash']:
        return False
    rid, current = matches[0]
    publication = profile_schemas(local.get_meta('sheets_profile')) or local.schemas
    values = {h: v for h, v in intent['history_values'].items()
              if h in publication['Job History']}
    base = local.baseline('Job History', rid) or {}
    if not _same_values(base, values) or intent['marker'] not in str(base.get('Review Notes', '')):
        return False
    if requires_opportunity(intent):
        opps = local.matches('Opportunities', {'Company': current['Company'],
                    'Job URL': current['Official Job URL']})
        return len(opps) == 1 and _same_values(
            local.baseline('Opportunities', opps[0][0]) or {}, intent['opportunity_values'])
    return True


def publish_reviews(runtime, stage, run_id=None, limit=25, *, identities=None,
                    local=None, remote=None, lock_path=None):
    """Retry this worker's saved review deliveries, including older Written ones.

    A receipt is Written only after live readback of the visible intent and its
    marker, including every required Opportunity. Failed attempts stay Pending.
    """
    if not 1 <= limit <= 100:
        raise ValueError('Publication limit must be between 1 and 100')
    from .cli import get_repository, get_remote_repository, state_path
    from .review_writeback import sheet_writer_lock
    owned = local is None
    try:
        if local is None:
            local = get_repository(write=True, interactive=False)
        if not getattr(local, 'is_local', False):
            return None  # Direct-Sheets writeback already verifies remote values.
        owner = " AND json_extract(d.payload,'$.run_id')=?" if run_id is not None else ''
        params = (stage, run_id) if run_id is not None else (stage,)
        candidates = runtime.db.execute('''SELECT d.job_key,d.source_hash,w.payload,p.state
          FROM decisions d JOIN writeback w USING(job_key,source_hash)
          LEFT JOIN review_publications p USING(stage,job_key,source_hash)
          WHERE d.stage=?
          AND json_extract(d.payload,'$.writeback_status')='Written'
          AND COALESCE(p.state,'Pending')='Pending'
          AND NOT EXISTS (SELECT 1 FROM conflicts c WHERE c.stage=d.stage
            AND c.job_key=d.job_key AND c.source_hash=d.source_hash)
          ''' + owner + ' ORDER BY d.updated,d.job_key', params).fetchall()
        selected = []
        counts = Counter()
        for candidate in candidates:
            key, source = candidate['job_key'], candidate['source_hash']
            if identities is not None and (key, source) not in identities:
                continue
            try:
                acknowledged = candidate['state'] is None and _acknowledged_baseline(
                    local, json.loads(candidate['payload']))
            except (ValueError, KeyError, TypeError) as exc:
                # Legacy data can contain an invalid saved URL or malformed
                # intent. Quarantine this exact review rather than preventing
                # every otherwise valid review from reaching the publisher.
                _receipt(runtime, stage, key, source, 'Conflict',
                         'Invalid saved review identity or intent: ' + str(exc))
                counts['Conflict'] += 1
                continue
            if acknowledged:
                _receipt(runtime, stage, key, source, 'Acknowledged',
                         'Existing Sheet publisher baseline acknowledges the saved review')
                continue
            _receipt(runtime, stage, key, source, 'Pending', 'Saved locally; awaiting verified Sheet publication')
            if len(selected) < limit:
                selected.append(candidate)
        report = {'pass': stage, 'run_id': run_id, 'selected': len(selected),
                  'counts': dict(counts), 'delivery_target': 'google_sheets'}
        if not selected:
            report['pending'] = publication_counts(runtime, stage, run_id).get('Pending', 0)
            return report
        # Use the single remote publisher lock, after local writeback released its
        # own lock. Never hold a SQLite transaction across network operations.
        publication_lock=Path(lock_path) if lock_path is not None else state_path().parent / 'writer.lock'
        with sheet_writer_lock(publication_lock), sheet_writer_lock(publication_lock.parent / 'review-writeback.lock'):
            if remote is None:
                remote = get_remote_repository(write=True, interactive=False,
                    schemas=profile_schemas(local.get_meta('sheets_profile')),
                    evidence_archives=False)
            sync = SheetsSynchronizer(local, remote)
            publication = sync.publication or local.schemas
            history_index = unique_rows('Job History', list(remote.read_columns(
                'Job History', ['Job Key'])))
            by_key = {row['Job Key']: number for number, row in history_index}
            opportunity_index = list(remote.read_columns('Opportunities', ['Company', 'Job URL']))
            def read_rows(tab, numbers):
                numbers = list(dict.fromkeys(numbers))
                if hasattr(remote, 'read_rows'):
                    return remote.read_rows(tab, numbers)
                return {n: remote.read_row(tab, n) for n in numbers}
            observed_history = read_rows('Job History',
                [by_key[s['job_key']] for s in selected if s['job_key'] in by_key])
            for saved in selected:
                number=by_key.get(saved['job_key'])
                if number is not None and observed_history[number].get('Job Key')!=saved['job_key']:
                    raise RepositoryError('History row moved during publication lookup')
            # The complete selected rows are loaded in bounded sparse-range
            # batches. Fresh human inputs merge before planning any delivery.
            headers = sync.pull_fields['Job History']
            sync.merge_remote('Job History', [(n, {h: row.get(h, '') for h in headers})
                for n, row in observed_history.items()], complete_snapshot=False)
            wanted_opps = set()
            for saved in selected:
                matches = local.matches('Job History', {'Job Key': saved['job_key']})
                if len(matches) == 1:
                    current = matches[0][1]
                    wanted_opps.update(n for n, row in opportunity_index if _same_values(row, {
                        'Company': current['Company'], 'Job URL': current['Official Job URL']}))
            observed_opps = read_rows('Opportunities', wanted_opps)
            for n, row in observed_opps.items():
                original = next(r for number, r in opportunity_index if number == n)
                if not _same_values(row, original):
                    raise RepositoryError('Opportunity moved during publication lookup')
            sync.merge_remote('Opportunities', list(observed_opps.items()), complete_snapshot=False)
            scope, guards, active = {}, [], []
            for saved in selected:
                key, source = saved['job_key'], saved['source_hash']
                intent = json.loads(saved['payload'])
                try:
                    matches = local.matches('Job History', {'Job Key': key})
                    if len(matches) != 1 or matches[0][1].get('Source Hash') != source:
                        raise ValueError('Local source identity changed; saved review was not published')
                    rid, current = matches[0]
                    if key not in by_key:
                        raise ValueError('Job is absent from the live Sheet; it will not be inserted')
                    if observed_history[by_key[key]].get('Job Key') != key:
                        raise RepositoryError('History row moved during publication lookup')
                    if local.db.execute("SELECT 1 FROM manual_choices WHERE tab='Job History' AND row_id=?", (rid,)).fetchone():
                        raise ValueError('A protected manual choice superseded the saved review')
                    if not _same_values(current, intent['history_values']):
                        raise ValueError('Current manual choice superseded the saved review')
                    if intent['marker'] not in str(current.get('Review Notes', '')):
                        raise ValueError('Saved review marker is missing; publication requires reconciliation')
                    if preserved_rejection(intent):
                        from .review_question_correction import guard_remote_correction
                        guard_remote_correction(intent,observed_history[by_key[key]],
                            [row for row in observed_opps.values() if _same_values(row,{'Company':current['Company'],'Job URL':current['Official Job URL']})])
                    visible = {h: v for h, v in intent['history_values'].items()
                               if h in publication['Job History']}
                    item_scope = {('Job History', rid): set(visible) | {'Review Notes'}}
                    opps = local.matches('Opportunities', {'Company': current['Company'],
                        'Job URL': current['Official Job URL']})
                    remote_opps = [(n, row) for n, row in observed_opps.items()
                        if _same_values(row, {'Company': current['Company'],
                                             'Job URL': current['Official Job URL']})]
                    if len(opps) > 1 or len(remote_opps) > 1:
                        raise ValueError('Ambiguous Opportunity identity; preserve all existing rows')
                    if requires_opportunity(intent):
                        if len(opps) != 1:
                            raise ValueError('Saved review has no unique local Opportunity')
                        oid, opportunity = opps[0]
                        if not _same_values(opportunity, intent['opportunity_values']):
                            raise ValueError('Current Opportunity differs from the saved review')
                        fields = (set(intent['opportunity_values']) if local.baseline('Opportunities', oid)
                                  else set(publication['Opportunities']))
                        item_scope[('Opportunities', oid)] = fields
                    elif intent['decision'] == 'Reject':
                        from .review_writeback import rejection_guard
                        rejection_guard([row for _, row in opps])
                        if remote_opps:
                            guards.append(rejection_guard([remote_opps[0][1]]))
                    if sync.publication is None:
                        for eid, _ in local.matches('Job Evidence', {'Job Key': key, 'Source Hash': source}):
                            item_scope[('Job Evidence', eid)] = set(local.schemas['Job Evidence'])
                    scope.update(item_scope)
                    active.append((key, source, intent, rid, current, visible))
                except ValueError as exc:
                    _receipt(runtime, stage, key, source, 'Conflict', str(exc))
                    counts['Conflict'] += 1
                except Exception as exc:
                    _receipt(runtime, stage, key, source, 'Pending', str(exc))
                    counts['Pending'] += 1
            batch_error = None
            if active:
                try:
                    # One bounded union scope covers the whole selected batch.
                    # Dependencies may require Evidence, History, Opportunity.
                    for _ in range(3):
                        sync.publish_batch(limit=100, row_scope=scope, guards=guards)
                except Exception as exc:
                    # A lost response may still have delivered everything; fresh
                    # bulk readback decides which exact intents are complete.
                    batch_error = str(exc)
                actual_history = read_rows('Job History', [by_key[item[0]] for item in active])
                accept = [item for item in active if requires_opportunity(item[2])]
                actual_opps = []
                if accept:
                    index = list(remote.read_columns('Opportunities', ['Company', 'Job URL']))
                    numbers = [n for n, row in index if any(_same_values(row, {
                        'Company': item[4]['Company'], 'Job URL': item[4]['Official Job URL']})
                        for item in accept)]
                    actual_opps = list(read_rows('Opportunities', numbers).values())
                for key, source, intent, rid, current, visible in active:
                    try:
                        actual = actual_history[by_key[key]]
                        if actual.get('Job Key') != key or not _same_values(actual, visible) or intent['marker'] not in str(actual.get('Review Notes', '')):
                            raise RepositoryError(batch_error or 'Live History readback did not verify the saved review')
                        if local.row('Job History', rid).get('Source Hash') != source:
                            raise RepositoryError('Local source changed during publication; reconcile readback')
                        if requires_opportunity(intent):
                            found = [row for row in actual_opps if _same_values(row, {
                                'Company': current['Company'], 'Job URL': current['Official Job URL']})]
                            if len(found) != 1 or not _same_values(found[0], intent['opportunity_values']):
                                raise RepositoryError(batch_error or 'Live Opportunity readback did not verify the saved review')
                        _receipt(runtime, stage, key, source, 'Written', 'Visible Sheet review and required Opportunity verified')
                        counts['Written'] += 1
                    except Exception as exc:
                        _receipt(runtime, stage, key, source, 'Pending', str(exc))
                        counts['Pending'] += 1
        report['counts'] = dict(counts)
        report['pending'] = publication_counts(runtime, stage, run_id).get('Pending', 0)
        return report
    except Exception as exc:
        # Authentication, writer contention and uncertain network responses keep
        # saved reviews and publication intent available for an ordinary retry.
        return {'pass': stage, 'run_id': run_id, 'delivery_target': 'google_sheets',
                'state': 'PUBLICATION_DEFERRED', 'detail': str(exc),
                'counts': {}, 'pending': publication_counts(runtime, stage, run_id).get('Pending', 0)}
    finally:
        if owned and local is not None and getattr(local, 'is_local', False):
            local.close()
