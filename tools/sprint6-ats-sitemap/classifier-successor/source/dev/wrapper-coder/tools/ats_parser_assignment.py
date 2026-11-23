"""Exact one-function ATS job path assignment and returned edit guard."""

import ast
from hashlib import sha256
import json

from coordinator_evidence import _safe_existing


TARGET = 'src/job_search_helper/ats_job_path.py'
TEST = 'tests/test_ats_sitemap_parser.py'
WORK_ORDER = 'successfactors-ats-job-path-v1'
COMPANY_ID = 'COMP-0573'
SOURCE = 'https://jobs.atsautomation.com/'
EXAMPLES = 'tests/fixtures/ats_job_path_examples.json'
EXAMPLE_TEST = 'tests/test_ats_job_path_examples.py'
EDIT_ANCHOR = 'classify_job_path: Callable[[str], str] | None = None'
PREFIXES = ('/job/', '/PA/job/', '/Comecer/job/')


def render(root, baseline, schema):
    if schema.get('function', {}).get('name') != 'code_edit':
        raise ValueError('The ATS parser assignment offers one scoped source edit.')
    inputs = {}
    for name in (TARGET, TEST, EXAMPLE_TEST, EXAMPLES):
        path = _safe_existing(root, name)
        if path is None:
            raise ValueError(f'Assignment input is unavailable: {name}')
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != baseline.get(name):
            raise ValueError(f'Assignment input differs from its frozen baseline: {name}')
        inputs[name] = raw
    if inputs[TARGET].decode().splitlines().count(EDIT_ANCHOR) != 1:
        raise ValueError('Expected the original unimplemented classifier.')
    packet = {
        'path': TARGET, 'sha256': baseline[TARGET], 'old': EDIT_ANCHOR,
        'signature': 'def classify_job_path(path: str) -> str:',
        'rules': [
            'Replace only old with the function. The module already imports re.',
            'Input is a URL path. Accept exactly an approved prefix, one nonempty slug, a slash, '
            '4 to 24 ASCII decimal digits, and a trailing slash. Return the digit string unchanged. '
            'Raise ValueError on any other path.',
            'The host handles URLs, XML, navigation pages, duplicates and map construction.',
        ],
        'job_path_prefixes': PREFIXES,
        'examples': json.loads(inputs[EXAMPLES]),
    }
    return [
        {'role': 'system', 'content': 'Return exactly one guarded code_edit to the supplied path. Use the supplied exact anchor as old and produce working code.'},
        {'role': 'user', 'content': json.dumps(packet, separators=(',', ':'))},
    ]


def edit_arguments(response, expected):
    """Resolve the only acceptable model-returned mutation before execution."""
    message = response.get('message') if isinstance(response, dict) else None
    calls = message.get('tool_calls') if isinstance(message, dict) else None
    function = calls[0].get('function') if isinstance(calls, list) and len(calls) == 1 and isinstance(calls[0], dict) else None
    args = function.get('arguments') if isinstance(function, dict) and function.get('name') == 'code_edit' else None
    if (
        not isinstance(args, dict) or set(args) != {'path', 'sha256', 'old', 'new'}
        or not all(isinstance(value, str) for value in args.values())
        or args['path'] != TARGET or args['sha256'] != expected.get(TARGET)
        or args['old'] != EDIT_ANCHOR or not args['new'] or args['old'] == args['new']
    ):
        raise ValueError('The ATS worker did not return one exact guarded edit.')
    try:
        definitions = ast.parse(args['new']).body
    except SyntaxError as exc:
        raise ValueError('The proposed classifier is invalid Python.') from exc
    if (len(definitions) != 1 or not isinstance(definitions[0], ast.FunctionDef)
            or definitions[0].name != 'classify_job_path' or definitions[0].decorator_list):
        raise ValueError('Replace the anchor with one classify_job_path function.')
    function = definitions[0]
    params = function.args
    if ([arg.arg for arg in params.args] != ['path'] or params.posonlyargs or params.kwonlyargs
            or params.vararg or params.kwarg or params.defaults
            or any(isinstance(node, (ast.Yield, ast.YieldFrom)) for node in ast.walk(function))):
        raise ValueError('The classifier must be a synchronous single-path function.')
    return args


MAX_CALLS = 1
MAX_TOKENS = 4000
MAX_OUTPUT = 1600


def is_assignment(state):
    integration = state.get('integration') or {}
    owner = state.get('repair_provenance') or {}
    return (
        integration.get('work_order') == WORK_ORDER
        and integration.get('company_id') == COMPANY_ID
        and integration.get('configured_url') == SOURCE
        and integration.get('source_targets') == [TARGET]
        and owner.get('company_id') == COMPANY_ID
        and bool(owner.get('outcome_id'))
        and state.get('max_sessions') == 1
        and state.get('authorization_version') == 1
        and state.get('mode') == 'develop'
        and state.get('isolated_workspace') is True
    )


def has_edit_authority(state):
    return (
        is_assignment(state)
        and state.get('phase') == 'implement'
        and state.get('workflow', {}).get('approved_parser_outcome')
        == state['repair_provenance']['outcome_id']
    )
