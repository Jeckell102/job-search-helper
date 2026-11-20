"""Fixture qualification of Forterra and the frozen PDW Rippling control."""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from uuid import UUID

import pytest

from job_search_helper import ats, shared_boards
from job_search_helper.company_events import source_revision
from job_search_helper.engine import Engine, State
from job_search_helper.integration_release import (
    config_tree_digest, dependency_manifest_digest, digest, source_tree_digest,
)
from job_search_helper.repository import MemoryRepository


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'dev/pre_release_validation/validate_candidate.py'
BOOTSTRAP = ROOT / 'release_admission_bootstrap.py'
FORTERRA = 'https://ats.rippling.com/forterra/jobs'
PDW = 'https://ats.rippling.com/pdwcareers/jobs'
FORTERRA_CAREERS = 'https://www.forterra.com/careers'
PDW_FIXTURE_CAREERS = 'https://pdw-employer.example.test/careers'


def posting(sequence):
    return {'id': str(UUID(int=sequence)), 'name': f'Integration Engineer {sequence}'}


def hydrated(props):
    payload = json.dumps({'props': {'pageProps': props}}, sort_keys=True)
    return f'<script type="application/json" id="__NEXT_DATA__">{payload}</script>'


def listing(board, items, page=0, *, total=None):
    slug = board.split('/')[-2]
    filters = {'searchQuery': '', 'departments': [], 'workplaceType': None, 'country': '',
               'state': '', 'city': '', 'page': page, 'pageSize': 20}
    total = len(items) if total is None else total
    return hydrated({'apiData': {'jobBoard': {'slug': slug}, 'jobBoardSlug': slug}, 'dehydratedState': {
        'queries': [{'queryKey': ['board', slug, 'job-posts', True, filters, 'en-US'], 'state': {'data': {
            'page': page, 'pageSize': 20, 'totalItems': total, 'totalPages': (total + 19) // 20,
            'items': items[page * 20:(page + 1) * 20],
        }}}],
    }})


def detail(board, item):
    slug = board.split('/')[-2]
    return hydrated({'apiData': {'jobBoard': {'slug': slug}, 'workLocations': ['Virginia'], 'jobPost': {
        'uuid': item['id'], 'name': item['name'], 'url': board + '/' + item['id'], 'unlistedFromSearch': False,
        'description': {
            'company': '<p>Build &amp; support field systems.</p>',
            'role': f'<p>{item["name"]} verifies the motion controller.</p><ul><li>Record all test results.</li>'
                    '<li>Document constraints &amp; calibrate sensors before release.</li></ul>',
        },
    }}})


def response(body, status=200):
    return {'status': status, 'body': body}


def make_case(role, company_id, name, source, authority, board, reads):
    responses = {}
    for entries in reads:
        for page in range(max(1, (len(entries) + 19) // 20)):
            url = board + (f'?page={page}' if page else '')
            responses.setdefault(url, []).append(response(listing(board, entries, page)))
        for entry in entries:
            url = f'{board}/{entry["id"]}'
            responses.setdefault(url, [response(detail(board, entry))])
    return {
        'role': role, 'company': {'Company ID': company_id, 'Company': name, 'Company Status': 'Active',
                                  'Official Careers URL': source, 'ATS / Source': 'Rippling'},
        'authority': {'url': authority, 'body': f'<html><iframe src="{board}"></iframe></html>'},
        'board_url': board, 'responses': responses,
    }


def make_capture(*, forterra_reads=None):
    if forterra_reads is None:
        # Preserve the provider's 20/20/20/2 boundary from the reviewed Forterra shape.
        forterra_reads = [[posting(n) for n in range(1, 63)]] * 2
    return {'schema': 'rippling-fixture-capture-v1', 'cases': [
        make_case('target', 'COMP-0066', 'Forterra', FORTERRA_CAREERS, FORTERRA_CAREERS, FORTERRA, forterra_reads),
        make_case('regression', 'COMP-0178', 'PDW', PDW, PDW_FIXTURE_CAREERS, PDW, [[posting(101)]] * 2),
    ]}


def write_bundle(directory, capture, candidate=ROOT):
    capture_path = directory / 'capture.json'
    raw = (json.dumps(capture, sort_keys=True, separators=(',', ':')) + '\n').encode()
    capture_path.write_bytes(raw)
    scope = []
    for case in make_capture()['cases']:
        company = case['company']
        scope.append({'role': case['role'], 'company_id': company['Company ID'], 'company': company['Company'],
                      'company_row_sha256': digest(company), 'source_revision': source_revision(company),
                      'authority_url': case['authority']['url'], 'board_url': case['board_url']})
    pin = {'schema': 'company-candidate-validation-pin-v1', 'candidate': {
        'source_manifest_sha256': source_tree_digest(candidate),
        'config_sha256': config_tree_digest(candidate),
        'dependency_manifest_sha256': dependency_manifest_digest(candidate),
    }, 'capture_sha256': sha256(raw).hexdigest(), 'measurement_tool_sha256': sha256(BOOTSTRAP.read_bytes()).hexdigest(),
        'scope': scope}
    pin_path = directory / 'pin.json'
    pin_path.write_text(json.dumps(pin, sort_keys=True) + '\n')
    return pin_path, capture_path, pin


def invoke(pin_path, capture_path, candidate=ROOT):
    completed = subprocess.run([sys.executable, '-I', '-S', '-B', str(SCRIPT),
                                '--candidate-root', str(candidate), '--measurement-tool', str(BOOTSTRAP),
                                '--pin', str(pin_path), '--capture', str(capture_path)],
                               capture_output=True, text=True, timeout=20, check=False)
    assert not completed.stderr, completed.stderr
    return completed.returncode, json.loads(completed.stdout)


def replay(tmp_path, capture=None, candidate=ROOT):
    pin_file, path, pin = write_bundle(tmp_path, capture or make_capture(), candidate)
    code, receipt = invoke(pin_file, path, candidate)
    return code, receipt, pin


def test_candidate_pin_and_regression_receipt(tmp_path):
    code, receipt, pin = replay(tmp_path)
    assert code == 0, receipt
    assert receipt['result'] == 'FIXTURE_PASS' and receipt['evidence_class'] == 'synthetic_fixture'
    for field in ('candidate', 'observed_candidate_before', 'observed_candidate_after',
                  'execution_candidate_before', 'execution_candidate_after'):
        assert receipt[field] == pin['candidate']
    assert receipt['capture_sha256'] == pin['capture_sha256']
    assert receipt['source_revision'] == pin['scope'][0]['source_revision']
    assert receipt['scope_sha256'] == digest(pin['scope'])
    target, regression = receipt['cases']
    assert target['company_id'] == 'COMP-0066' and target['board_url'] == FORTERRA and target['posting_count'] == 62
    assert regression['company_id'] == 'COMP-0178' and regression['board_url'] == PDW and regression['posting_count'] == 1
    assert [read['page_counts'] for read in target['listing_reads']] == [[20, 20, 20, 2]] * 2
    counts = Counter(request['url'] for request in target['board_trace'])
    assert len(counts) == 66 and all(counts[FORTERRA + f'?page={page}'] == 2 for page in range(1, 4))
    assert counts[FORTERRA] == 2 and FORTERRA + '?page=4' not in counts
    assert len(target['posting_evidence_sha256']) == 64
    assert 'calibrate sensors' not in json.dumps(receipt)


@pytest.mark.parametrize('defect, reason', [
    ('foreign-board', 'different board'),
    ('missing-page', 'missing_or_out_of_scope_response'),
    ('missing-detail', 'missing_or_out_of_scope_response'),
    ('foreign-detail', 'detail identity'),
    ('missing-description', 'description'),
    ('unverified-zero', 'explicit valid total'),
    ('wrong-employer', 'single exact Rippling board'),
    ('duplicate-id', 'duplicate_listing_id'),
])
def test_defects_hold_target_and_leave_pdw_observable(tmp_path, defect, reason):
    capture = make_capture()
    target = capture['cases'][0]
    responses = target['responses']
    first_id = posting(1)['id']
    if defect == 'foreign-board':
        responses[FORTERRA][0] = response(listing(PDW, [posting(101)]))
    elif defect == 'missing-page':
        del responses[FORTERRA + '?page=3']
    elif defect == 'missing-detail':
        del responses[FORTERRA + '/' + first_id]
    elif defect == 'foreign-detail':
        responses[FORTERRA + '/' + first_id] = [response(detail(PDW, posting(1)))]
    elif defect == 'missing-description':
        record = responses[FORTERRA + '/' + first_id][0]
        record['body'] = record['body'].replace('"role":', '"summary":')
    elif defect == 'unverified-zero':
        capture = make_capture(forterra_reads=[[], []])
        zero = capture['cases'][0]['responses'][FORTERRA][0]
        zero['body'] = zero['body'].replace('"totalItems": 0', '"totalItems": null')
    elif defect == 'wrong-employer':
        target['authority']['body'] += f'<a href="{PDW}">Other employers</a>'
    else:
        repeated = [posting(n) for n in range(1, 21)] + [posting(1)]
        capture = make_capture(forterra_reads=[repeated, repeated])
    code, receipt, _ = replay(tmp_path, capture)
    assert code == 1 and receipt['result'] == 'HOLD', receipt
    blocked, regression = receipt['cases']
    assert blocked['result'] == 'HOLD' and reason in blocked['reason'], receipt
    assert regression['result'] == 'FIXTURE_PASS' and regression['posting_count'] == 1


@pytest.mark.parametrize('substitution', ['omit-pdw', 'relabel-pdw', 'relabel-forterra', 'replace-pdw-authority'])
def test_new_capture_cannot_change_scope_under_existing_review(tmp_path, substitution):
    capture = make_capture()
    target, regression = capture['cases']
    if substitution == 'omit-pdw':
        capture['cases'].pop()
    elif substitution == 'relabel-pdw':
        regression['company'].update({'Company ID': 'COMP-9999', 'Company': 'Other employer'})
    elif substitution == 'relabel-forterra':
        target['company']['Company'] = 'Other employer'
    else:
        regression['authority']['url'] = 'https://other-employer.example.test/careers'
    code, receipt, _ = replay(tmp_path, capture)
    assert code == 1 and receipt['result'] == 'HOLD', receipt
    if substitution == 'omit-pdw':
        assert not receipt['cases'] and receipt['reason'] == 'reviewed_forterra_and_pdw_required'
    else:
        blocked, = (row for row in receipt['cases'] if row['result'] == 'HOLD')
        assert blocked['reason'] == 'company_row_outside_reviewed_scope' and 'board_trace' not in blocked


def test_explicit_zero_is_scoped_and_reread(tmp_path):
    code, receipt, _ = replay(tmp_path, make_capture(forterra_reads=[[], []]))
    assert code == 0, receipt
    target, _ = receipt['cases']
    assert target['posting_count'] == 0 and target['zero_evidence'] == 'scoped_explicit_zero_with_reread'
    assert [entry['total'] for entry in target['listing_reads']] == [0, 0]
    assert {entry['url'] for entry in target['board_trace']} == {FORTERRA}


@pytest.mark.parametrize('element', ['template', 'noscript'])
def test_inert_zero_markup_does_not_establish_opening_count(tmp_path, element):
    capture = make_capture(forterra_reads=[[], []])
    for entry in capture['cases'][0]['responses'][FORTERRA]:
        entry['body'] = f'<h1>Service unavailable</h1><{element}>{entry["body"]}</{element}>'
    code, receipt, _ = replay(tmp_path, capture)
    assert code == 1, receipt
    assert 'complete Rippling hydration script' in receipt['cases'][0]['reason']
    assert 'zero_evidence' not in receipt['cases'][0]


def test_iframe_srcdoc_does_not_establish_authority(tmp_path):
    capture = make_capture()
    capture['cases'][0]['authority']['body'] = f'<iframe src="{FORTERRA}" srcdoc="Board unavailable"></iframe>'
    code, receipt, _ = replay(tmp_path, capture)
    assert code == 1 and 'single exact Rippling board' in receipt['cases'][0]['reason'], receipt


def test_inert_role_is_not_a_full_description(tmp_path):
    capture = make_capture()
    first_detail = capture['cases'][0]['responses'][FORTERRA + '/' + posting(1)['id']][0]
    begin = first_detail['body'].index('"role": "') + len('"role": "')
    end = first_detail['body'].index('"', begin)
    body = first_detail['body']
    first_detail['body'] = f'{body[:begin]}<template>{body[begin:end]}</template>{body[end:]}'
    code, receipt, _ = replay(tmp_path, capture)
    assert code == 1 and 'no visible text' in receipt['cases'][0]['reason'], receipt


def test_verified_loader_uses_measured_bytes_after_source_replacement(tmp_path):
    spec = spec_from_file_location('candidate_validation', SCRIPT)
    validator = module_from_spec(spec)
    spec.loader.exec_module(validator)
    package = tmp_path / 'src/job_search_helper'
    package.mkdir(parents=True)
    path = package / '__init__.py'
    path.write_text('result = "pinned bytes"\n')
    loader = validator.VerifiedPackage(package, source_tree_digest(tmp_path))
    original = sha256(path.read_bytes()).hexdigest()
    path.write_text('raise RuntimeError("unreviewed bytes")\n')
    spec = loader.find_spec('job_search_helper')
    module = module_from_spec(spec)
    loader.exec_module(module)
    assert module.result == 'pinned bytes'
    assert loader.loaded == {'__init__.py': original}


def test_bounded_reread_reconciles_a_changing_listing(tmp_path):
    capture = make_capture(forterra_reads=[[posting(1)], [posting(2)], [posting(2)]])
    code, receipt, _ = replay(tmp_path, capture)
    assert code == 0, receipt
    original, changed, stable = receipt['cases'][0]['listing_reads']
    assert original['items_sha256'] != changed['items_sha256'] == stable['items_sha256']
    assert receipt['cases'][0]['posting_count'] == 1


def test_repeatedly_changing_inventory_holds(tmp_path):
    capture = make_capture(forterra_reads=[[posting(n)] for n in range(1, 6)])
    # The final unstable listing is observed at the attempt limit, so its detail cannot be read.
    del capture['cases'][0]['responses'][FORTERRA + '/' + posting(5)['id']]
    code, receipt, _ = replay(tmp_path, capture)
    assert code == 1 and receipt['cases'][0]['reason'] == 'inventory_did_not_stabilize', receipt


def test_capture_substitution_fails_before_candidate_dispatch(tmp_path):
    pin_file, capture_file, _ = write_bundle(tmp_path, make_capture())
    capture_file.write_bytes(capture_file.read_bytes() + b' ')
    code, receipt = invoke(pin_file, capture_file)
    assert code == 1 and receipt['reason'] == 'capture_digest_mismatch' and receipt['cases'] == []


@pytest.mark.parametrize('changed', ['source', 'configuration', 'dependency'])
def test_candidate_change_fails_before_dispatch(tmp_path, changed):
    candidate = tmp_path / 'candidate'
    candidate.mkdir()
    shutil.copytree(ROOT / 'src', candidate / 'src', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(ROOT / 'pyproject.toml', candidate)
    pin_file, capture_file, pin = write_bundle(tmp_path, make_capture(), candidate)
    if changed == 'source':
        # A new initializer would raise if the validator imports before measuring.
        (candidate / 'src/job_search_helper/__init__.py').write_text('raise RuntimeError("unapproved import")\n')
    elif changed == 'configuration':
        (candidate / '.storage-backend').write_text('sqlite\n')
    else:
        (candidate / 'requirements.lock').write_text('# changed dependency\n')
    code, receipt = invoke(pin_file, capture_file, candidate)
    assert code == 1 and receipt['reason'] == 'candidate_pin_mismatch_before_dispatch', receipt
    assert receipt['observed_candidate_before'] != pin['candidate'] and not receipt['cases']


def test_both_cases_enter_normal_company_only_engine_dispatch(tmp_path, monkeypatch):
    """Exercise the ordinary scoped cycle with only synthetic transport and stores."""
    spec = spec_from_file_location('rippling_capture', SCRIPT.with_name('rippling_capture.py'))
    oracle = module_from_spec(spec)
    spec.loader.exec_module(oracle)
    spec = spec_from_file_location('candidate_validation', SCRIPT)
    validator = module_from_spec(spec)
    spec.loader.exec_module(validator)

    def deny_network(*args, **kwargs):
        pytest.fail('unexpected network attempt')

    monkeypatch.setattr(socket.socket, 'connect', deny_network)
    monkeypatch.setattr(socket, 'getaddrinfo', deny_network)
    cases = make_capture()['cases']
    for case in cases:
        board = case['board_url']
        replay = validator.BoardReplay(board, case['responses'], ats.HTTPResponse, oracle)
        factories = []

        class Transport:
            def __new__(cls, routed_board):
                factories.append(routed_board.url)
                assert routed_board.url == board
                return replay

        monkeypatch.setattr(shared_boards, 'Transport', Transport)
        company_id = case['company']['Company ID']
        repo = MemoryRepository({'Companies': [c['company'].copy() for c in cases]})
        with closing(State(tmp_path / f'{company_id}.db')) as state:
            engine = Engine(repo, state)
            cycle_id = engine.start_cycle(company_ids=[company_id], new_scan_request={
                'mode': 'company-only', 'request_id': 'validation-' + company_id,
                'company_ids': [company_id], 'source_revision': source_revision(case['company']), 'start_last': [],
            })
            engine.resume(cycle_id)
            cycle = state.cycle(cycle_id)
            assert cycle['all'] is False and list(cycle['companies']) == [company_id]
            assert cycle['start_request_id'] == 'validation-' + company_id
            assert cycle['companies'][company_id]['inventory_status'] == 'complete'
        assert factories == [board]
        expected = replay.expected_jobs()
        desired = 62 if company_id == 'COMP-0066' else 1
        assert len(expected) == desired
        evidence = repo.read('Job Evidence')
        assert len(evidence) == desired
        assert {row['Job Description'] for row in evidence} == {row['description'] for row in expected.values()}
