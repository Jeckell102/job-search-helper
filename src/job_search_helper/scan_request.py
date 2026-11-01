"""Explicit one-time fresh scan requests; old checkpoints are never deleted."""
import json


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
    if (not isinstance(request, dict) or request.get('mode') != 'fresh-full-scan'
            or not isinstance(request.get('request_id'), str) or not request['request_id']
            or not isinstance(request.get('start_last', []), list)
            or not all(isinstance(value, str) for value in request.get('start_last', []))):
        raise ValueError('Invalid next-scan.json; refusing to alter scan selection.')
    found = [cycle for cycle in state.cycles() if cycle.get('start_request_id') == request['request_id']]
    if len(found) > 1:
        raise ValueError('Duplicate fresh-scan request IDs require reconciliation.')
    cycle_id = found[0]['id'] if found else engine.start_cycle(new_scan_request=request)
    path.replace(path.with_name('last-scan-request.json'))
    print(f'Fresh full scan: {cycle_id}. Previous scan checkpoints are retained; requested slow companies are queued last.', flush=True)
    return cycle_id
