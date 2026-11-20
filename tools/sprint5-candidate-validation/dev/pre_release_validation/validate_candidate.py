"""Replay reviewed synthetic Rippling evidence through a pinned candidate.

Run in a fresh, isolated standard-library Python process. The release owner
supplies the candidate and capture pins separately from the replay capture.
"""
from __future__ import annotations

import argparse
from collections import deque
from contextlib import contextmanager
from hashlib import sha256
from importlib.abc import Loader, MetaPathFinder
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from tempfile import TemporaryDirectory


PIN_SCHEMA = 'company-candidate-validation-pin-v1'
CAPTURE_SCHEMA = 'rippling-fixture-capture-v1'
RECEIPT_SCHEMA = 'company-candidate-validation-receipt-v1'
DIGEST_FIELDS = {'source_manifest_sha256', 'config_sha256', 'dependency_manifest_sha256'}
ROW_FIELDS = {'Company ID', 'Company', 'Company Status', 'Official Careers URL', 'ATS / Source'}
DESCRIPTION_FIELDS = ('posting_id', 'url', 'title', 'description')
SUPPORTED_SCOPE = (
    ('target', 'COMP-0066', 'Forterra', 'https://ats.rippling.com/forterra/jobs'),
    ('regression', 'COMP-0178', 'PDW', 'https://ats.rippling.com/pdwcareers/jobs'),
)
SCOPE_FIELDS = {'role', 'company_id', 'company', 'company_row_sha256', 'source_revision',
                'authority_url', 'board_url'}
MAX_CAPTURE_BYTES = 64 * 1024 * 1024
MAX_BOARD_REQUESTS = 13_000
# Match the reviewed Rippling scope: an initial scan, a reread, and up to
# three reconciliation rounds. A future wider scope needs its own review.
MAX_LISTING_READS = 5
FIXTURE_ROOT_FILES = ('.storage-backend', 'title-blacklist.txt', 'title-review-list.txt',
                      'pyproject.toml', 'requirements.txt', 'requirements.lock', 'uv.lock', 'poetry.lock')


class ValidationError(ValueError):
    pass


def digest(value):
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return sha256(canonical.encode()).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValidationError(reason)


def checked_fields(value, fields):
    require(isinstance(value, dict) and set(value) == fields, 'invalid_input_fields')


def read_input(path, bound):
    with path.open('rb') as stream:
        raw = stream.read(bound + 1)
    require(len(raw) <= bound, 'input_exceeds_bound')
    return raw


def parse_json(raw):
    def distinct_object(pairs):
        result = dict(pairs)
        require(len(result) == len(pairs), 'duplicate_json_keys')
        return result

    return json.loads(raw, object_pairs_hook=distinct_object)


def validate_pin(pin):
    checked_fields(pin, {'schema', 'candidate', 'measurement_tool_sha256', 'capture_sha256', 'scope'})
    require(pin['schema'] == PIN_SCHEMA, 'invalid_pin_schema')
    checked_fields(pin['candidate'], DIGEST_FIELDS)
    scope = pin['scope']
    require(isinstance(scope, list) and len(scope) == len(SUPPORTED_SCOPE), 'reviewed_forterra_and_pdw_required')
    for entry, identity in zip(scope, SUPPORTED_SCOPE, strict=True):
        checked_fields(entry, SCOPE_FIELDS)
        require(tuple(entry[key] for key in ('role', 'company_id', 'company', 'board_url')) == identity,
                'reviewed_forterra_and_pdw_required')
        for key in ('authority_url', 'board_url'):
            require(isinstance(entry[key], str) and entry[key].startswith('https://'), 'invalid_scope_url')
    row_digests = [entry[key] for entry in scope for key in ('company_row_sha256', 'source_revision')]
    for value in [*pin['candidate'].values(), pin['measurement_tool_sha256'], pin['capture_sha256'], *row_digests]:
        require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value), 'invalid_digest')


class BoardReplay:
    """Deliver pinned responses and independently account for every page and detail."""

    def __init__(self, board, responses, http_response, oracle):
        require(isinstance(responses, dict) and 0 < len(responses) <= MAX_BOARD_REQUESTS,
                'invalid_response_table')
        self.responses = {}
        for url, entries in responses.items():
            require(isinstance(entries, list) and 0 < len(entries) <= MAX_LISTING_READS,
                    'invalid_response_sequence')
            for entry in entries:
                checked_fields(entry, {'status', 'body'})
                require(type(entry['status']) is int and 100 <= entry['status'] <= 599
                        and isinstance(entry['body'], str), 'invalid_captured_response')
            self.responses[url] = deque(entries)
        require(sum(map(len, self.responses.values())) <= MAX_BOARD_REQUESTS, 'response_limit')
        self.board = board
        self.http_response = http_response
        self.oracle = oracle
        self.trace = []
        self.violations = []
        self.listings = []
        self.details = {}
        self.items = {}
        self.page = 0
        self.total = None
        self.page_counts = []

    def _observe(self, url, body):
        if url.startswith(self.board + '/'):
            ident = url.removeprefix(self.board + '/')
            require(self.listings and self.page == 0 and ident in self.listings[-1]['items'],
                    'detail_outside_complete_listing')
            item = self.listings[-1]['items'][ident]
            self.details[ident] = (item, self.oracle.read_detail(self.board, item, body))
            return
        expected_url = self.board + (f'?page={self.page}' if self.page else '')
        require(url == expected_url, 'foreign_board_or_page_sequence')
        require(len(self.listings) < MAX_LISTING_READS, 'reconciliation_limit')
        total, entries = self.oracle.read_listing(self.board, self.page, body)
        require(self.total is None or total == self.total, 'listing_total_changed_between_pages')
        self.total = total
        for entry in entries:
            ident = entry['id']
            require(ident not in self.items, 'duplicate_listing_id')
            self.items[ident] = entry
        self.page_counts.append(len(entries))
        if len(self.items) == self.total:
            self.listings.append({'total': total, 'page_counts': self.page_counts, 'items': self.items})
            self.items, self.page_counts = {}, []
            self.total, self.page = None, 0
        else:
            self.page += 1

    def get(self, url):
        require(len(self.trace) < MAX_BOARD_REQUESTS, 'request_limit')
        entries = self.responses.get(url)
        if not entries:
            self.violations.append('missing_or_out_of_scope_response')
            self.trace.append({'request_sha256': digest(url), 'status': None})
            return self.http_response(404, b'')
        entry = entries.popleft()
        status, body = entry['status'], entry['body']
        raw = body.encode()
        self.trace.append({'url': url, 'status': status, 'body_sha256': sha256(raw).hexdigest()})
        if status != 200:
            self.violations.append('non_success_response')
        else:
            try:
                self._observe(url, body)
            except (ValidationError, self.oracle.CaptureError) as error:
                self.violations.append(str(error))
        return self.http_response(status, raw, {'Content-Type': 'text/html; charset=utf-8'})

    def post(self, url, payload):
        self.violations.append('unexpected_provider_post')
        raise ValidationError('unexpected_provider_post')

    def expected_jobs(self):
        require(not self.violations, self.violations[0] if self.violations else '')
        require(not any(self.responses.values()), 'unconsumed_capture_responses')
        require(self.page == 0 and len(self.listings) >= 2, 'incomplete_listing_or_reread')
        initial = self.listings[-2]['items']
        final = self.listings[-1]['items']
        require(initial == final, 'inventory_did_not_stabilize')
        expected = {}
        for ident, item in final.items():
            detail = self.details.get(ident)
            require(detail is not None and detail[0] == item, 'missing_current_detail')
            expected[ident] = detail[1]
        return expected


class EmployerReplay:
    def __init__(self, url, body, http_response):
        self.url, self.body, self.http_response = url, body, http_response
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        require(url == self.url and len(self.calls) <= 2, 'unexpected_employer_request')
        return self.http_response(200, self.body.encode())


def validate_company(case, scope, received, row_revision, oracle, dispatch, http_response):
    checked_fields(case, {'role', 'company', 'authority', 'board_url', 'responses'})
    company = case['company']
    checked_fields(company, ROW_FIELDS)
    require(all(isinstance(value, str) and value and value.strip() == value for value in company.values())
            and company['Company Status'] == 'Active' and company['ATS / Source'] == 'Rippling',
            'invalid_company_row')
    cid, name, url = (company[key] for key in ('Company ID', 'Company', 'Official Careers URL'))
    revision = row_revision(company)
    board = case['board_url']
    received.update(role=case['role'], company_id=cid, company=name, company_row_sha256=digest(company),
                    source_revision=revision, board_url=board)
    authority = case['authority']
    checked_fields(authority, {'url', 'body'})
    observed_scope = {key: received[key] for key in SCOPE_FIELDS - {'authority_url'}}
    observed_scope['authority_url'] = authority['url']
    require(observed_scope == scope and url in (authority['url'], board), 'company_row_outside_reviewed_scope')
    oracle.check_authority(authority['url'], board, authority['body'])
    received['authority'] = {'url': authority['url'], 'body_sha256': sha256(authority['body'].encode()).hexdigest()}
    employer = EmployerReplay(authority['url'], authority['body'], http_response)
    replay = BoardReplay(board, case['responses'], http_response, oracle)
    try:
        inventory = dispatch('Rippling', url, cid, name, transport=replay, discovery_transport=employer)
        received['dispatch_status'] = inventory.status
        expected = replay.expected_jobs()
        require(inventory.status == 'complete' and inventory.source_url == board and inventory.ats == 'Rippling',
                'dispatch_scope_or_status_mismatch')
        actual = {}
        for job in inventory.jobs:
            require(job['company_id'] == cid and job['company'] == name and job['ats'] == 'Rippling'
                    and job['is_listed'] is True, 'dispatched_job_outside_scope')
            ident = job['posting_id']
            require(ident not in actual, 'duplicate_dispatched_job_id')
            actual[ident] = {field: job[field] for field in DESCRIPTION_FIELDS}
        require(actual.keys() == expected.keys(), 'dispatch_inventory_membership_mismatch')
        require(actual == expected, 'dispatch_job_identity_or_full_description_mismatch')
        received.update(posting_count=len(actual), posting_evidence_sha256=digest(actual),
                        zero_evidence='scoped_explicit_zero_with_reread' if not actual else None)
    finally:
        received['board_trace'] = replay.trace
        received['employer_requests'] = employer.calls
        received['listing_reads'] = [dict(total=listing['total'], page_counts=listing['page_counts'],
                                          items_sha256=digest(listing['items'])) for listing in replay.listings]


@contextmanager
def prohibit_io(attempts):
    active = True

    def audit(event, args):
        if not active:
            return
        write_open = event == 'open' and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        mutation = event in {'os.rename', 'os.remove', 'os.mkdir', 'os.rmdir', 'os.chmod',
                             'os.link', 'os.symlink', 'os.truncate', 'sqlite3.connect'}
        launch = event in {'subprocess.Popen', 'os.exec', 'os.posix_spawn', 'os.system'}
        if write_open or mutation or launch or event.startswith('socket.'):
            attempts.append(event)
            raise ValidationError('external_io_attempted')

    sys.addaudithook(audit)
    try:
        yield
    finally:
        active = False


def load_source(name, path):
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    sys.modules[name] = module
    raw = path.read_bytes()
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module, sha256(raw).hexdigest()


def fixture_package(candidate_root):
    src = candidate_root / 'src'
    package = src / 'job_search_helper'
    require(src.is_dir() and not src.is_symlink() and package.is_dir() and not package.is_symlink()
            and (package / '__init__.py').is_file(), 'candidate_package_unavailable')
    return package


def freeze_candidate(candidate_root, frozen_root):
    package = fixture_package(candidate_root)
    for name in ('.env', '.venv'):
        path = candidate_root / name
        require(not path.exists() and not path.is_symlink(), 'fixture_candidate_requires_clean_standard_library_layout')
    shutil.copytree(package, frozen_root / 'src/job_search_helper', symlinks=True)
    configs = candidate_root / '.state/integration-configs'
    if configs.exists() or configs.is_symlink():
        require(not configs.is_symlink() and not configs.parent.is_symlink(), 'unsafe_fixture_configuration_path')
        shutil.copytree(configs, frozen_root / '.state/integration-configs', symlinks=True)
    for name in FIXTURE_ROOT_FILES:
        path = candidate_root / name
        if path.exists() or path.is_symlink():
            shutil.copy2(path, frozen_root / name, follow_symlinks=False)


class VerifiedPackage(MetaPathFinder, Loader):
    """Execute the exact package bytes included in the measured manifest."""

    NAME = 'job_search_helper'

    def __init__(self, package, expected_manifest):
        self.package = package
        self.sources = {}
        manifest = {}
        for path in package.rglob('*'):
            require(not path.is_symlink() and path.name != '__pycache__'
                    and path.suffix not in {'.pyc', '.so', '.pyd'}, 'cached_or_alias_source')
            if path.suffix not in {'.py', '.json'} or not path.is_file():
                continue
            with path.open('rb') as stream:
                mode = stat.S_IMODE(os.fstat(stream.fileno()).st_mode)
                raw = stream.read()
            relative = path.relative_to(package).as_posix()
            manifest[relative] = {'sha256': sha256(raw).hexdigest(), 'mode': mode, 'size': len(raw)}
            if path.suffix == '.py':
                self.sources[relative] = raw
        require(digest(manifest) == expected_manifest, 'executed_package_manifest_mismatch')
        self.loaded = {}

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.NAME and not fullname.startswith(self.NAME + '.'):
            return None
        suffix = fullname.removeprefix(self.NAME).lstrip('.').replace('.', '/')
        package = f'{suffix}/__init__.py' if suffix else '__init__.py'
        if package in self.sources:
            return spec_from_file_location(fullname, self.package / package, loader=self,
                                           submodule_search_locations=[])
        module = f'{suffix}.py'
        if module in self.sources:
            return spec_from_file_location(fullname, self.package / module, loader=self)
        raise ModuleNotFoundError(f'Candidate module is outside the verified package: {fullname}')

    def exec_module(self, module):
        path = Path(module.__file__)
        relative = path.relative_to(self.package).as_posix()
        raw = self.sources[relative]
        self.loaded[relative] = sha256(raw).hexdigest()
        exec(compile(raw, str(path), 'exec'), module.__dict__)


def run(candidate_root, pin_path, capture_path, measurement_tool, receipt):
    require(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode,
            'fresh_isolated_standard_library_process_required')
    tool_root = Path(__file__).resolve().parent
    pin_raw = read_input(pin_path, 16 * 1024)
    capture_raw = read_input(capture_path, MAX_CAPTURE_BYTES)
    receipt.update(pin_sha256=sha256(pin_raw).hexdigest(), capture_sha256=sha256(capture_raw).hexdigest())
    pin = parse_json(pin_raw)
    validate_pin(pin)
    target = pin['scope'][0]
    receipt.update(candidate=pin['candidate'], company_id=target['company_id'],
                   source_revision=target['source_revision'], scope_sha256=digest(pin['scope']))
    require(receipt['capture_sha256'] == pin['capture_sha256'], 'capture_digest_mismatch')
    capture = parse_json(capture_raw)
    checked_fields(capture, {'schema', 'cases'})
    require(capture['schema'] == CAPTURE_SCHEMA, 'fixture_capture_schema_required')
    cases = capture['cases']
    require(isinstance(cases, list) and len(cases) == len(SUPPORTED_SCOPE)
            and all(isinstance(case, dict) and isinstance(case.get('company'), dict) for case in cases)
            and [case.get('role') for case in cases] == ['target', 'regression'], 'reviewed_forterra_and_pdw_required')

    measurement_source = read_input(measurement_tool, 128 * 1024)
    receipt['measurement_tool_sha256'] = sha256(measurement_source).hexdigest()
    require(receipt['measurement_tool_sha256'] == pin['measurement_tool_sha256'], 'measurement_tool_digest_mismatch')
    measurement = {'__name__': '_pinned_release_admission_bootstrap', '__file__': str(measurement_tool)}
    exec(compile(measurement_source, str(measurement_tool), 'exec'), measurement)

    def measure_candidate(root):
        return {'source_manifest_sha256': measurement['source_tree_digest'](root),
                'config_sha256': measurement['config_tree_digest'](root),
                'dependency_manifest_sha256': measurement['dependency_manifest_digest'](root)}

    receipt['observed_candidate_before'] = measure_candidate(candidate_root)
    require(receipt['observed_candidate_before'] == pin['candidate'], 'candidate_pin_mismatch_before_dispatch')
    with TemporaryDirectory(prefix='jsh-m5-replay-', dir='/tmp') as temporary:
        frozen_root = Path(temporary)
        freeze_candidate(candidate_root, frozen_root)
        receipt['execution_candidate_before'] = measure_candidate(frozen_root)
        require(receipt['execution_candidate_before'] == pin['candidate'], 'frozen_candidate_pin_mismatch')
        attempts = []
        with prohibit_io(attempts):
            run_frozen(frozen_root, tool_root, cases, pin, receipt)
            receipt['execution_candidate_after'] = measure_candidate(frozen_root)
        require(not attempts, 'external_io_attempted')
        require(receipt['execution_candidate_after'] == pin['candidate'], 'frozen_candidate_changed_during_dispatch')
    receipt['observed_candidate_after'] = measure_candidate(candidate_root)
    require(receipt['observed_candidate_after'] == pin['candidate'], 'candidate_pin_mismatch_after_dispatch')
    require(all(case['result'] == 'FIXTURE_PASS' for case in receipt['cases']), 'company_fixture_failed')


def run_frozen(frozen_root, tool_root, cases, pin, receipt):
    require(VerifiedPackage.NAME not in sys.modules, 'candidate_already_imported')
    loader = VerifiedPackage(fixture_package(frozen_root), pin['candidate']['source_manifest_sha256'])
    sys.meta_path.insert(0, loader)
    oracle, oracle_digest = load_source('rippling_capture', tool_root / 'rippling_capture.py')
    from job_search_helper import ats, company_events

    require(all(Path(module.__file__).resolve().is_relative_to(frozen_root / 'src/job_search_helper')
                for module in (ats, company_events)), 'candidate_import_origin_mismatch')
    receipt['validator'] = {Path(__file__).name: sha256(Path(__file__).read_bytes()).hexdigest(),
                            'rippling_capture.py': oracle_digest}
    receipt['python'] = {'version': sys.version.split()[0],
                         'executable_sha256': sha256(Path(sys.executable).read_bytes()).hexdigest()}
    for case, scope in zip(cases, pin['scope'], strict=True):
        result = {'result': 'HOLD'}
        receipt['cases'].append(result)
        try:
            validate_company(case, scope, result, company_events.source_revision, oracle, ats.fetch_inventory,
                             ats.HTTPResponse)
        except (ValidationError, oracle.CaptureError) as error:
            result['reason'] = str(error)
        else:
            result['result'] = 'FIXTURE_PASS'
    receipt['executed_package_modules_sha256'] = digest(loader.loaded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--measurement-tool', type=Path, required=True)
    parser.add_argument('--pin', type=Path, required=True)
    parser.add_argument('--capture', type=Path, required=True)
    args = parser.parse_args()
    receipt = {'schema': RECEIPT_SCHEMA, 'result': 'HOLD', 'evidence_class': 'synthetic_fixture', 'cases': []}
    try:
        run(args.candidate_root.resolve(strict=True), args.pin, args.capture, args.measurement_tool, receipt)
    except ValidationError as error:
        receipt['reason'] = str(error)
    except (ValueError, OSError, ImportError, TypeError, KeyError, AttributeError, RuntimeError) as error:
        # Parsing and candidate exceptions can contain captured job or path data.
        receipt['reason'] = f'validation_input_or_runtime_error:{type(error).__name__}'
    else:
        receipt['result'] = 'FIXTURE_PASS'
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    return 0 if receipt['result'] == 'FIXTURE_PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
