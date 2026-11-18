"""MuleLab evidence gates; receipts are observations, never live certification.

These deterministic checks establish that excerpts of assigned material were
retrieved. A receipt can contain more lines than the model's compact view; a
single file read does not prove that every assertion or routing branch was read
or understood. The checks cannot establish that an employer is authentic or that
a scraper obtained complete pagination/descriptions. Public text remains
untrusted data, and the separate live-validation/operator gate remains required.
"""
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import time
from urllib.parse import urlsplit, urlunsplit


PROTOCOL = 'docs/wrapper-development-test-protocol.md'
_PATH = re.compile(r'\b(?:src|tests|docs)/[A-Za-z0-9_./-]+\.(?:py|md|txt|json|html|xml|toml|csv)\b')
_URL = re.compile(r'https?://[^\s<>\[\]`"\']+')
_VOLATILE = {'seconds', 'render_seconds', 'elapsed', 'elapsed_seconds', 'elapsed_ms',
             'duration', 'duration_seconds', 'duration_ms', 'timestamp', 'timestamps',
             'created', 'created_at', 'fetched_at', 'retrieved_at', 'execution_location'}
_JS_SHELL = re.compile(r'(?:you\s+)?(?:need\s+to\s+)?enable\s+javascript(?:\s+to\s+(?:run|use|view)\s+this\s+(?:app|application|website|site))?|javascript\s+(?:is\s+)?(?:required|disabled)', re.I)
_CHALLENGE = re.compile(r'\b(?:verify (?:that )?you are human|just a moment|checking your browser|access denied|captcha)\b', re.I)


def manifest_digest(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def _safe_existing(root, name):
    """Read only ordinary bounded files below the allowed development folders."""
    path = PurePosixPath(name)
    if not path.parts or path.parts[0] not in ('src', 'tests', 'docs') or any(p in ('.', '..') or p.startswith('.') for p in path.parts):
        return None
    current = Path(root)
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            return None
    if current.is_file() and current.stat().st_nlink == 1 and current.stat().st_size <= 256000:
        return current
    return None


def _tree(path):
    try:
        return ast.parse(path.read_text())
    except (OSError, UnicodeError, SyntaxError):
        return None


def _constants(tree):
    result = {}
    if tree:
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        result[target.id] = node.value.value
    return result


def _normal_url(value):
    if not isinstance(value, str):
        return ''
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
            return ''
        host = parts.hostname.lower()
        if host.startswith('www.'):
            host = host[4:]
        port = parts.port
        netloc = host + (f':{port}' if port and port != (443 if parts.scheme.lower() == 'https' else 80) else '')
        return urlunsplit((parts.scheme.lower(), netloc, parts.path.rstrip('/') or '/', parts.query, ''))
    except ValueError:
        return ''


def _words(value):
    return ' '.join(re.findall(r'\w+', str(value).casefold()))


def build_requirements(objective, tests, root):
    """Freeze task-specific file/source requirements before a worker runs.

    Derivation parses source as data and never imports or evaluates repository
    code. Source targets come from the objective. A matching existing company
    repair entry can supply known alternate source URLs and identity cues.
    """
    required = list(dict.fromkeys(tests))
    for name in _PATH.findall(objective):
        if name != PROTOCOL and _safe_existing(root, name) and name not in required:
            required.append(name)
    for test in tests:
        candidate = 'src/job_search_helper/' + Path(test).stem.removeprefix('test_') + '.py'
        if _safe_existing(root, candidate) and candidate not in required:
            required.append(candidate)
        path = _safe_existing(root, test)
        tree = _tree(path) if path else None
        if tree:
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module == 'job_search_helper':
                        modules = [node.module + '.' + alias.name for alias in node.names]
                    elif node.module.startswith('job_search_helper.'):
                        modules = [node.module]
                elif isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names if alias.name.startswith('job_search_helper.')]
                for module in modules:
                    candidate = 'src/' + module.replace('.', '/') + '.py'
                    if _safe_existing(root, candidate) and candidate not in required:
                        required.append(candidate)
    if any(name.startswith('src/job_search_helper/') for name in required):
        for candidate in ('src/job_search_helper/ats.py', 'src/job_search_helper/company_sources.py'):
            if _safe_existing(root, candidate) and candidate not in required:
                required.append(candidate)
    identities, company_ids = [], set(re.findall(r'\bCOMP-\d+\b', objective))
    for name in required:
        if name.endswith(('/ats.py', '/company_sources.py')):
            continue
        path = _safe_existing(root, name)
        constants = _constants(_tree(path)) if path and path.suffix == '.py' else {}
        for key in ('COMPANY', 'COMPANY_NAME'):
            if constants.get(key) and constants[key] not in identities:
                identities.append(constants[key])
        if constants.get('COMPANY_ID'):
            company_ids.add(constants['COMPANY_ID'])
    mapping = _safe_existing(root, 'src/job_search_helper/company_sources.py')
    tree = _tree(mapping) if mapping else None
    entries = []
    if tree:
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value in company_ids:
                        try:
                            entry = ast.literal_eval(value)
                        except (ValueError, TypeError, SyntaxError):
                            continue
                        if isinstance(entry, dict):
                            entries.append(entry)
    targets = []
    for raw in _URL.findall(objective):
        url = raw.rstrip('.,;:!?)}')
        normal = _normal_url(url)
        if not normal or any(t['url'] == url for t in targets):
            continue
        aliases, cues = [url], identities[:]
        for entry in entries:
            extra_urls = entry.get('expected_urls', [])
            extra_urls = extra_urls if isinstance(extra_urls, (list, tuple)) else []
            known = [entry.get('url'), entry.get('expected_url'), *extra_urls]
            known = [u for u in known if isinstance(u, str) and _normal_url(u)]
            if normal in {_normal_url(u) for u in known}:
                aliases.extend(known)
                cues = [entry['company']] if isinstance(entry.get('company'), str) else cues
                extra_cues = entry.get('company_aliases', [])
                if isinstance(extra_cues, (list, tuple)):
                    cues.extend(c for c in extra_cues if isinstance(c, str))
        targets.append({'url': url, 'allowed_urls': list(dict.fromkeys(aliases)),
                        'identity_terms': list(dict.fromkeys(cues))})
    hints = {}
    stems = [Path(name).stem for name in required if name.startswith('src/job_search_helper/')
             and not name.endswith(('/ats.py', '/company_sources.py'))]
    for name in required:
        path = _safe_existing(root, name)
        if not path:
            continue
        try:
            lines = path.read_text().splitlines()
        except (OSError, UnicodeError):
            continue
        # Hints help the next worker find relevant excerpts; they do not claim
        # that reading one excerpt covers the entire file or its assertions.
        matches = [i for i, line in enumerate(lines, 1) if any(key in line for key in company_ids)]
        if not matches:
            matches = [i for i, line in enumerate(lines, 1) if any(stem in line for stem in stems)]
        hints[name] = list(dict.fromkeys([max(1, line - 8) for line in matches]))[:6] or [1]
    return {'version': 1, 'required_files': required, 'source_targets': targets,
            'read_hints': hints}


def _read_path(receipt):
    result = receipt.get('result') or {}
    value = result.get('result') or {}
    path = receipt.get('arguments', {}).get('path')
    if receipt.get('name') != 'code_read' or not result.get('ok') or not path or value.get('path') != path:
        return None
    if not isinstance(value.get('text'), str) or not value['text'].strip():
        return None
    return path


def _source_evidence(receipt, target):
    result = receipt.get('result') or {}
    value = result.get('result') or {}
    if receipt.get('name') not in ('web_read', 'rendered_web_read') or not result.get('ok'):
        return False
    allowed = {_normal_url(u) for u in target['allowed_urls']}
    requested = _normal_url(receipt.get('arguments', {}).get('url'))
    actual = _normal_url(value.get('url'))
    if not requested or requested not in allowed or not actual:
        return False
    status = value.get('status')
    if type(status) is not int or not 200 <= status < 300:
        return False
    text = value.get('text')
    if not isinstance(text, str) or _CHALLENGE.search(text):
        return False
    # A company title around the usual JavaScript shell is still only a shell.
    if _JS_SHELL.search(text):
        return False
    if len(text.strip()) < 25 or len(_words(text).split()) < 4:
        return False
    cues = target.get('identity_terms', [])
    if cues:
        page = ' ' + _words(str(value.get('title', '')) + ' ' + text) + ' '
        if not any(' ' + _words(cue) + ' ' in page for cue in cues if _words(cue)):
            return False
    elif actual not in allowed:
        # Without a company cue, an unrelated redirect is not task evidence.
        return False
    return True


def phase_evidence(state, receipts, current_manifest):
    """Return (satisfied, missing reason); never promote or certify a task."""
    requirements = state.get('evidence_requirements')
    if not isinstance(requirements, dict) or requirements.get('version') != 1:
        return False, 'Task evidence requirements are missing; operator must review this older assignment.'
    phase = state.get('phase')
    relevant = [r for r in receipts if r.get('phase') == phase]
    required = requirements.get('required_files', [])
    if not required:
        return False, 'No assigned source/test files were recorded.'
    if phase == 'inspect':
        read = {path for r in relevant if (path := _read_path(r)) in current_manifest
                and r['result']['result'].get('sha256') == current_manifest[path]}
        missing = [path for path in required if path not in read]
        if missing:
            return False, 'Read the current assigned files: ' + ', '.join(missing) + '.'
        missing_sources = [target['url'] for target in requirements.get('source_targets', [])
                           if not (source_receipts(target, relevant) if state.get('workflow_version') == 2
                                   else any(_source_evidence(r, target) for r in relevant))]
        if missing_sources:
            return False, ('Missing retrieved public source evidence for: ' + ', '.join(missing_sources)
                           + '. Read or render a declared source (or its recorded company mapping), with HTTP success and meaningful company text; searches and JavaScript shells do not qualify. If inaccessible, checkpoint blocked.')
        return True, ''
    if phase == 'implement':
        if not any(_read_path(r) in required for r in relevant):
            return False, 'Read an assigned source or test file during implementation.'
        required_edits = set(state.get('workflow', {}).get('required_edit_paths', []))
        edited = {r.get('arguments', {}).get('path') for r in relevant
                  if r.get('name') == 'code_edit' and (r.get('result') or {}).get('ok')}
        missing_edits = sorted(required_edits - edited)
        if missing_edits:
            return False, 'Make the required guarded edits before verification: ' + ', '.join(missing_edits) + '.'
        digest = manifest_digest(current_manifest)
        diffs = [r for r in relevant if r.get('name') == 'code_diff' and (r.get('result') or {}).get('ok')
                 and r['result'].get('source_manifest_sha256') == digest
                 and r['result'].get('source_unchanged_during_diff') is True]
        if not diffs:
            return False, 'Inspect a successful diff of the current files after the last edit.'
        if state.get('mode') == 'develop' and not any(
                str((r['result'].get('result') or {}).get('diff', '')).strip()
                or (r['result'].get('result') or {}).get('new_files') for r in diffs):
            return False, 'No development change exists. Make the bounded repair and add its regression test before verification.'
        return True, ''
    return False, 'Evidence gate is only defined for inspection and implementation.'


def source_receipts(target, receipts, now=None):
    """Return provenance IDs for fresh direct evidence or an observed redirect.

    A URL mentioned in prose never creates an alias. Linking requires a successful
    retrieval starting at an allowed URL, its actual destination, and a successful
    company-scoped rendered/read result requested at that exact destination.
    Public observations expire after 30 minutes, even within the same task.
    """
    now = time.time() if now is None else now
    fresh = [r for r in receipts if isinstance(r.get('created'), (float, int))
             and 0 <= now - r['created'] <= 1800 and (r.get('result') or {}).get('ok')]
    for r in reversed(fresh):
        if _source_evidence(r, target):
            return [r['id']]
    allowed = {_normal_url(u) for u in target['allowed_urls']}
    for observation in reversed(fresh):
        value = observation['result'].get('result') or {}
        if (observation.get('name') not in ('web_read', 'rendered_web_read')
                or _normal_url(observation.get('arguments', {}).get('url')) not in allowed
                or type(value.get('status')) is not int or not 200 <= value['status'] < 300):
            continue
        final = _normal_url(value.get('url'))
        # Identity cues are mandatory when joining separate observations.
        if not final or not target.get('identity_terms'):
            continue
        linked = dict(target, allowed_urls=[value['url']])
        for r in reversed(fresh):
            actual = _normal_url((r['result'].get('result') or {}).get('url'))
            if actual == final and _source_evidence(r, linked):
                return list(dict.fromkeys([observation['id'], r['id']]))
    return []


def _stable(value, *, test_output=False):
    if isinstance(value, dict):
        return {k: _stable(v, test_output=test_output and k == 'output')
                for k, v in value.items() if k not in _VOLATILE}
    if isinstance(value, list):
        return [_stable(v, test_output=test_output) for v in value]
    if isinstance(value, str) and test_output:
        value = re.sub(r'\x1b\[[0-9;]*m', '', value)
        value = re.sub(r'\bin \d+(?:\.\d+)?(?:s| seconds?)\b', 'in <duration>', value)
        value = re.sub(r'(?m)^(Ran \d+ tests? in )\d+(?:\.\d+)?s$', r'\1<duration>', value)
        value = re.sub(r'(?m)^\d+(?:\.\d+)?s(\s+(?:setup|call|teardown)\s+)', r'<duration>\1', value)
    return value


def evidence_fingerprint(receipt):
    """Stable successful observations only; keep complete raw receipts separately."""
    result = receipt.get('result')
    if not isinstance(result, dict) or not result.get('ok'):
        return None
    stable = _stable(result)
    if receipt.get('name') == 'code_test' and isinstance(stable.get('result'), dict):
        value = stable['result']
        if isinstance(value.get('output'), str):
            value['output'] = _stable(value['output'], test_output=True)
    payload = {'name': receipt.get('name'), 'arguments': receipt.get('arguments', {}), 'result': stable}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
