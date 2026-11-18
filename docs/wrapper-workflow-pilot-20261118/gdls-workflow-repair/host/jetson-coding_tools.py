"""Typed development tools, confined to a separate source-only checkout."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import tempfile
import threading
import time
import uuid

LOCK = threading.Lock()
ALLOWED = {'src', 'tests', 'docs'}
EXTENSIONS = {'.py', '.md', '.txt', '.json', '.html', '.xml', '.toml', '.csv'}
MAX_FILE = 160000


def spec(name, description, props, required=()):
    return {'type': 'function', 'function': {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': props,
            'required': list(required), 'additionalProperties': False}}}
S = {'type': 'string'}
SCHEMAS = [
    spec('code_list', 'List development files matching a filename substring. Start here to locate relevant code/tests.', {'query': S}),
    spec('code_read', 'Read a source excerpt and its current SHA256. Use the hash for guarded edits.', {'path': S, 'start_line': {'type': 'integer'}}, ['path']),
    spec('code_edit', 'Replace one exact unique excerpt in an existing file after checking its SHA256. Read first.', {'path': S, 'sha256': S, 'old': S, 'new': S}, ['path', 'sha256', 'old', 'new']),
    spec('code_create', 'Create a new development source/test/document file. Never overwrites.', {'path': S, 'content': S}, ['path', 'content']),
    spec('code_test', 'Run up to eight named tests/test_*.py files offline in the Linux sandbox. No shell, network or host data access.', {'paths': S}, ['paths']),
    spec('code_diff', 'Show the current development changes against the last local commit.', {}),
    spec('code_commit', 'Commit development changes locally only when the user explicitly requests a commit. Does not push or install.', {'message': S}, ['message']),
]
NAMES = {s['function']['name'] for s in SCHEMAS}
RENDERED_SCHEMA = spec(
    'rendered_web_read',
    'Render one public JavaScript page in an ephemeral browser on the scraper computer and return bounded visible text and links. Use for dynamic pages that web_read cannot inspect.',
    {'url': S},
    ['url'],
)


def scope(messages):
    from coordinator_permissions import prohibits_writes
    last = next((m['content'] for m in reversed(messages) if m.get('role') == 'user'), '').strip().casefold().replace('\u2019', "'").replace('\u2018', "'")
    # The manual chat retains explicit coding requests, but mere discussion of a
    # proposed fix is not a request to execute it. The coordinator uses its
    # structured mode instead of this compatibility parser.
    imperative = r'(?:^|[.!?;:\n]\s*|\b(?:please|then|and|can you|could you|would you|will you|want you to|need you to|help me)\s+)'
    mutation = r'(?:edit|create|write|fix|implement|build|modify|update|add|replace|code_edit|code_create)\b'
    prohibited = prohibits_writes(last)
    write = not prohibited and bool(re.search(imperative + mutation, last))
    names = {'code_list', 'code_read', 'code_diff'}
    if write:
        names |= {'code_edit', 'code_create', 'code_test'}
    if re.search(r'\b(test|tests|pytest|code_test)\b', last):
        names.add('code_test')
    if not prohibited and re.search(imperative + r'(?:commit|code_commit)\b', last) and not re.search(r"\b(do not|don't|must not|should not|never|without|no) commit", last):
        names.add('code_commit')
    return names


def schemas_for(messages):
    names = scope(messages)
    from assistant_tools import schemas_for as web_schemas
    result = [s for s in SCHEMAS if s['function']['name'] in names]
    result += [s for s in web_schemas(messages) if s['function']['name'] in ('web_search','web_read')]
    last = next((m['content'] for m in reversed(messages) if m.get('role') == 'user'), '').lower()
    if re.search(r'\b(render|rendered|javascript|browser|dynamic|rendered_web_read)\b', last) and re.search(r'https?://', last):
        result.append(RENDERED_SCHEMA)
    return result



def execute(name, args, names):
    """Forward to the scraper computer. Never execute or save locally."""
    import urllib.request
    import urllib.error
    try:
        if name not in names or name not in NAMES | {'web_read', 'web_search', 'rendered_web_read'}:
            raise ValueError('This action is outside the current request.')
        config = json.loads((Path(__file__).parent / 'config/wrapper-host.json').read_text())
        payload = json.dumps({'name': name, 'args': args, 'names': sorted(names)}).encode()
        request = urllib.request.Request('http://127.0.0.1:18789/execute', data=payload,
            headers={'Authorization': 'Bearer ' + config['token'], 'Content-Type': 'application/json'})
        # Never inherit proxy configuration for this loopback-only bridge.
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=110) as response:
            raw = response.read(100001)
        if len(raw) > 100000:
            raise ValueError('Host response exceeded its size limit.')
        result = json.loads(raw)
        if not isinstance(result, dict) or type(result.get('ok')) is not bool:
            raise ValueError('Invalid host result.')
        return result
    except (ValueError, OSError, urllib.error.URLError) as exc:
        return {'ok': False, 'error': 'Scraper-computer development tools unavailable or request failed. '
                'No Jetson fallback copy was saved. Check that the scraper computer and wrapper bridge are running. '
                + type(exc).__name__}
