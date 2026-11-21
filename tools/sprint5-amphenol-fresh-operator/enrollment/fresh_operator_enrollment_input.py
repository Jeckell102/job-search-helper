"""Read-only binding of one queued operator request to one retired predecessor."""
import hashlib
import json
from pathlib import Path
import re


_HEX = re.compile(r'[0-9a-f]{64}\Z')
_REQUEST = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{2,127}\Z')
_SCHEMA = 'operator-company-scan-request-v1'


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def _read(path, *, pinned_sha256=None):
    path = Path(path)
    try:
        physical = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError('fresh_operator_enrollment_path') from exc
    if not path.is_absolute() or path.is_symlink() or physical != path:
        raise ValueError('fresh_operator_enrollment_path')
    raw = path.read_bytes()
    if pinned_sha256 is not None and hashlib.sha256(raw).hexdigest() != pinned_sha256:
        raise ValueError('fresh_operator_enrollment_readback_pin')
    value = json.loads(raw)
    if not isinstance(value, dict) or (pinned_sha256 is None and (_canonical(value) + '\n').encode() != raw):
        raise ValueError('fresh_operator_enrollment_json')
    return value


def read_fresh_operator_enrollment(*, state_root, request_id, native_readback_path,
                                   expected_predecessor_sha256):
    """Return canonical non-authorizing enrollment facts or raise a hold.

    The caller supplies physical fixture paths.  This function never queues,
    consumes, edits, or arms anything.
    """
    root = Path(state_root)
    if not root.is_absolute() or root.is_symlink() or root.resolve(strict=True) != root:
        raise ValueError('fresh_operator_enrollment_root')
    if not isinstance(request_id, str) or not _REQUEST.fullmatch(request_id):
        raise ValueError('fresh_operator_enrollment_request')
    request = _read(root / 'next-scan.json')
    receipt_name = hashlib.sha256(_canonical({'request_id': request_id}).encode()).hexdigest() + '.json'
    receipt = _read(root / 'operator-company-requests' / 'receipts' / receipt_name)
    if not isinstance(expected_predecessor_sha256, str) or not _HEX.fullmatch(expected_predecessor_sha256):
        raise ValueError('fresh_operator_enrollment_readback_pin')
    retired = _read(native_readback_path, pinned_sha256=expected_predecessor_sha256)
    identity = request.get('operator_request')
    if (set(request) != {'mode', 'request_id', 'company_ids', 'source_revision', 'enqueued_at', 'start_last',
                         'operator_request'}
            or request.get('mode') != 'company-only' or request.get('request_id') != request_id
            or request.get('start_last') != []
            or request.get('company_ids') != ['COMP-0490'] or not isinstance(identity, dict)
            or identity != {'schema': _SCHEMA, 'request_id': request_id,
                            'company_id': 'COMP-0490', 'source_revision': request.get('source_revision')}
            or receipt.get('schema') != _SCHEMA or any(receipt.get(k) != identity.get(k) for k in identity)
            or receipt.get('state') not in {'REQUEST_WRITTEN', 'REQUEST_ALREADY_DURABLE'}
            or receipt.get('request_sha256') != hashlib.sha256(_canonical(request).encode()).hexdigest()):
        raise ValueError('fresh_operator_enrollment_request_binding')
    required = {'company_id','current_company_source_revision','original_outcome_id','original_repair_key',
                'original_task_id','canonical_task_state_sha256','existing_failure_fingerprint',
                'original_repair_status','original_task_status','original_task_phase','original_task_sessions',
                'original_task_max_sessions','original_task_stop_requested','original_task_unsettled_tool_receipts'}
    if (not required <= set(retired) or retired.get('company_id') != 'COMP-0490'
            or identity['source_revision'] != retired['current_company_source_revision']
            or request_id == 'operator-amphenol-20261121-03'
            or (retired['original_repair_status'], retired['original_task_status'], retired['original_task_phase'],
                retired['original_task_sessions'], retired['original_task_max_sessions'],
                retired['original_task_stop_requested'], retired['original_task_unsettled_tool_receipts'])
               != ('PROMOTED_PAUSED','PAUSED_ERROR','inspect',1,1,False,0)
            or any(not isinstance(retired[k], str) or not _HEX.fullmatch(retired[k])
                   for k in ('current_company_source_revision','original_repair_key','canonical_task_state_sha256','existing_failure_fingerprint'))
            or not re.fullmatch(r'OUT-[0-9a-f]{24}', retired['original_outcome_id'])
            or not re.fullmatch(r'WRAP-[0-9a-f]{10}', retired['original_task_id'])):
        raise ValueError('fresh_operator_enrollment_retired_predecessor')
    return {'request_id': request_id, 'request_sha256': receipt['request_sha256'],
            'source_revision': identity['source_revision'], 'predecessor_outcome_id': retired['original_outcome_id'],
            'predecessor_repair_key': retired['original_repair_key'], 'predecessor_task_id': retired['original_task_id'],
            'predecessor_task_state_sha256': retired['canonical_task_state_sha256'],
            'failure_fingerprint': retired['existing_failure_fingerprint']}
