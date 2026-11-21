from hashlib import sha256
import json
from pathlib import Path

import pytest

from fresh_operator_enrollment_input import read_fresh_operator_enrollment
from host_server import OperatorAmphenolRecipeEnrollment


READBACK = Path(__file__).parent / 'S5_AMPHENOL_FRESH_SUCCESSOR_NATIVE_READBACK_20261121.json'
READBACK_PIN = '96cf0cbc51de8cd6f5972614ec81e711a8aaf6a9f87a58b6b76e661d5c0d5434'


def write_request(path, value):
    payload = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    path.write_bytes(payload + b'\n')
    return sha256(payload).hexdigest()


@pytest.fixture
def queued(tmp_path):
    request_id = 'operator-amphenol-fixture-fresh'
    readback = json.loads(READBACK.read_bytes())
    identity = {'schema': 'operator-company-scan-request-v1', 'request_id': request_id,
                'company_id': 'COMP-0490', 'source_revision': readback['current_company_source_revision']}
    body = {'mode': 'company-only', 'request_id': request_id, 'company_ids': ['COMP-0490'],
            'source_revision': identity['source_revision'], 'enqueued_at': '2026-11-21T00:00:00Z',
            'start_last': [], 'operator_request': identity}
    queue = tmp_path / 'next-scan.json'
    digest = write_request(queue, body)
    receipts = tmp_path / 'operator-company-requests' / 'receipts'
    receipts.mkdir(parents=True)
    name = sha256(json.dumps({'request_id': request_id}, separators=(',', ':')).encode()).hexdigest()
    receipt = receipts / (name + '.json')
    write_request(receipt, {**identity, 'state': 'REQUEST_WRITTEN', 'request_sha256': digest})
    arguments = {'state_root': tmp_path, 'request_id': request_id, 'native_readback_path': READBACK,
                 'expected_predecessor_sha256': READBACK_PIN}
    return arguments, queue, body, readback


def test_pinned_native_readback_produces_exact_host_enrollment(queued):
    args, _, _, predecessor = queued
    values = read_fresh_operator_enrollment(**args)
    enrollment = OperatorAmphenolRecipeEnrollment.from_process_environment({
        'WRAPPER_AMPHENOL_OPERATOR_RECIPE_ENROLLMENT': json.dumps(values, sort_keys=True, separators=(',', ':')),
    })
    assert enrollment.request_id == args['request_id']
    assert enrollment.predecessor_task_state_sha256 == predecessor['canonical_task_state_sha256']
    assert enrollment.predecessor_repair_key == predecessor['original_repair_key']
    assert enrollment.failure_fingerprint == predecessor['existing_failure_fingerprint']


def test_drift_in_pinned_predecessor_or_request_holds(queued):
    args, queue, body, _ = queued
    with pytest.raises(ValueError, match='readback_pin'):
        read_fresh_operator_enrollment(**{**args, 'expected_predecessor_sha256': '0' * 64})
    write_request(queue, {**body, 'start_last': ['another company']})
    with pytest.raises(ValueError, match='request_binding'):
        read_fresh_operator_enrollment(**args)
