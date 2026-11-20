"""Check the narrow authority policies and replay an optional private specimen."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import os
import re

import pytest

from test_pre_release_candidate_validation import invoke, make_capture, write_bundle
from rippling_capture import CaptureError
from rippling_public_authority import (
    FORTERRA_BOARD, FORTERRA_CAREERS, PDW_ALIAS, PDW_BOARD, PDW_CAREERS, check_public_authority,
)


MANIFEST_SHA = '4b724ffead928ea1678e594eddfb4d934ee4139279e661e783ed7aa3397e55ce'
EMPLOYER_OK = 'HTTP/2 200 \r\nContent-Type: text/html\r\n\r\n'
REDIRECT_OK = 'HTTP/2 308 \r\nLocation: /pdwcareers/jobs\r\n\r\n'


def pdw_authority():
    body = f'<main><a href="{PDW_BOARD}">Careers</a><a href="{PDW_ALIAS}">Browse careers</a></main>'
    return {'url': PDW_CAREERS, 'headers': EMPLOYER_OK, 'body': body,
            'redirect': {'url': PDW_ALIAS, 'headers': REDIRECT_OK}}


@pytest.mark.parametrize('matching_refresh', [False, True])
def test_pdw_normalizes_only_the_independently_captured_exact_alias(matching_refresh):
    authority = pdw_authority()
    if matching_refresh:
        authority['redirect']['headers'] = REDIRECT_OK[:-2] + 'Refresh: 0;url=/pdwcareers/jobs\r\n\r\n'
    witness = check_public_authority('COMP-0178', PDW_BOARD, authority)
    assert witness['redirect'] == {
        'url': PDW_ALIAS, 'status': 308, 'location': '/pdwcareers/jobs', 'canonical_url': PDW_BOARD,
        'headers_sha256': sha256(authority['redirect']['headers'].encode()).hexdigest(),
    }


@pytest.mark.parametrize('value', [
    '/forterra/jobs', '/pdwcareers/jobs?x=1', '/pdwcareers/jobs#open', '/pdwcareers/jobs/',
    '//ats.rippling.com/pdwcareers/jobs', 'https://ats.rippling.com/pdwcareers/jobs',
    'https://other.example/pdwcareers/jobs', '/pdwcareers/./jobs', '/pdwcareers/%6aobs',
    '/pdwcareers/jobs, /pdwcareers/jobs', '/pdwcareers/jobs\r', '',
])
def test_pdw_holds_unapproved_location_forms(value):
    authority = pdw_authority()
    authority['redirect']['headers'] = REDIRECT_OK.replace('/pdwcareers/jobs', value)
    with pytest.raises(CaptureError):
        check_public_authority('COMP-0178', PDW_BOARD, authority)


@pytest.mark.parametrize('headers', [
    'HTTP/2 200 \r\nLocation: /pdwcareers/jobs\r\n\r\n',
    'HTTP/2 301 \r\nLocation: /pdwcareers/jobs\r\n\r\n',
    'HTTP/2 302 \r\nLocation: /pdwcareers/jobs\r\n\r\n',
    'HTTP/2 308 \r\nDate: ignored\r\n\r\n',
    'HTTP/2 308 \r\nLocation: /pdwcareers/jobs\r\nRefresh: 0;url=/other/jobs\r\n\r\n',
    'HTTP/2 308 \r\nLocation: /pdwcareers/jobs\r\nRefresh: 0;url=/pdwcareers/jobs\r\n'
    'Refresh: 0;url=/pdwcareers/jobs\r\n\r\n',
    'HTTP/2 308 \r\nLocation: /pdwcareers/jobs\r\nlOcAtIoN: /pdwcareers/jobs\r\n\r\n',
    'HTTP/2 308 \r\nLocation: /pdwcareers/jobs\r\n /forged/path\r\n\r\n',
    'HTTP/2 103 \r\nLocation: /pdwcareers/jobs\r\n\r\nHTTP/2 308 \r\n\r\n',
    REDIRECT_OK + EMPLOYER_OK,
    REDIRECT_OK.replace('\r\n', '\n'),
])
def test_pdw_holds_ambiguous_or_unobserved_redirect_headers(headers):
    authority = pdw_authority()
    authority['redirect']['headers'] = headers
    with pytest.raises(CaptureError):
        check_public_authority('COMP-0178', PDW_BOARD, authority)


@pytest.mark.parametrize('alias', [
    'http://ats.rippling.com/pdwcareers', 'https://ats.rippling.com:443/pdwcareers',
    'https://user@ats.rippling.com/pdwcareers', 'https://ats.rippling.com./pdwcareers',
    'https://ats.rippling.com.example/pdwcareers', 'https://ats.rippling.com/pdwcareers?source=careers',
])
def test_pdw_rejects_nonexact_alias_request_or_anchor(alias):
    authority = pdw_authority()
    authority['redirect']['url'] = alias
    with pytest.raises(CaptureError):
        check_public_authority('COMP-0178', PDW_BOARD, authority)
    authority = pdw_authority()
    authority['body'] = authority['body'].replace(f'href="{PDW_ALIAS}"', f'href="{alias}"')
    with pytest.raises(CaptureError):
        check_public_authority('COMP-0178', PDW_BOARD, authority)


@pytest.mark.parametrize('context', ['template', 'noscript', 'textarea', 'iframe', 'hidden', 'display:none', 'dialog', 'details', 'canvas'])
def test_pdw_does_not_use_inert_alias_anchor(context):
    authority = pdw_authority()
    alias_anchor = f'<a href="{PDW_ALIAS}">Browse careers</a>'
    if context == 'hidden':
        replacement = f'<div hidden>{alias_anchor}</div>'
    elif context == 'display:none':
        replacement = f'<div style="display: none !important">{alias_anchor}</div>'
    else:
        replacement = f'<{context}>{alias_anchor}</{context}>'
    authority['body'] = authority['body'].replace(alias_anchor, replacement)
    with pytest.raises(CaptureError):
        check_public_authority('COMP-0178', PDW_BOARD, authority)


def test_public_authority_requires_exact_employer_and_no_employer_redirect():
    authority = pdw_authority()
    for url in ('https://pdw.ai/careers', PDW_CAREERS + '?from=footer', PDW_CAREERS + '#open'):
        with pytest.raises(CaptureError):
            check_public_authority('COMP-0178', PDW_BOARD, {**authority, 'url': url})
    with pytest.raises(CaptureError):
        check_public_authority('COMP-0178', PDW_BOARD, {**authority, 'redirect': None})
    redirected = EMPLOYER_OK.replace('Content-Type:', 'Location:')
    with pytest.raises(CaptureError):
        check_public_authority('COMP-0178', PDW_BOARD, {**authority, 'headers': redirected})


def test_forterra_rejects_similar_script_with_approved_looking_literals():
    body = ('<div id="rr-job-board-forterra"></div><div id="rr-job-board-gotenna"></div>'
            '<script>var containerId = "rr-job-board-forterra"; var boardId = "forterra";</script>')
    with pytest.raises(CaptureError):
        check_public_authority('COMP-0066', FORTERRA_BOARD, {
            'url': FORTERRA_CAREERS, 'headers': EMPLOYER_OK, 'body': body, 'redirect': None,
        })


@pytest.fixture(scope='module')
def private_capture():
    folder = os.environ.get('JSH_PRIVATE_PUBLIC_CAPTURE_DIR')
    if not folder:
        pytest.skip('Set JSH_PRIVATE_PUBLIC_CAPTURE_DIR to the separately preserved private corpus')
    root = Path(folder)
    raw_manifest = (root / 'SHA256SUMS').read_bytes()
    assert sha256(raw_manifest).hexdigest() == MANIFEST_SHA

    def read_verified(name):
        expected = hashes[name]
        raw = (root / name).read_bytes()
        assert sha256(raw).hexdigest() == expected, f'Private evidence hash mismatch for {name}'
        return raw

    hashes = {name: value for value, name in (line.split('  ', 1) for line in raw_manifest.decode().splitlines())}
    observations = json.loads(read_verified('public-observations.json'))
    capture = make_capture()
    capture['schema'] = 'rippling-public-capture-v1'
    for case, name in zip(capture['cases'], ('forterra', 'pdw'), strict=True):
        evidence = observations['companies'][name]
        authority = evidence['authority']
        redirect = None
        if name == 'pdw':
            redirect = {'url': PDW_ALIAS, 'headers': read_verified('pdw-alias.headers').decode('latin-1')}
        case['authority'] = {'url': authority['official_url'], 'body': read_verified(f'{name}-careers.html').decode(),
                             'headers': read_verified(f'{name}-careers.headers').decode('latin-1'), 'redirect': redirect}
        responses = {}
        for phase, key in (('list', 'initial'), ('reread', 'reread')):
            for index, entry in enumerate(evidence[key]):
                raw = read_verified(f'{name}-{phase}-{index}.html')
                responses.setdefault(entry['url'], []).append({'status': entry['status'], 'body': raw.decode()})
        for ident, entry in evidence['detail_outcomes'].items():
            assert re.fullmatch(r'[0-9a-f-]{36}', ident)
            raw = read_verified(f'{name}-detail-{ident}.html')
            responses[entry['url']] = [{'status': entry['status'], 'body': raw.decode()}]
        case['responses'] = responses
    return capture


def test_original_forterra_authority_distinguishes_sibling_board(private_capture):
    authority = private_capture['cases'][0]['authority']
    witness = check_public_authority('COMP-0066', FORTERRA_BOARD, authority)
    assert witness['widgets']['approved']['tenant'] == 'forterra'
    assert witness['widgets']['excluded']['tenant'] == 'gotenna-inc'
    with pytest.raises(CaptureError):
        check_public_authority('COMP-0066', 'https://ats.rippling.com/gotenna-inc/jobs', authority)


@pytest.mark.parametrize('mutation', [
    'hidden-mount', 'duplicate-mount', 'changed-script', 'sibling-only', 'foreign-link', 'late-mount',
    'refresh', 'self-closing-template', 'self-closing-script', 'unexpected-board-variable',
    'commented-property', 'commented-value', 'escaped-style',
])
def test_original_forterra_authority_holds_changed_or_ambiguous_widget(private_capture, mutation):
    authority = private_capture['cases'][0]['authority'].copy()
    body = authority['body']
    mount = '<div id="rr-job-board-forterra"></div>'
    assert mount in body
    if mutation == 'hidden-mount':
        body = body.replace(mount, f'<textarea>{mount}</textarea>', 1)
    elif mutation == 'duplicate-mount':
        body = body.replace(mount, mount + mount, 1)
    elif mutation == 'changed-script':
        body = body.replace("var boardId = 'forterra'", "var boardId = 'gotenna-inc'", 1)
    elif mutation == 'sibling-only':
        body = body.replace(mount, '', 1)
    elif mutation == 'foreign-link':
        body = body.replace(mount, mount + '<a href="https://ats.rippling.com/gotenna-inc/jobs">Sibling</a>', 1)
    elif mutation == 'late-mount':
        body = body.replace(mount, '', 1).replace('</body>', mount + '</body>', 1)
    elif mutation == 'refresh':
        body = body.replace(mount, '<meta http-equiv="refresh" content="0;url=/other">' + mount, 1)
    elif mutation == 'self-closing-template':
        body = body.replace(mount, '<template/>' + mount, 1)
    elif mutation == 'self-closing-script':
        body = body.replace(mount, '<script/>' + mount, 1)
    elif mutation == 'unexpected-board-variable':
        body = body.replace(mount, mount + "<script>var boardId = 'other';</script>", 1)
    else:
        style = {'commented-property': 'display/**/:none', 'commented-value': 'display:/**/none',
                 'escaped-style': r'd\69splay:none'}[mutation]
        body = body.replace(mount, f'<div style="{style}">{mount}</div>', 1)
    assert body != authority['body']
    authority['body'] = body
    with pytest.raises(CaptureError):
        check_public_authority('COMP-0066', FORTERRA_BOARD, authority)


@pytest.mark.parametrize('bad_redirect', [False, True])
def test_full_original_employer_and_provider_replay(private_capture, tmp_path, bad_redirect):
    capture = deepcopy(private_capture) if bad_redirect else private_capture
    if bad_redirect:
        capture['cases'][1]['authority']['redirect']['headers'] = REDIRECT_OK.replace('/pdwcareers/', '/forterra/')
    pin_path, capture_path, pin = write_bundle(tmp_path, capture)
    pin['scope'][1]['authority_url'] = PDW_CAREERS
    pin_path.write_text(json.dumps(pin, sort_keys=True) + '\n')
    status, receipt = invoke(pin_path, capture_path)
    assert receipt['evidence_class'] == 'captured_public' and receipt['release_qualification'] is False
    forterra, pdw = receipt['cases']
    expected = 'PUBLIC_EVIDENCE_ACCEPTED'
    assert forterra['result'] == expected and forterra['posting_count'] == 65
    assert [entry['page_counts'] for entry in forterra['listing_reads']] == [[20, 20, 20, 5]] * 2
    assert forterra['authority']['widgets']['excluded']['tenant'] == 'gotenna-inc'
    if bad_redirect:
        assert status == 1 and receipt['result'] == pdw['result'] == 'HOLD'
        assert 'board_trace' not in pdw
    else:
        assert status == 0 and receipt['result'] == pdw['result'] == expected and pdw['posting_count'] == 33
        assert [entry['page_counts'] for entry in pdw['listing_reads']] == [[20, 13]] * 2
        assert pdw['authority']['redirect']['location'] == '/pdwcareers/jobs'
        assert receipt['execution_candidate_before'] == receipt['execution_candidate_after'] == pin['candidate']
        assert forterra['posting_evidence_sha256'] == 'ce001b011f2dfaf778b4a6980845f8a9af274b8bf635aec3c492b533e32c76b6'
        assert pdw['posting_evidence_sha256'] == 'de34debc1ddce8c16a9df083c7165af4c0b6c5d8fce69f346f1159e21975f4ce'
