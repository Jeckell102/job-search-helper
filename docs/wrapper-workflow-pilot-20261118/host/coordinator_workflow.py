"""Deterministic work selection and bounded evidence packets. No model or IO writes."""
import hashlib
import json
import re
import time

from coordinator_evidence import _safe_existing, source_receipts

MAX_AUTOMATIC_ACTIONS = 80
MAX_STALL_TURNS = 3


def current_reads(receipts, manifest, phase=None):
    return [r for r in receipts if r.get('name') == 'code_read'
            and (phase is None or r.get('phase') == phase)
            and (r.get('result') or {}).get('ok')
            and (r['result'].get('result') or {}).get('sha256')
                == manifest.get(r.get('arguments', {}).get('path'), 'missing')]


def read_lines(receipt):
    value = receipt['result'].get('result') or {}
    text = value.get('text', '')
    lines = text.splitlines()
    # A character-truncated final line is not proof of having read that line.
    if len(text) >= 10000 and value.get('truncated'):
        lines = lines[:-1]
    return {int(m[1]) for line in lines if (m := re.match(r'^(\d+):', line))}


def file_steps(requirements, root):
    """Small files in full; large routing registries get bounded relevant ranges."""
    steps = []
    for name in requirements['required_files']:
        path = _safe_existing(root, name)
        if not path:
            steps.append((name, 1, 1))
            continue
        count = len(path.read_text().splitlines())
        if count <= 600:
            steps.append((name, 1, max(1, count)))
        else:
            for start in requirements.get('read_hints', {}).get(name, [1])[:6]:
                steps.append((name, start, min(start + 59, count)))
    return steps


def plan(state, receipts, manifest, root, now=None):
    """Choose one missing action. Completed work is reconstructed from receipts."""
    now = time.time() if now is None else now
    req = state['evidence_requirements']
    pending, complete = [], []
    phase = state['phase']
    reads = current_reads(receipts, manifest, phase)
    if phase == 'inspect':
        for name, start, end in file_steps(req, root):
            covered = set().union(*(read_lines(r) for r in reads if r['arguments']['path'] == name))
            missing = next((i for i in range(start, end + 1) if i not in covered), None)
            label = f'{name}:{start}-{end}'
            if missing is None:
                complete.append(label)
            else:
                pending.append({'name': 'code_read', 'arguments': {'path': name, 'start_line': missing}, 'label': label})
        relevant = [r for r in receipts if r.get('phase') == phase]
        sources = []
        for target in req.get('source_targets', []):
            ids = source_receipts(target, relevant, now)
            sources.append({'url': target['url'], 'receipt_ids': ids})
            if ids:
                complete.append(target['url'])
                continue
            # Once per transport per freshness interval; a shell triggers rendering.
            attempted = {r['name'] for r in relevant
                         if r.get('arguments', {}).get('url') == target['url']
                         and 0 <= now - r.get('created', 0) <= 1800}
            method = next((n for n in ('web_read', 'rendered_web_read') if n not in attempted), None)
            pending.append({'name': method, 'arguments': {'url': target['url']}, 'label': target['url']})
    else:
        sources = []
        if not reads:
            name = next((n for n in req['required_files'] if n.startswith('src/') and not n.endswith(('/ats.py', '/company_sources.py'))), req['required_files'][0])
            pending.append({'name': 'code_read', 'arguments': {'path': name, 'start_line': 1}, 'label': name})
        if state.get('workflow', {}).get('finish_requested') and not pending:
            pending.append({'name': 'code_diff', 'arguments': {}, 'label': 'current diff'})
    return {'complete': complete, 'remaining': [p['label'] for p in pending],
            'next': pending[0] if pending else None, 'sources': sources,
            'assignment': 'Analyze the collected evidence and decide the smallest supported repair.' if phase == 'inspect'
                          else 'Make one supported edit, request a specific missing excerpt, or checkpoint the completed repair.'}


def cached_read(receipts, args, manifest):
    for r in reversed(current_reads(receipts, manifest)):
        if (r['arguments'].get('path') == args.get('path')
                and r['arguments'].get('start_line', 1) == args.get('start_line', 1)):
            return r
    return None


def progress_key(receipts, manifest):
    """Overlapping read requests count only the additional lines, not arguments."""
    ranges = {}
    for r in current_reads(receipts, manifest):
        ranges.setdefault(r['arguments']['path'], set()).update(read_lines(r))
    web = set()
    for r in receipts:
        if r.get('name') in ('web_read', 'rendered_web_read') and (r.get('result') or {}).get('ok'):
            v = r['result'].get('result') or {}
            web.add(json.dumps({k: v.get(k) for k in ('url', 'status', 'text')}, sort_keys=True))
    data = {'manifest': manifest, 'lines': {k: sorted(v) for k, v in ranges.items()}, 'web': sorted(web)}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def packet(state, receipts, manifest, char_limit=12000):
    """Carry real excerpts into fresh context; latest requested content comes first."""
    eligible = [r for r in receipts if (r.get('result') or {}).get('ok')]
    valid_read_ids = {r['id'] for r in current_reads(receipts, manifest)}
    items, used, seen = [], 0, set()
    focus = state.get('workflow', {}).get('focus_receipt_id')
    ordered = sorted(eligible, key=lambda r: (r['id'] == focus, r['id']), reverse=True)
    for r in ordered:
        value = r['result'].get('result') or {}
        if r['name'] == 'code_read' and r['id'] not in valid_read_ids:
            continue
        key = (r['name'], r.get('arguments', {}).get('path'), r.get('arguments', {}).get('start_line', 1), r.get('arguments', {}).get('url'))
        if key in seen:
            continue
        seen.add(key)
        body = value.get('text', value.get('diff', value.get('output', '')))
        cap = min(4500 if not items else 2200, char_limit - used)
        if cap < 200:
            break
        body = str(body)[:cap]
        items.append({'receipt_id': r['id'], 'tool': r['name'], 'arguments': {k: v for k, v in r['arguments'].items() if k not in ('old', 'new', 'content')},
                      'sha256': value.get('sha256'), 'excerpt': body, 'excerpt_truncated': len(str(value.get('text', value.get('diff', value.get('output', ''))))) > len(body)})
        used += len(body)
        if len(items) >= 8:
            break
    return items
