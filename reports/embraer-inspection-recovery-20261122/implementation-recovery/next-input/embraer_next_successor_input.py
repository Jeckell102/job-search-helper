"""Read-only, approval-pinned #03 Embraer successor enrollment input."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import stat

REQUEST = 'operator-embraer-20261122-03'
PREVIOUS_REQUEST = 'operator-embraer-20261122-02'
PREVIOUS_BASELINE = 'df0a9c5461e0a46965757499a4f20abadc46f74d99313b9c018977cfe6868369'
EXPECTED_TEST_SHA256 = 'c029561b133971409ba0285d90e5f4ed51f26246ac0984026ffdbfe4f299cc9d'
PREDECESSOR = {
    'predecessor_outcome_id': 'OUT-f5084fdec013f314e5353c0c',
    'predecessor_repair_key': 'ffef857a2e6ee4f718a44e9c79d158e4550c2823004432a1515e6354bb7e3360',
    'predecessor_task_id': 'WRAP-289593fcc0',
    'predecessor_task_state_sha256': '0bdfb4ba6e226e8082148cb77d92a66faf650fa9fb5ee1b61cd4c35d9e8d2bb3',
    'paired_receipt_sha256': '69842a9e33a21eb43476d7fd66b0b7836c6d1811ea18de3a8c2fe7c992526c34',
}
FIELDS = frozenset({'schema','request_id','request_sha256','outcome_id','source_manifest_sha256',
                    'baseline_sha256','baseline_test_sha256','withdrawal_path','withdrawal_sha256',
                    *PREDECESSOR,'failure_fingerprint'})


def _physical(path, private=False):
    path = Path(path)
    if (not path.is_absolute() or path.resolve(strict=True) != path or not path.is_file() or path.stat().st_nlink != 1
            or private and stat.S_IMODE(path.stat().st_mode) != 0o600):
        raise ValueError('Next successor custody differs.')
    return path


def _approval(path, digest):
    raw = _physical(path, private=True).read_bytes()
    if not isinstance(digest, str) or sha256(raw).hexdigest() != digest:
        raise ValueError('Next successor approval pin differs.')
    value = json.loads(raw)
    if (not isinstance(value, dict) or set(value) != FIELDS or value.get('schema') != 'embraer-next-successor-input-v1'
            or value.get('request_id') != REQUEST or any(not isinstance(value[k], str) for k in FIELDS)
            or any(not re.fullmatch(r'[0-9a-f]{64}', value[k]) for k in FIELDS
                   if k.endswith('sha256') or k in ('request_sha256','failure_fingerprint'))
            or not re.fullmatch(r'OUT-[0-9a-f]{24}', value['outcome_id'])
            or any(value[k] != v for k,v in PREDECESSOR.items())):
        raise ValueError('Next successor approval is not exact.')
    return value


def read_operator_embraer_next_successor_enrollment(*, state_root, wrapper_base, approval_path, approval_sha256,
        expected_source_manifest_sha256, original_reader, repository_factory, source_reader, baseline_files, baseline_binding):
    approval = _approval(approval_path, approval_sha256)
    root, wrapper = Path(state_root), Path(wrapper_base)
    if root.resolve(strict=True) != root or wrapper.resolve(strict=True) != wrapper or root != root.parent / '.state':
        raise ValueError('Canonical application roots are required.')
    if approval['source_manifest_sha256'] != expected_source_manifest_sha256:
        raise ValueError('Next source manifest approval differs.')
    captured=[]
    def capture(repository, record, request_sha256):
        proof=source_reader(repository, record, request_sha256); captured.append((record,proof)); return proof
    selected, outcome_id = original_reader(state_root=root, request_id=REQUEST, request_sha256=approval['request_sha256'],
        expected_source_manifest_sha256=expected_source_manifest_sha256, repository_factory=repository_factory, source_reader=capture)
    from coordinator_store import canonical_scrape_outcome
    if len(captured) != 1:
        raise ValueError('Next successor source is ambiguous.')
    record=canonical_scrape_outcome(captured[0][0])
    if (record != captured[0][0] or outcome_id != approval['outcome_id'] or record['outcome_id'] != approval['outcome_id']
            or record['failure_fingerprint'] != approval['failure_fingerprint'] or selected.get('request_id') != REQUEST
            or selected.get('request_sha256') != approval['request_sha256']):
        raise ValueError('Next successor source differs.')
    baseline = wrapper/'pilot-bases'/('embraer-'+approval['baseline_sha256'])
    if baseline.resolve(strict=True) != baseline or baseline.is_symlink() or not baseline.is_dir():
        raise ValueError('Next successor baseline custody differs.')
    manifest=baseline_files(baseline)
    prior = wrapper/'pilot-bases'/('embraer-'+PREVIOUS_BASELINE)
    if (prior.resolve(strict=True) != prior or prior.is_symlink() or not prior.is_dir()
            or baseline_binding(manifest)['digest'] != approval['baseline_sha256']
            or approval['baseline_test_sha256'] != EXPECTED_TEST_SHA256
            or manifest.get('tests/test_embraer_typed_defect.py') != EXPECTED_TEST_SHA256
            or baseline_binding(baseline_files(prior))['digest'] != PREVIOUS_BASELINE
            or {path for path in set(manifest)|set(baseline_files(prior))
                if manifest.get(path) != baseline_files(prior).get(path)} != {'tests/test_embraer_typed_defect.py'}):
        raise ValueError('Next successor baseline differs.')
    withdrawal=_physical(approval['withdrawal_path'], private=True)
    if sha256(withdrawal.read_bytes()).hexdigest() != approval['withdrawal_sha256']:
        raise ValueError('Previous withdrawal differs.')
    withdrawn=json.loads(withdrawal.read_bytes())
    owner_path = root/'operator-company-requests/embraer-pilot'/(sha256(PREVIOUS_REQUEST.encode()).hexdigest()+'.json')
    if (withdrawn.get('state') != 'EMBRAER_PILOT_WITHDRAWN' or withdrawn.get('task_id') != PREDECESSOR['predecessor_task_id']
            or withdrawn.get('outcome_id') != PREDECESSOR['predecessor_outcome_id']
            or withdrawn.get('owner_record') != str(owner_path)):
        raise ValueError('Previous withdrawal is not terminal.')
    owner=json.loads(_physical(owner_path, private=True).read_bytes())
    enrollment=owner.get('enrollment')
    required_enrollment={'request_id','source_revision','request_sha256','shared_boards_sha256','ats_sha256','baseline_sha256','successor'}
    if (set(owner) != {'schema','enrollment','outcome_id','disarm_receipts'}
            or owner.get('schema') != 'embraer-operator-pilot-enrollment-v1'
            or not isinstance(enrollment, dict) or set(enrollment) != required_enrollment
            or enrollment.get('request_id') != PREVIOUS_REQUEST
            or enrollment.get('request_sha256') != 'bea920fe5fbea9382a180bbffd4534dd4ac7dc7608b5a0c7a4021eec11dd4e4b'
            or enrollment.get('baseline_sha256') != PREVIOUS_BASELINE
            or enrollment.get('source_revision') != selected.get('source_revision')
            or owner.get('outcome_id') != PREDECESSOR['predecessor_outcome_id']
            or owner.get('disarm_receipts') != {'sender_receipt_sha256': PREDECESSOR['paired_receipt_sha256'],
                                                'receiver_receipt_sha256': PREDECESSOR['paired_receipt_sha256']}):
        raise ValueError('Previous owner receipt differs.')
    db=_physical(wrapper/'tasks/tasks.sqlite3')
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as con:
        controls={key:json.loads(value) for key,value in con.execute('SELECT key,value FROM settings')}
        task=con.execute('SELECT state FROM tasks WHERE id=?',(PREDECESSOR['predecessor_task_id'],)).fetchone()
        pair=con.execute('SELECT receipt FROM scrape_outcome_delivery_receipts WHERE consumer=? AND outcome_id=?',('repair-coordinator',PREDECESSOR['predecessor_outcome_id'])).fetchone()
        repair=con.execute('SELECT payload FROM repair_intake WHERE repair_key=?',(PREDECESSOR['predecessor_repair_key'],)).fetchone()
        old=canonical_scrape_outcome(json.loads(repair[0])) if repair else None
        if (controls.get('queue_enabled',True) or controls.get('campaign_enabled',False) or controls.get('autopilot_enabled',False)
                or controls.get('pilot_task') is not None or not task or old is None
                or old['outcome_id'] != PREDECESSOR['predecessor_outcome_id'] or old['failure_fingerprint'] != approval['failure_fingerprint']
                or sha256(json.dumps(json.loads(task[0]),sort_keys=True,separators=(',',':')).encode()).hexdigest() != PREDECESSOR['predecessor_task_state_sha256']
                or not pair or sha256(pair[0].encode()).hexdigest() != PREDECESSOR['paired_receipt_sha256']):
            raise ValueError('Previous stopped owner differs.')
    return {**selected, 'baseline_sha256': approval['baseline_sha256'], 'successor': {
        'outcome_id': approval['outcome_id'], **{key: approval[key] for key in PREDECESSOR if key != 'paired_receipt_sha256'},
        'failure_fingerprint': approval['failure_fingerprint']}}, outcome_id
