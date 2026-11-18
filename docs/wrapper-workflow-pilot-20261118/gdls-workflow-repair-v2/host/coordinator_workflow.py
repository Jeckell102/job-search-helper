"""Deterministic work selection and bounded evidence packets. No model or IO writes."""
import hashlib
import json
import re
import time

from coordinator_evidence import _safe_existing, _normal_url, source_receipts, investigation_observation

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
            request_url = target['url']
            # Render only an observed successful raw destination, never a URL
            # extracted from prose. Public transport still enforces SSRF policy.
            if method == 'rendered_web_read' and target.get('identity_terms'):
                for r in reversed(relevant):
                    value = (r.get('result') or {}).get('result') or {}
                    if (r.get('name') == 'web_read' and (r.get('result') or {}).get('ok')
                            and r.get('arguments', {}).get('url') == target['url']
                            and 0 <= now - r.get('created', 0) <= 1800
                            and type(value.get('status')) is int and 200 <= value['status'] < 300
                            and _normal_url(value.get('url'))):
                        request_url = value['url']
                        break
                if any(r.get('name') == method and r.get('arguments', {}).get('url') == request_url
                       and 0 <= now - r.get('created', 0) <= 1800 for r in relevant):
                    method = None
            pending.append({'name': method, 'arguments': {'url': request_url}, 'label': target['url']})
        for target in req.get('investigation_targets', []):
            observation = investigation_observation(target, relevant, now)
            sources.append(observation)
            if observation['complete']:
                complete.append('Diagnostic observation: ' + target['url'])
            else:
                pending.append(observation['next'])
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
    eligible = [r for r in eligible if r['name'] != 'code_read' or r['id'] in valid_read_ids]
    items, used, seen = [], 0, set()
    focus = state.get('workflow', {}).get('focus_receipt_id')
    required = state.get('evidence_requirements', {}).get('required_files', [])
    def priority(r):
        path = r.get('arguments', {}).get('path', '')
        if r['id'] == focus:
            return (0, 0, -r['id'])
        if r['name'] in ('web_read', 'rendered_web_read'):
            return (1, 0, -r['id'])
        if path in required:
            # The wrapper and assertions precede oversized routing registries.
            rank = 2 if path.endswith(('/ats.py', '/company_sources.py')) else 1
            return (2, rank, required.index(path))
        return (3, 0, -r['id'])
    ranked = sorted(eligible, key=priority)
    preferred, rest, represented, web_count = [], [], set(), 0
    for r in ranked:
        path = r.get('arguments', {}).get('path')
        is_web = r['name'] in ('web_read', 'rendered_web_read')
        if r['id'] == focus or (is_web and web_count < 2) or (path in required and path not in represented):
            preferred.append(r)
            if is_web:
                web_count += 1
            if path and (r['id'] != focus or r.get('arguments', {}).get('start_line', 1) == 1):
                represented.add(path)
        else:
            rest.append(r)
    ordered = preferred + rest
    for r in ordered:
        value = r['result'].get('result') or {}
        if r['name'] == 'code_read' and r['id'] not in valid_read_ids:
            continue
        key = (r['name'], r.get('arguments', {}).get('path'), r.get('arguments', {}).get('start_line', 1), r.get('arguments', {}).get('url'))
        if key in seen:
            continue
        seen.add(key)
        body = value.get('text', value.get('diff', value.get('output', '')))
        if r.get('arguments', {}).get('path', '').endswith('/company_sources.py'):
            # Keep the assigned mapping, not the unrelated employers preceding it.
            identity = state.get('integration_identity') or {}
            ids = re.findall(r'COMP-\d+', str(identity) + ' ' + state.get('objective', ''))
            lines = str(body).splitlines()
            index = next((i for i, line in enumerate(lines) if any(cid in line for cid in ids)), None)
            if index is not None:
                body = '\n'.join(lines[max(0, index - 1):index + 12])
        # Reserve space for all essential categories within the same context cap.
        cap = min(max(500, char_limit // 8), char_limit - used)
        if cap < 200:
            break
        body = str(body)[:cap]
        items.append({'receipt_id': r['id'], 'tool': r['name'], 'arguments': {k: v for k, v in r['arguments'].items() if k not in ('old', 'new', 'content')},
                      'sha256': value.get('sha256'),
                      'retrieval': {k: value[k] for k in ('url', 'status', 'title', 'truncated') if k in value},
                      'links': [link for link in value.get('links', [])
                                if isinstance(link, dict) and any(word in (str(link.get('text', '')) + ' ' + str(link.get('url', ''))).lower()
                                                                 for word in ('job', 'career', 'position', 'vacanc'))][:12],
                      'excerpt': body, 'excerpt_truncated': len(str(value.get('text', value.get('diff', value.get('output', ''))))) > len(body)})
        used += len(body)
        if len(items) >= 8:
            break
    return items
