"""Read-only, held-byte snapshots of installed guarded source mappings."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit

from .company_events import current_company_repair_snapshot
from .company_sources import REPAIRS

_PATHS = (
    'src/job_search_helper/shared_boards.py', 'src/job_search_helper/shared_extended.py',
    'src/job_search_helper/ats.py', 'src/job_search_helper/core.py',
    'src/job_search_helper/company_sources.py', 'src/job_search_helper/source_configuration_manifest.json')
QUALIFICATION_PATH = 'src/job_search_helper/source_configuration_qualification.json'
MAPPING_FACTS_PATH = 'src/job_search_helper/source_configuration_mapping_facts.json'
_TOKEN = re.compile(r'^[a-z0-9][a-z0-9._-]{0,95}$')
_SHA = re.compile(r'^[0-9a-f]{64}$')


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _root():
    here = Path(__file__)
    if here.is_symlink():
        return None
    root = here.parent.parent.parent
    return root if root.is_dir() and not root.is_symlink() else None


def _held_read_allowed(root_fd, relative, allowed):
    """Read one fixed application artifact without following a path component.

    ``allowed`` is deliberately a closed tuple.  In particular the
    qualification matrix is not a capability source and must never influence
    the installed-capability source digest.
    """
    if relative not in allowed or '..' in relative.split('/'):
        return None
    current = os.dup(root_fd)
    try:
        parts = relative.split('/')
        for component in parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=current)
            os.close(current)
            current = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current)
        os.close(current)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            os.close(fd); return None
        data = b''.join(iter(lambda: os.read(fd, 65536), b''))
        after = os.fstat(fd); os.close(fd)
    except OSError:
        try: os.close(current)
        except OSError: pass
        return None
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        return None
    return data


def _held_read(root_fd, relative):
    return _held_read_allowed(root_fd, relative, _PATHS)


def _duplicate_free_json(data):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, ValueError):
        return None


def _canonical_bytes(value):
    return (_json(value) + '\n').encode('utf-8')


def _digest_text(value):
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _provider(value):
    value = value.strip().casefold() if isinstance(value, str) else ''
    return value if _TOKEN.fullmatch(value) else ''


def _rippling_url(value):
    if not isinstance(value, str) or value != value.strip() or '%' in value:
        return ''
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return ''
    match = re.fullmatch(r'/([a-z0-9-]+)/jobs', parts.path)
    if (parts.scheme != 'https' or parts.hostname not in {'ats.rippling.com', 'ats.us1.rippling.com'}
            or parts.netloc != parts.hostname or port is not None or parts.query or parts.fragment
            or not match):
        return ''
    return 'https://' + parts.hostname + parts.path


def _canonical_mapping(entry):
    required = {'company_id', 'company', 'provider', 'expected_url', 'configured_url',
                'evidence', 'capability_id', 'company_sources_sha256'}
    allowed = required | {'expected_urls', 'company_aliases'}
    if not isinstance(entry, dict) or set(entry) - allowed or not required <= set(entry):
        return None
    if (not isinstance(entry['company_id'], str) or not re.fullmatch(r'COMP-\d{4,}', entry['company_id'])
            or not isinstance(entry['company'], str) or not entry['company'].strip()
            or _provider(entry['provider']) != 'rippling' or entry['capability_id'] != 'rippling-shared-v1'
            or not isinstance(entry['evidence'], str) or not entry['evidence']
            or not _SHA.fullmatch(entry['company_sources_sha256'])
            or not _rippling_url(entry['configured_url'])):
        return None
    aliases = entry.get('company_aliases', {})
    if not isinstance(aliases, dict) or any(not isinstance(k, str) or not k or v != entry['company'] for k, v in aliases.items()):
        return None
    if (len({key.casefold() for key in aliases}) != len(aliases)
            or entry['company'].casefold() in {key.casefold() for key in aliases}):
        return None
    extra_urls = entry.get('expected_urls', [])
    if not isinstance(extra_urls, list):
        return None
    expected = [entry['expected_url']] + extra_urls
    if (not all(isinstance(value, str) for value in expected)
            or len(expected) != len(set(expected))):
        return None
    return entry


def validate_installed_source_configuration(snapshot):
    """Return a canonical copy of one public snapshot, else ``None``.

    This accepts no caller-selected paths or configuration: it only validates
    the closed first Rippling capability grammar used by this installed build.
    """
    fields = {'schema', 'company_id', 'source_revision', 'company',
              'official_careers_url', 'ats_source', 'configured_provider',
              'configured_url', 'capability_id', 'capability_sources',
              'capability_digest', 'mapping_digest', 'configuration_digest'}
    if not isinstance(snapshot, dict) or set(snapshot) != fields:
        return None
    if (snapshot['schema'] != 'installed-source-configuration-v1'
            or not isinstance(snapshot['company_id'], str)
            or not re.fullmatch(r'COMP-\d{4,}', snapshot['company_id'])
            or not isinstance(snapshot['source_revision'], str)
            or not _SHA.fullmatch(snapshot['source_revision'])
            or not isinstance(snapshot['company'], str)
            or snapshot['company'] != snapshot['company'].strip() or not snapshot['company']
            or not isinstance(snapshot['official_careers_url'], str)
            or not _provider(snapshot['ats_source']) or snapshot['ats_source'] != 'rippling'
            or snapshot['configured_provider'] != 'rippling'
            or not _rippling_url(snapshot['configured_url'])
            or snapshot['capability_id'] != 'rippling-shared-v1'
            or any(not isinstance(snapshot[key], str) or not _SHA.fullmatch(snapshot[key])
                   for key in ('capability_digest', 'mapping_digest', 'configuration_digest'))):
        return None
    sources = snapshot['capability_sources']
    if (not isinstance(sources, list) or [item.get('path') if isinstance(item, dict) else None
                                          for item in sources] != list(_PATHS)
            or any(not isinstance(item, dict) or set(item) != {'path', 'sha256'}
                   or not isinstance(item['sha256'], str)
                   or not _SHA.fullmatch(item['sha256']) for item in sources)):
        return None
    capability = {'capability_id': 'rippling-shared-v1', 'provider': 'rippling',
                  'source_paths': list(_PATHS)}
    if snapshot['capability_digest'] != _digest({'capability': capability, 'sources': sources}):
        return None
    expected = dict(snapshot)
    configuration_digest = expected.pop('configuration_digest')
    if configuration_digest != _digest(expected):
        return None
    return json.loads(_json(snapshot))


class _CompanyAuthority:
    """Expose one narrow identity read across application repository types."""
    def __init__(self, repository):
        self.repository = repository

    def matches(self, tab, identity):
        if tab != 'Companies' or set(identity) != {'Company ID'}:
            return []
        matcher = getattr(self.repository, 'matches', None)
        if callable(matcher):
            return matcher(tab, identity)
        rows = self.repository.read('Companies')
        wanted = str(identity['Company ID']).strip()
        return [(number + 1, row) for number, row in enumerate(rows)
                if str(row.get('Company ID', '')).strip() == wanted]


def _resolve_authoritative_installed_source_configuration(repository, company_id):
    """Return a fail-closed installed configuration snapshot, or ``None``."""
    if not isinstance(company_id, str) or not company_id.strip():
        return None
    authority = _CompanyAuthority(repository)
    initial = current_company_repair_snapshot(authority, company_id.strip())
    if initial is None or _provider(initial['ats_source']) != 'rippling':
        return None
    root = _root()
    if root is None:
        return None
    try:
        root_fd = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        held = {path: _held_read(root_fd, path) for path in _PATHS}
    finally:
        os.close(root_fd)
    if any(value is None for value in held.values()):
        return None
    try:
        def unique_pairs(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError('duplicate JSON key')
                value[key] = item
            return value
        manifest = json.loads(held[_PATHS[-1]].decode('utf-8'), object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, ValueError):
        return None
    if (not isinstance(manifest, dict) or set(manifest) != {'schema', 'capabilities', 'mappings'}
            or manifest['schema'] != 'source-configuration-manifest-v1'
            or not isinstance(manifest['capabilities'], list) or len(manifest['capabilities']) != 1
            or not isinstance(manifest['mappings'], list)):
        return None
    capability = manifest['capabilities'][0]
    if (not isinstance(capability, dict) or set(capability) != {'capability_id', 'provider', 'source_paths'}
            or capability.get('capability_id') != 'rippling-shared-v1' or _provider(capability.get('provider')) != 'rippling'
            or capability.get('source_paths') != list(_PATHS)):
        return None
    entries = [_canonical_mapping(value) for value in manifest['mappings']]
    if any(value is None for value in entries) or len({value['company_id'] for value in entries}) != len(entries):
        return None
    matches = [value for value in entries if value['company_id'] == initial['company_id']]
    if len(matches) != 1:
        return None
    mapping = matches[0]
    aliases = mapping.get('company_aliases', {})
    canonical_match = initial['company'] == mapping['company']
    alias_match = initial['company'] in aliases
    if canonical_match == alias_match or (alias_match and aliases[initial['company']] != mapping['company']):
        return None
    try:
        from .core import canonicalize_url
        current_url = canonicalize_url(initial['official_careers_url'])
        expected = [canonicalize_url(mapping['expected_url'])] + [canonicalize_url(v) for v in mapping.get('expected_urls', [])]
    except ValueError:
        return None
    loaded = {'ats': 'Rippling', 'company': mapping['company'], 'evidence': mapping['evidence'],
              'expected_url': mapping['expected_url'], 'url': mapping['configured_url']}
    if 'expected_urls' in mapping:
        loaded['expected_urls'] = mapping['expected_urls']
    if 'company_aliases' in mapping:
        loaded['company_aliases'] = mapping['company_aliases']
    if expected.count(current_url) != 1 or initial['ats_source'] != mapping['provider'] or REPAIRS.get(initial['company_id']) != loaded:
        return None
    if hashlib.sha256(held['src/job_search_helper/company_sources.py']).hexdigest() != mapping['company_sources_sha256']:
        return None
    sources = [{'path': path, 'sha256': hashlib.sha256(held[path]).hexdigest()} for path in _PATHS]
    capability_digest = _digest({'capability': capability, 'sources': sources})
    mapping_digest = _digest(mapping)
    result = {'schema': 'installed-source-configuration-v1', 'company_id': initial['company_id'],
              'source_revision': initial['source_revision'], 'company': initial['company'],
              'official_careers_url': current_url, 'ats_source': initial['ats_source'],
              'configured_provider': 'rippling', 'configured_url': mapping['configured_url'],
              'capability_id': 'rippling-shared-v1', 'capability_sources': sources,
              'capability_digest': capability_digest, 'mapping_digest': mapping_digest}
    final = current_company_repair_snapshot(authority, company_id.strip())
    if final != initial:
        return None
    result['configuration_digest'] = _digest(result)
    return validate_installed_source_configuration(result)


def resolve_installed_source_configuration(repository, company_id):
    """Public candidate resolver; admission uses the private reread directly."""
    return _resolve_authoritative_installed_source_configuration(repository, company_id)


_QUALIFICATION_FIELDS = {
    'company_id', 'source_revision', 'capability_id', 'capability_digest',
    'mapping_digest', 'configuration_digest', 'category', 'evidence_code',
}
_FACT_FIELDS = {
    'schema', 'cycle_id', 'company_id', 'source_revision', 'capability_id',
    'capability_digest', 'mapping_digest', 'configuration_digest',
    'authority_extraction_digest', 'candidate_inventory_digest',
    'regression_inventory_digest', 'evidence_code',
}
_SIDECAR_FIELDS = {
    'schema', 'capability_id', 'capability_digest', 'mapping_digest',
    'configuration_digest', 'category', 'evidence_code',
}
_EVIDENCE_FIELDS = {'schema', 'matrix_digest', 'qualification'}


def _canonical_qualification(value):
    if not isinstance(value, dict) or set(value) != _QUALIFICATION_FIELDS:
        return None
    if (not isinstance(value['company_id'], str) or not re.fullmatch(r'COMP-\d{4,}', value['company_id'])
            or not isinstance(value['source_revision'], str) or not _SHA.fullmatch(value['source_revision'])
            or value['capability_id'] != 'rippling-shared-v1'
            or any(not isinstance(value[key], str) or not _SHA.fullmatch(value[key])
                   for key in ('capability_digest', 'mapping_digest', 'configuration_digest'))
            or value['category'] != 'same_provider_source_mapping'
            or value['evidence_code'] != 'rippling_verified_mapping_divergence'):
        return None
    return json.loads(_json(value))


def validate_mapping_divergence_fact(value, *, cycle_id=None, snapshot=None):
    """Validate the closed F5 fact; callers cannot extend this grammar."""
    if not isinstance(value, dict) or set(value) != _FACT_FIELDS:
        return None
    if (value.get('schema') != 'rippling-mapping-divergence-fact-v1'
            or not isinstance(value.get('cycle_id'), str) or not value['cycle_id']
            or not isinstance(value.get('company_id'), str) or not re.fullmatch(r'COMP-\d{4,}', value['company_id'])
            or not isinstance(value.get('source_revision'), str) or not _SHA.fullmatch(value['source_revision'])
            or value.get('capability_id') != 'rippling-shared-v1'
            or value.get('evidence_code') != 'rippling_verified_mapping_divergence'
            or any(not isinstance(value.get(key), str) or not _SHA.fullmatch(value[key])
                   for key in ('capability_digest', 'mapping_digest', 'configuration_digest',
                               'authority_extraction_digest', 'candidate_inventory_digest',
                               'regression_inventory_digest'))):
        return None
    result = json.loads(_json(value))
    if cycle_id is not None and result['cycle_id'] != cycle_id:
        return None
    checked = validate_installed_source_configuration(snapshot) if snapshot is not None else None
    if snapshot is not None and (checked is None or any(result[key] != checked[key] for key in (
            'company_id', 'source_revision', 'capability_id', 'capability_digest',
            'mapping_digest', 'configuration_digest'))):
        return None
    return result


def validate_source_configuration_defect(value, *, snapshot=None):
    if not isinstance(value, dict) or set(value) != _SIDECAR_FIELDS:
        return None
    if (value.get('schema') != 'source-configuration-defect-v1'
            or value.get('capability_id') != 'rippling-shared-v1'
            or value.get('category') != 'same_provider_source_mapping'
            or value.get('evidence_code') != 'rippling_verified_mapping_divergence'
            or any(not isinstance(value.get(key), str) or not _SHA.fullmatch(value[key])
                   for key in ('capability_digest', 'mapping_digest', 'configuration_digest'))):
        return None
    result = json.loads(_json(value))
    checked = validate_installed_source_configuration(snapshot) if snapshot is not None else None
    if snapshot is not None and (checked is None or any(result[key] != checked[key] for key in (
            'capability_id', 'capability_digest', 'mapping_digest', 'configuration_digest'))):
        return None
    return result


def read_source_configuration_qualification():
    """Read the held default-empty F5 matrix, returning no caller-selected data."""
    root = _root()
    if root is None:
        return None
    try:
        root_fd = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        raw = _held_read_allowed(root_fd, QUALIFICATION_PATH, (QUALIFICATION_PATH,))
    finally:
        os.close(root_fd)
    if raw is None or not raw.endswith(b'\n'):
        return None
    value = _duplicate_free_json(raw)
    if (value is None or _canonical_bytes(value) != raw
            or not isinstance(value, dict) or set(value) != {'schema', 'qualifications'}
            or value.get('schema') != 'source-configuration-qualification-v1'
            or not isinstance(value.get('qualifications'), list)):
        return None
    entries = [_canonical_qualification(entry) for entry in value['qualifications']]
    if any(entry is None for entry in entries):
        return None
    tuples = [_json(entry) for entry in entries]
    if tuples != sorted(tuples) or len(tuples) != len(set(tuples)):
        return None
    return {'matrix_digest': hashlib.sha256(raw).hexdigest(), 'qualifications': entries}


def qualification_for_snapshot(snapshot):
    """Return the one exact F5 tuple for a frozen installed snapshot."""
    checked = validate_installed_source_configuration(snapshot)
    matrix = read_source_configuration_qualification()
    if checked is None or matrix is None:
        return None
    matches = [entry for entry in matrix['qualifications'] if all(
        entry[key] == checked[key] for key in ('company_id', 'source_revision', 'capability_id',
                                                'capability_digest', 'mapping_digest',
                                                'configuration_digest'))]
    if len(matches) != 1:
        return None
    return {'matrix_digest': matrix['matrix_digest'], 'qualification': matches[0]}


def validate_source_configuration_qualification_evidence(value, *, snapshot=None):
    if not isinstance(value, dict) or set(value) != _EVIDENCE_FIELDS:
        return None
    if (value.get('schema') != 'source-configuration-qualification-evidence-v1'
            or not isinstance(value.get('matrix_digest'), str) or not _SHA.fullmatch(value['matrix_digest'])):
        return None
    qualification = _canonical_qualification(value.get('qualification'))
    checked = validate_installed_source_configuration(snapshot) if snapshot is not None else None
    if qualification is None or (snapshot is not None and (checked is None or any(
            qualification[key] != checked[key] for key in ('company_id', 'source_revision', 'capability_id',
                'capability_digest', 'mapping_digest', 'configuration_digest')))):
        return None
    return {'schema': value['schema'], 'matrix_digest': value['matrix_digest'],
            'qualification': qualification}


def mapping_fact_id(fact):
    """The deterministic identifier of a canonical, closed machine fact."""
    checked = validate_mapping_divergence_fact(fact)
    return _digest_text(checked) if checked is not None else None


def read_source_configuration_mapping_facts():
    """Read the immutable default-empty F5 fact descriptor; no writer exists."""
    root = _root()
    if root is None:
        return None
    try:
        root_fd = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        raw = _held_read_allowed(root_fd, MAPPING_FACTS_PATH, (MAPPING_FACTS_PATH,))
    finally:
        os.close(root_fd)
    if raw is None or not raw.endswith(b'\n'):
        return None
    value = _duplicate_free_json(raw)
    if (value is None or _canonical_bytes(value) != raw or not isinstance(value, dict)
            or set(value) != {'schema', 'facts'}
            or value.get('schema') != 'source-configuration-mapping-facts-v1'
            or not isinstance(value.get('facts'), list)):
        return None
    records = []
    for entry in value['facts']:
        if not isinstance(entry, dict) or set(entry) != {'fact_id', 'fact'}:
            return None
        fact = validate_mapping_divergence_fact(entry['fact'])
        if (not isinstance(entry['fact_id'], str) or not _SHA.fullmatch(entry['fact_id'])
                or mapping_fact_id(fact) != entry['fact_id']):
            return None
        records.append({'fact_id': entry['fact_id'], 'fact': fact})
    order = [_json(record) for record in records]
    if order != sorted(order) or len(order) != len(set(order)):
        return None
    return records


def mapping_fact_by_id(cycle_id, company_id, fact_id, *, state=None, repository=None, runtime_binding=None):
    """Read a packaged fact, or use the exact runtime owner when supplied.

    The existing three-argument lookup never consults runtime data. A runtime
    owner that has a fact reserves that owner even when a different ID is asked
    for. A corrupt or stale runtime record raises and never falls back.
    """
    if (not isinstance(cycle_id, str) or not cycle_id or not isinstance(company_id, str)
            or not company_id or not isinstance(fact_id, str) or not _SHA.fullmatch(fact_id)):
        return None
    if any(value is not None for value in (state, repository, runtime_binding)):
        if any(value is None for value in (state, repository, runtime_binding)):
            raise ValueError('Runtime mapping fact lookup requires the complete admitted owner.')
        from .runtime_mapping_facts import read_runtime_mapping_fact

        runtime = read_runtime_mapping_fact(state, repository, runtime_binding, cycle_id=cycle_id, company_id=company_id)
        if runtime is not None:
            return runtime['fact'] if runtime['fact_id'] == fact_id else None
    records = read_source_configuration_mapping_facts()
    if records is None:
        return None
    matches = [record['fact'] for record in records if record['fact_id'] == fact_id
               and record['fact']['cycle_id'] == cycle_id
               and record['fact']['company_id'] == company_id]
    return matches[0] if len(matches) == 1 else None
