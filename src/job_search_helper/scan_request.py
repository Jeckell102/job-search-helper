"""Explicit one-time fresh scan requests; old checkpoints are never deleted."""
import json


COMPANY_ONLY_MODE = "company-only"


def cycle_metadata(cycle):
    if 'Notes' not in cycle:
        return cycle
    try:
        value = json.loads(cycle.get('Notes') or '{}')
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def superseded_cycle_ids(cycles):
    result = set()
    for cycle in cycles:
        values = cycle_metadata(cycle).get('supersedes', [])
        if isinstance(values, list):
            result.update(value for value in values if isinstance(value, str))
    return result


def requested_scan(engine, state, database):
    """Consume a user-requested fresh scan only after its checkpoint is saved.

    The request ID makes a retry after interruption select the same new cycle.
    A receipt is kept for audit. With no request, the runner creates a fresh scan.
    """
    path = database.parent / 'next-scan.json'
    if not path.exists():
        return None
    request = json.loads(path.read_text())
    if (not isinstance(request, dict)
            or not isinstance(request.get('request_id'), str) or not request['request_id']
            or not isinstance(request.get('start_last', []), list)
            or not all(isinstance(value, str) for value in request.get('start_last', []))):
        raise ValueError('Invalid next-scan.json; refusing to alter scan selection.')
    mode = request.get('mode')
    if mode == 'fresh-full-scan':
        company_ids = None
    elif mode == COMPANY_ONLY_MODE:
        company_ids = request.get('company_ids')
        if (not isinstance(company_ids, list) or not company_ids
                or not all(isinstance(value, str) and value.strip() for value in company_ids)
                or len(set(company_ids)) != len(company_ids)):
            raise ValueError('Invalid company-only next-scan.json; refusing to widen scan selection.')
    else:
        raise ValueError('Invalid next-scan.json; refusing to alter scan selection.')
    found = [cycle for cycle in state.cycles() if cycle.get('start_request_id') == request['request_id']]
    if len(found) > 1:
        raise ValueError('Duplicate fresh-scan request IDs require reconciliation.')
    if found:
        cycle_id = found[0]['id']
    else:
        # The caller holds the normal scraper/writer lock.  Do not supersede a
        # normal cycle to make room for a one-company request: leave the durable
        # request in place and make the blocking cycle visible to the operator.
        blocking = _unfinished_cycle_ids(engine, state)
        if mode == COMPANY_ONLY_MODE and blocking:
            raise ValueError(
                'Company-only request is waiting for safe boundary behind unfinished cycle(s): '
                + ', '.join(sorted(blocking))
            )
        cycle_id = engine.start_cycle(company_ids=company_ids, new_scan_request=request)
    path.replace(path.with_name('last-scan-request.json'))
    if mode == COMPANY_ONLY_MODE:
        print(f'Company-only scan: {cycle_id}. Only {len(company_ids)} declared company ID(s) are queued.', flush=True)
    else:
        print(f'Fresh full scan: {cycle_id}. Previous scan checkpoints are retained; requested slow companies are queued last.', flush=True)
    return cycle_id


def _unfinished_cycle_ids(engine, state):
    """Return non-superseded local and workbook cycles that still own work."""
    local = state.cycles()
    if hasattr(engine.repo, 'read_columns'):
        remote = [row for _, row in engine.repo.read_columns(
            'Scan Cycles', ['Cycle ID', 'Cycle Status', 'Notes'])]
    else:
        remote = engine.repo.read('Scan Cycles')
    superseded = superseded_cycle_ids(local + remote)
    local_ids = {
        cycle['id'] for cycle in local
        if cycle.get('id') not in superseded
        and cycle.get('status') not in {'Complete', 'Complete with exceptions'}
    }
    remote_ids = {
        cycle['Cycle ID'] for cycle in remote
        if cycle.get('Cycle ID') not in superseded
        and cycle.get('Cycle Status') not in {'Complete', 'Complete with exceptions', '', None}
    }
    return local_ids | remote_ids
