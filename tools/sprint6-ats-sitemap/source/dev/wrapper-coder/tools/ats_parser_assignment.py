"""Exact one-function ATS parser assignment and returned edit guard."""

from hashlib import sha256
import json

from coordinator_evidence import _safe_existing


TARGET = 'src/job_search_helper/ats_sitemap_parser.py'
TEST = 'tests/test_ats_sitemap_parser.py'
WORK_ORDER = 'successfactors-ats-sitemap-parser-v1'
COMPANY_ID = 'COMP-0573'
SOURCE = 'https://jobs.atsautomation.com/'
NAMESPACE = 'http://www.sitemaps.org/schemas/sitemap/0.9'
PREFIXES = ('/job/', '/PA/job/', '/Comecer/job/')


def render(root, baseline, schema):
    if schema.get('function', {}).get('name') != 'code_edit':
        raise ValueError('The ATS parser assignment offers one scoped source edit.')
    target = _safe_existing(root, TARGET)
    test = _safe_existing(root, TEST)
    if target is None or test is None:
        raise ValueError('The pinned ATS parser assignment files are absent.')
    before = target.read_bytes()
    source_pin = sha256(before).hexdigest()
    if source_pin != baseline.get(TARGET) or sha256(test.read_bytes()).hexdigest() != baseline.get(TEST):
        raise ValueError('The ATS parser or acceptance fixture differs from its reviewed baseline.')
    packet = {
        'path': TARGET,
        'sha256': source_pin,
        'old': before.decode(),
        'authority': {
            'host': 'jobs.atsautomation.com',
            'namespace': NAMESPACE,
            'job_path_prefixes': PREFIXES,
        },
        'instructions': [
            'Return a single code_edit replacing the entire supplied small file.',
            'Set PARSER_READY = True and implement parse_job_sitemap(xml: str) -> dict[str, str]. '
            'Do not add network calls, file reads, a generator, or dependencies beyond Python standard XML and URL parsing.',
            'Input is a standard namespaced urlset. Accept only exact HTTPS same-host canonical posting paths '
            'with a slug and numeric ID. Preserve the entire URL and map from its ID. '
            'Allow same-host non-job navigation links but reject foreign hosts, unsupported job path forms, duplicate '
            'IDs, invalid XML and empty job inventories by raising ValueError. Reject any DOCTYPE or ENTITY.',
            'The approved job prefixes are /job/, /PA/job/ and /Comecer/job/. '
            'MuleLab fetches source and details, checks canonical membership and runs all tests.',
        ],
        'examples': {
            'https://jobs.atsautomation.com/job/Engineering/10001/': '10001',
            'https://jobs.atsautomation.com/PA/job/Process-Engineering/10002/': '10002',
            'https://jobs.atsautomation.com/Comecer/job/Technician/10003/': '10003',
        },
    }
    return [
        {'role': 'system', 'content': 'Return exactly one guarded code_edit to the supplied path. Use the supplied file text as old and produce working code.'},
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
        or not args['old'] or not args['new'] or args['old'] == args['new']
    ):
        raise ValueError('The ATS worker did not return one exact guarded edit.')
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
