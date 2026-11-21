"""Validate the measured descriptor paired with a single mapping correction."""

import ast
from hashlib import sha256
import os

from .source_configuration_snapshot import _PATHS, _canonical_mapping, _duplicate_free_json, _held_read


REGISTRY = 'src/job_search_helper/company_sources.py'
DESCRIPTOR = 'src/job_search_helper/source_configuration_manifest.json'
_CAPABILITY = {'capability_id': 'rippling-shared-v1', 'provider': 'rippling', 'source_paths': list(_PATHS)}


def _snapshot(root, files, phase):
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        contents = {name: _held_read(directory, name) for name in (REGISTRY, DESCRIPTOR)}
    finally:
        os.close(directory)
    for name, raw in contents.items():
        if raw is None or sha256(raw).hexdigest() != files[name][phase]['sha256']:
            raise ValueError('The source mapping companion does not match its measured file')
    descriptor = _duplicate_free_json(contents[DESCRIPTOR])
    if (not isinstance(descriptor, dict) or set(descriptor) != {'schema', 'capabilities', 'mappings'}
            or descriptor['schema'] != 'source-configuration-manifest-v1'
            or descriptor['capabilities'] != [_CAPABILITY] or not isinstance(descriptor['mappings'], list)):
        raise ValueError('The source mapping companion changed its reviewed capability')
    records = {}
    for entry in descriptor['mappings']:
        mapping = _canonical_mapping(entry)
        if (mapping is None or mapping['company_id'] in records
                or mapping['company_sources_sha256'] != files[REGISTRY][phase]['sha256']):
            raise ValueError('The source mapping companion has an invalid or unmeasured mapping')
        records[mapping['company_id']] = mapping
    return contents[REGISTRY], records


def _mask_board(registry, company_id, mapping):
    """Compare the real registry AST while ignoring only the selected URL."""
    try:
        tree = ast.parse(registry)
        company_nodes = [node for node in ast.walk(tree)
                         if isinstance(node, ast.Constant) and node.value == company_id]
        if len(company_nodes) != 1:
            raise ValueError
        (company_node,) = company_nodes
        (entry,) = (
            value
            for node in ast.walk(tree) if isinstance(node, ast.Dict)
            for key, value in zip(node.keys, node.values) if key is company_node
        )
        if not isinstance(entry, ast.Dict):
            raise ValueError
        expected = {'ats': 'Rippling', 'company': mapping['company'], 'evidence': mapping['evidence'],
                    'expected_url': mapping['expected_url'], 'url': mapping['configured_url']}
        expected.update({key: mapping[key] for key in ('expected_urls', 'company_aliases') if key in mapping})
        if len(entry.keys) != len(expected) or ast.literal_eval(entry) != expected:
            raise ValueError
        (board,) = (value for key, value in zip(entry.keys, entry.values)
                    if isinstance(key, ast.Constant) and key.value == 'url')
        if not isinstance(board, ast.Constant):
            raise ValueError
    except (SyntaxError, TypeError, ValueError):
        raise ValueError('The measured registry does not contain the exact literal Company mapping') from None
    board.value = None
    return ast.dump(tree)


def verify_companion_mapping(project_root, candidate_root, manifest):
    """Prove the paired files alter only one named mapping in one capability."""
    files = manifest['files']
    company = manifest['company_id']
    before_source, before = _snapshot(project_root, files, 'before')
    after_source, after = _snapshot(candidate_root, files, 'after')
    if company not in before or before.keys() != after.keys():
        raise ValueError('The source mapping companion must retain existing Company membership')
    ignored_target = {'company_sources_sha256', 'configured_url'}
    for company_id, previous in before.items():
        ignored = ignored_target if company_id == company else {'company_sources_sha256'}
        current = after[company_id]
        if ({key: value for key, value in previous.items() if key not in ignored}
                != {key: value for key, value in current.items() if key not in ignored}):
            raise ValueError('The source mapping companion changes unqualified Company data')
    if before[company]['configured_url'] == after[company]['configured_url']:
        raise ValueError('The source mapping companion requires a changed Company board')
    if _mask_board(before_source, company, before[company]) != _mask_board(after_source, company, after[company]):
        raise ValueError('The registry changes executable source outside the qualified Company board')
