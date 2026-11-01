"""Deterministic, guarded Closed + Pending cleanup; never a fit assessment."""
from collections import Counter

from .core import canonicalize_url
from .repository import RepositoryError, _equivalent

MARKER = '[closed-job cleanup]'
NOTE = MARKER + ' Job Status is Closed; Pending changed to No and automatic review cleared. No fit assessment was performed.'
VALUES = {'Added to Opportunities?': 'No', 'Review Status': 'Reviewed', 'Review Started At': ''}
FIELDS = ['Company', 'Job Key', 'Job Title', 'Official Job URL', 'Source Hash',
          'Job Status', 'Added to Opportunities?', 'Review Status', 'Review Started At', 'Review Notes']


def _url(value):
    try:
        return canonicalize_url(value)
    except (TypeError, ValueError):
        return None


def opportunity_identities(repo):
    return {(str(r.get('Company', '')).strip().casefold(), _url(r.get('Job URL', '')))
            for _, r in repo.read_columns('Opportunities', ['Company', 'Job URL'])}


def close_pending_operation(row, opportunities, *, closing=False):
    """For a new closure, guard the old state and combine this with its update."""
    if str(row.get('Added to Opportunities?', '')).strip().casefold() != 'pending':
        return None
    if not closing and str(row.get('Job Status', '')).strip().casefold() != 'closed':
        return None
    if str(row.get('Review Status', '')).strip().casefold() not in ('', 'needs review'):
        return None
    if row.get('Review Started At') or not row.get('Job Key'):
        return None
    identity = (str(row.get('Company', '')).strip().casefold(), _url(row.get('Official Job URL', '')))
    if not identity[1] or identity in opportunities:
        return None
    return {'tab': 'Job History', 'identity': {'Job Key': row['Job Key']},
            'append_if_missing': False,
            'expected': {h: row[h] for h in FIELDS if h in row},
            'values': {h: v for h, v in VALUES.items() if h in row},
            'append_notes': {'Review Notes': NOTE}}


def stage_closed_pending(repo, *, limit=100, job_keys=None, include_staged=False, apply=True):
    """Save through the repository/outbox, preserving assessment and user fields."""
    if not 1 <= limit <= 100:
        raise ValueError('Closed-job cleanup limit must be 1–100.')
    fields = [h for h in FIELDS if h in repo.schemas['Job History']]
    rows = list(repo.read_columns('Job History', fields))
    counts = Counter(r.get('Job Key') for _, r in rows)
    opportunities = opportunity_identities(repo)
    operations, targets, skipped = [], [], []
    candidates = [(n, r) for n, r in rows if str(r.get('Job Status', '')).strip().casefold() == 'closed'
                  and (job_keys is None or r.get('Job Key') in job_keys)
                  and (str(r.get('Added to Opportunities?', '')).strip().casefold() == 'pending'
                       or include_staged and r.get('Added to Opportunities?') == 'No'
                       and MARKER in str(r.get('Review Notes', '')))]
    for number, row in candidates:
        if counts[row.get('Job Key')] != 1:
            skipped.append({'job_key': row.get('Job Key'), 'reason': 'Duplicate or missing identity'})
            continue
        op = close_pending_operation(row, opportunities)
        staged = (include_staged and row.get('Added to Opportunities?') == 'No'
                  and row.get('Review Status') == 'Reviewed' and MARKER in str(row.get('Review Notes', ''))
                  and (str(row.get('Company', '')).strip().casefold(), _url(row.get('Official Job URL', ''))) not in opportunities)
        if not op and not staged:
            skipped.append({'job_key': row.get('Job Key'), 'reason': 'Protected Opportunity, choice, claim or identity'})
            continue
        if len(targets) >= limit:
            continue
        targets.append((number, row))
        if op:
            operations.append(op)
    if operations and apply:
        repo.commit(operations)
    return {'changed': len(operations) if apply else 0, 'planned': len(operations), 'selected': len(targets), 'skipped': skipped,
            'remaining': max(0, len(candidates)-len(targets)-len(skipped)),
            'delivery_target': 'local_database' if getattr(repo, 'is_local', False) else 'google_sheets',
            'targets': targets}


def publish_closed_pending(local, remote, *, limit=100):
    """Caller owns writer + review locks. Publish only this cleanup's fields."""
    from .sheets_sync import SheetsSynchronizer, unique_rows
    sync = SheetsSynchronizer(local, remote)
    fields = [h for h in FIELDS if h in remote.schemas['Job History']]
    rows = unique_rows('Job History', list(remote.read_columns('Job History', fields)))
    opportunities = opportunity_identities(remote)
    eligible = [(n, row) for n, row in rows
                if str(row.get('Job Status', '')).strip().casefold() == 'closed'
                and str(row.get('Added to Opportunities?', '')).strip().casefold() == 'pending']
    selected, skipped = [], []
    for number, observed in eligible:
        if not close_pending_operation(observed, opportunities):
            skipped.append({'job_key': observed.get('Job Key'), 'reason': 'Live protected Opportunity, claim or identity'})
            continue
        matches = local.matches('Job History', {'Job Key': observed['Job Key']})
        if len(matches) != 1:
            skipped.append({'job_key': observed['Job Key'], 'reason': 'No unique local source record'})
            continue
        rid, current = matches[0]
        if any(not _equivalent(h, current.get(h, ''), observed.get(h, ''))
               for h in ('Company', 'Job Title', 'Official Job URL', 'Job Status')):
            skipped.append({'job_key': observed['Job Key'], 'reason': 'Live/local source identity or closure differs'})
            continue
        if len(selected) < limit:
            selected.append((number, observed, rid))
    if not selected:
        return {'changed': 0, 'verified': 0, 'closed_pending': len(eligible),
                'remaining': len(eligible), 'skipped': skipped, 'identities': []}
    # Merge fresh controls/notes before planning; the normal outbox tracks echoes.
    sync.merge_remote('Job History', [(n, {h: row.get(h, '') for h in
                      ('Job Key', 'Added to Opportunities?', 'Review Notes')}) for n, row, _ in selected],
                      complete_snapshot=False)
    keys = {r['Job Key'] for _, r, _ in selected}
    staged = stage_closed_pending(local, limit=limit, job_keys=keys, include_staged=True)
    accepted = {r['Job Key'] for _, r in staged['targets']}
    active = [(n, r, rid) for n, r, rid in selected if r['Job Key'] in accepted]
    scope = {('Job History', rid): set(VALUES) | {'Review Notes'} for _, _, rid in active}
    guards = [{'tab': 'Job History', 'identity': {'Job Key': row['Job Key']},
               'values': {}, 'expected': {h: row.get(h, '') for h in fields}}
              for _, row, _ in active]
    error = None
    try:
        if active:
            sync.publish_batch(limit=limit, row_scope=scope, guards=guards)
    except Exception as exc:
        error = str(exc)
    numbers = [n for n, _, _ in active]
    actual = remote.read_rows('Job History', numbers) if hasattr(remote, 'read_rows') else {
        n: remote.read_row('Job History', n) for n in numbers}
    verified, identities = 0, []
    for number, before, rid in active:
        after = actual.get(number, {})
        okay = (after.get('Job Key') == before['Job Key']
                and after.get('Job Status') == before.get('Job Status')
                and after.get('Added to Opportunities?') == 'No'
                and after.get('Review Status') == 'Reviewed'
                and MARKER in str(after.get('Review Notes', '')))
        verified += int(okay)
        identities.append({'job_key': before['Job Key'], 'source_hash': local.row('Job History', rid).get('Source Hash'),
                           'row_number': number, 'verified': okay})
    # A lost response may follow a successful write. Reconcile the saved
    # delivery attempt so our own No is not later mistaken for a manual edit.
    sync.merge_remote('Job History', [(n, {h: row[h] for h in
                      ('Job Key', 'Added to Opportunities?', 'Review Notes', 'Review Status', 'Review Started At')
                      if h in row}) for n, row in actual.items()], complete_snapshot=False)
    with local.transaction():
        local.event('closed_job_cleanup', detail={'identities': identities, 'error': error})
    return {'changed': staged['changed'], 'verified': verified, 'closed_pending': len(eligible),
            'remaining': len(eligible)-verified, 'skipped': skipped+staged['skipped'],
            'identities': identities, 'error': error, 'delivery_target': 'google_sheets'}


def execute_cleanup(args):
    from .cli import get_repository, get_remote_repository, print_json, state_path
    from .review_writeback import sheet_writer_lock
    from .sheet_profile import profile_schemas
    local = get_repository(write=args.apply, interactive=args.authenticate)
    try:
        if not args.apply:
            report = stage_closed_pending(local, limit=args.limit, apply=False)
            report.pop('targets', None)
            print_json(dict(report, dry_run=True))
            return
        with sheet_writer_lock(state_path().parent/'writer.lock'), sheet_writer_lock(state_path().parent/'review-writeback.lock'):
            if getattr(local, 'is_local', False):
                remote = get_remote_repository(write=True, interactive=args.authenticate,
                    schemas=profile_schemas(local.get_meta('sheets_profile')), evidence_archives=False)
                if remote.spreadsheet_id != local.spreadsheet_id:
                    raise RepositoryError('Closed-job cleanup workbook differs from local storage.')
                report = publish_closed_pending(local, remote, limit=args.limit)
            else:
                report = stage_closed_pending(local, limit=args.limit)
                report.pop('targets', None)
            print_json(report)
    finally:
        if getattr(local, 'is_local', False):
            local.close()
