"""Read-only exact fresh Embraer input; native owner retains all activation authority."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import stat

REQUEST = 'operator-embraer-20261122-02'
REQUEST_SHA256 = 'bea920fe5fbea9382a180bbffd4534dd4ac7dc7608b5a0c7a4021eec11dd4e4b'
OLD_REQUEST = 'operator-embraer-20261122-01'
OLD_REQUEST_SHA256 = '19e7af99bd90d243f9b9f7465d5b6c38455ef99208cade05b7e1cfe5ca7536d2'
BASELINE = 'df0a9c5461e0a46965757499a4f20abadc46f74d99313b9c018977cfe6868369'
OLD_BASELINE = 'dc4b353766486a305a742ec10ada5494885f42967b60adb269db610f01b6063d'
NOTE_SHA256 = '441dce96d66f64c22b22016eb709f68ef2d5f34d71fd6b903ce7ea3320089025'
PAIRED_RECEIPT = 'd3964ed3d2f3d63adb17d0af72ce616a397a3c8e8a62676ed1711b15d5a24afb'
OWNER_PINS = {
    'outcome_id': 'OUT-f5084fdec013f314e5353c0c',
    'predecessor_outcome_id': 'OUT-719882e9ec8b8ad044885426',
    'predecessor_repair_key': '73509fddfc962496895d1a5d8059f15b789246c649ee0dc764da0e3ef9431453',
    'predecessor_task_id': 'WRAP-fbb9ff24d3',
    'predecessor_task_state_sha256': '37f55412454f74eaf344786936d32d70625cce0098aac1e858f3e7b118192971',
    'failure_fingerprint': '54fa33466785019727081b24a415767a6d352d5b55209c1fbb348de1607e8430',
}
EVIDENCE = Path(__file__).resolve().parent.parent / 'successor-evidence'
PIN_FILES = {
    'PROPOSED_SUCCESSOR_OWNER_PINS.json': '23144528dd53afce5c6973106e5684bdbae972d511cc56b36abccd2501cc7057',
    'LIVE_WITHDRAW_RECEIPT.json': '14cae5ff186edbb98cfb16e2055334d364a80099cefb4fb9b84fbcfdfd761186',
}


def _physical(path, *, private=False):
    path = Path(path)
    if (not path.is_absolute() or path.resolve(strict=True) != path or not path.is_file()
            or path.stat().st_nlink != 1 or private and stat.S_IMODE(path.stat().st_mode) != 0o600):
        raise ValueError('Embraer successor input custody differs.')
    return path


def _json(path, *, pin=None, private=False):
    raw = _physical(path, private=private).read_bytes()
    if pin and sha256(raw).hexdigest() != pin:
        raise ValueError('Embraer successor input pin differs.')
    return json.loads(raw)


def read_operator_embraer_successor_enrollment(*, state_root, wrapper_base,
        expected_source_manifest_sha256, original_reader, repository_factory,
        source_reader, baseline_files, baseline_binding):
    """Return six unchanged fields plus one closed successor group; never arm.

    The native caller loads measured original reader/baseline/source functions
    after its unchanged runtime admission, and holds deployment/scraper leases.
    This reader itself opens only existing files and a read-only coordinator DB.
    """
    root, wrapper = Path(state_root), Path(wrapper_base)
    project = root.parent
    if (root.resolve(strict=True) != root or wrapper.resolve(strict=True) != wrapper
            or root != project / '.state' or wrapper != project / 'dev/wrapper-coder'):
        raise ValueError('Canonical native application and wrapper roots are required.')
    if _json(EVIDENCE/'PROPOSED_SUCCESSOR_OWNER_PINS.json', pin=PIN_FILES['PROPOSED_SUCCESSOR_OWNER_PINS.json']) != OWNER_PINS:
        raise ValueError('The exact proposed successor owner differs.')
    withdrawal = _json(EVIDENCE/'LIVE_WITHDRAW_RECEIPT.json', pin=PIN_FILES['LIVE_WITHDRAW_RECEIPT.json'])
    if (withdrawal.get('state') != 'EMBRAER_PILOT_WITHDRAWN'
            or withdrawal.get('task_id') != OWNER_PINS['predecessor_task_id']
            or withdrawal.get('outcome_id') != OWNER_PINS['predecessor_outcome_id']):
        raise ValueError('Original withdrawal is not terminal.')
    captured = []
    def capture(repository, record, request_sha256):
        proof = source_reader(repository, record, request_sha256)
        captured.append((record, proof))
        return proof
    selected, outcome_id = original_reader(state_root=root, request_id=REQUEST,
        request_sha256=REQUEST_SHA256, expected_source_manifest_sha256=expected_source_manifest_sha256,
        repository_factory=repository_factory, source_reader=capture)
    if (len(captured) != 1 or outcome_id != OWNER_PINS['outcome_id']
            or captured[0][0].get('failure_fingerprint') != OWNER_PINS['failure_fingerprint']
            or selected.get('request_id') != REQUEST or selected.get('request_sha256') != REQUEST_SHA256
            or selected.get('baseline_sha256') != OLD_BASELINE):
        raise ValueError('Fresh actual operator source does not match the successor.')
    baseline = wrapper/'pilot-bases'/('embraer-'+BASELINE)
    if baseline.resolve(strict=True) != baseline:
        raise ValueError('The independently approved successor baseline is not physical.')
    manifest = baseline_files(baseline)
    if (baseline_binding(manifest)['digest'] != BASELINE
            or manifest.get('docs/backlog/COMP-0634.md') != NOTE_SHA256):
        raise ValueError('The frozen successor evidence baseline differs.')
    current_manifest = baseline_files(wrapper/'pilot-bases'/('embraer-'+OLD_BASELINE))
    if baseline_binding(current_manifest)['digest'] != OLD_BASELINE:
        raise ValueError('The original reviewed baseline changed.')
    changed = {name for name in set(manifest)|set(current_manifest) if manifest.get(name) != current_manifest.get(name)}
    if changed != {'docs/backlog/COMP-0634.md'}:
        raise ValueError('Successor baseline changed outside its one approved evidence note.')
    old_owner_path = root/'operator-company-requests/embraer-pilot'/(sha256(OLD_REQUEST.encode()).hexdigest()+'.json')
    if withdrawal.get('owner_record') != str(old_owner_path):
        raise ValueError('Withdrawal owner path differs.')
    old_owner = _json(old_owner_path, private=True)
    expected_old = {**selected, 'request_id': OLD_REQUEST, 'request_sha256': OLD_REQUEST_SHA256}
    if (set(old_owner) != {'schema','enrollment','outcome_id','disarm_receipts'}
            or old_owner['schema'] != 'embraer-operator-pilot-enrollment-v1'
            or old_owner['enrollment'] != expected_old
            or old_owner['outcome_id'] != OWNER_PINS['predecessor_outcome_id']
            or old_owner['disarm_receipts'] != {'sender_receipt_sha256': PAIRED_RECEIPT,
                                               'receiver_receipt_sha256': PAIRED_RECEIPT}):
        raise ValueError('Original receipt-owned enrollment has not been withdrawn.')
    with closing(repository_factory(root/'jobs.sqlite3')) as repository:
        rows = repository._outcome_delivery_rows('repair-coordinator', outcome_id=OWNER_PINS['predecessor_outcome_id'])
        if (len(rows) != 1 or rows[0][7] != PAIRED_RECEIPT
                or not isinstance(rows[0][6], str) or sha256(rows[0][6].encode()).hexdigest() != PAIRED_RECEIPT
                or json.loads(rows[0][6]).get('outcome_id') != OWNER_PINS['predecessor_outcome_id']):
            raise ValueError('Original sender receipt changed.')
    database = _physical(wrapper/'tasks/tasks.sqlite3')
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        controls = {k:json.loads(v) for k,v in db.execute('SELECT key,value FROM settings')}
        if (controls.get('queue_enabled',True) or controls.get('campaign_enabled',False)
                or controls.get('autopilot_enabled',False) or controls.get('pilot_task') is not None
                or any(json.loads(row[0]).get('status') in ('RUNNING','QUEUED','PAUSING') for row in db.execute('SELECT state FROM tasks'))
                or db.execute("SELECT 1 FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN') LIMIT 1").fetchone()
                or db.execute('SELECT 1 FROM receipts WHERE result IS NULL LIMIT 1').fetchone()):
            raise ValueError('Successor enrollment requires the stopped single lane.')
        row = db.execute('SELECT state FROM tasks WHERE id=?',(OWNER_PINS['predecessor_task_id'],)).fetchone()
        task = json.loads(row[0]) if row else {}
        if (sha256(json.dumps(task,sort_keys=True,separators=(',',':')).encode()).hexdigest() != OWNER_PINS['predecessor_task_state_sha256']
                or task.get('status') != 'PAUSED' or task.get('stop_requested') is not True
                or task.get('held_repair_key') != OWNER_PINS['predecessor_repair_key']):
            raise ValueError('The original stopped counted task changed.')
        repair = db.execute('SELECT outcome_id,company_id,source_revision,status,task_id,payload FROM repair_intake WHERE repair_key=?',
                            (OWNER_PINS['predecessor_repair_key'],)).fetchone()
        if (repair is None or repair[:5] != (OWNER_PINS['predecessor_outcome_id'], 'COMP-0634',
                                              selected['source_revision'], 'PROMOTED_PAUSED', task['id'])):
            raise ValueError('Original held repair ownership changed.')
        from coordinator_store import canonical_scrape_outcome
        try:
            old_record = json.loads(repair[5])
            old_canonical = canonical_scrape_outcome(old_record)
            new_canonical = canonical_scrape_outcome(captured[0][0])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError('Original or fresh classifier record is not canonical.') from exc
        if (old_record != old_canonical or captured[0][0] != new_canonical
                or old_canonical['outcome_id'] != OWNER_PINS['predecessor_outcome_id']
                or new_canonical['outcome_id'] != OWNER_PINS['outcome_id']
                or old_canonical['failure_fingerprint'] != OWNER_PINS['failure_fingerprint']
                or new_canonical['failure_fingerprint'] != OWNER_PINS['failure_fingerprint']
                or old_canonical['identity'].get('request_id') != OLD_REQUEST
                or new_canonical['identity'].get('request_id') != REQUEST):
            raise ValueError('Original and fresh classifier pins differ.')
        pair = db.execute('SELECT receipt_sha256,receipt FROM scrape_outcome_delivery_receipts WHERE consumer=? AND outcome_id=?',
                          ('repair-coordinator',OWNER_PINS['predecessor_outcome_id'])).fetchone()
        if (not pair or pair[0] != PAIRED_RECEIPT or not isinstance(pair[1], str)
                or sha256(pair[1].encode()).hexdigest() != PAIRED_RECEIPT
                or json.loads(pair[1]).get('outcome_id') != OWNER_PINS['predecessor_outcome_id']):
            raise ValueError('Original receiver receipt changed.')
    return {**selected, 'baseline_sha256':BASELINE, 'successor':dict(OWNER_PINS)}, outcome_id
