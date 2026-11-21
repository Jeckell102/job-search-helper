import json

import pytest

from test_live_employer_authority import PDW_CAREERS, private_capture
from test_pre_release_candidate_validation import digest, invoke, make_capture, source_revision, write_bundle


FULL_CONTROL = 'Performance Drone Works (PDW)'


def pin_case(pin, case):
    company = case['company']
    pin['scope'][1].update(role=case['role'], company=company['Company'],
                           company_id=company['Company ID'], board_url=case['board_url'],
                           authority_url=case['authority']['url'], source_revision=source_revision(company),
                           company_row_sha256=digest(company))


def save_pin(path, pin):
    path.write_text(json.dumps(pin, sort_keys=True) + '\n')


@pytest.mark.parametrize('condition,success,reason', [
    ('fully-pinned', True, None),
    ('old-pin', False, 'company_row_outside_reviewed_scope'),
    ('display-only-pin', False, 'company_row_outside_reviewed_scope'),
    ('wrong-source-revision', False, 'company_row_outside_reviewed_scope'),
    ('substitute-employer', False, 'reviewed_forterra_and_pdw_required'),
    ('substitute-company-id', False, 'reviewed_forterra_and_pdw_required'),
    ('substitute-role', False, 'reviewed_forterra_and_pdw_required'),
    ('substitute-board', False, 'reviewed_forterra_and_pdw_required'),
])
def test_literal_display_name_never_changes_other_pins(tmp_path, condition, success, reason):
    capture = make_capture()
    control = capture['cases'][1]
    old_company = control['company'].copy()
    control['company']['Company'] = FULL_CONTROL
    assert source_revision(control['company']) == source_revision(old_company)
    assert digest(control['company']) != digest(old_company)
    if condition == 'substitute-employer':
        control['company']['Company'] = 'Another named employer'
    elif condition == 'substitute-company-id':
        control['company']['Company ID'] = 'COMP-9999'
    elif condition == 'substitute-role':
        control['role'] = 'target'
    elif condition == 'substitute-board':
        control['board_url'] = 'https://ats.rippling.com/different-control/jobs'
    pin_path, capture_path, pin = write_bundle(tmp_path, capture)
    if condition == 'display-only-pin':
        pin['scope'][1]['company'] = FULL_CONTROL
    elif condition != 'old-pin':
        pin_case(pin, control)
    if condition == 'wrong-source-revision':
        pin['scope'][1]['source_revision'] = '0' * 64
    save_pin(pin_path, pin)
    code, receipt = invoke(pin_path, capture_path)
    if success:
        assert code == 0 and receipt['result'] == 'FIXTURE_PASS'
        assert receipt['cases'][1]['company'] == FULL_CONTROL
        assert receipt['cases'][1]['company_row_sha256'] == digest(control['company'])
        assert receipt['execution_candidate_before'] == receipt['execution_candidate_after'] == pin['candidate']
    else:
        assert code == 1 and receipt['result'] == 'HOLD'
        observed = receipt['cases'][1] if receipt['cases'] else receipt
        assert observed['reason'] == reason
        assert 'board_trace' not in observed


def test_repinning_full_company_to_substitute_public_employer_still_refuses(private_capture, tmp_path):
    capture = private_capture
    control = capture['cases'][1]
    assert control['authority']['url'] == PDW_CAREERS
    wrong = 'https://substituted-employer.example.test/careers'
    control['company'].update({'Company': FULL_CONTROL, 'Official Careers URL': wrong})
    control['authority']['url'] = wrong
    pin_path, capture_path, pin = write_bundle(tmp_path, capture)
    pin_case(pin, control)
    save_pin(pin_path, pin)
    code, receipt = invoke(pin_path, capture_path)
    assert code == 1 and receipt['result'] == 'HOLD'
    assert receipt['cases'][1]['reason'] == 'Unexpected public employer or board URL'
    assert 'board_trace' not in receipt['cases'][1]
