"""Inspect, arm or disarm one owned Embraer pilot; no action on import."""
import argparse
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from types import ModuleType, SimpleNamespace

HERE = Path(__file__).resolve().parent
STAGE = HERE.parents[1]
ENROLLMENT_TOOLS = STAGE / "pilot-enrollment"
PROJECT = Path('/home/chris/job-search-helper_old')
ROOT = PROJECT / '.state'
TOOLS = PROJECT / 'dev/wrapper-coder/tools'
DEPLOYMENT = STAGE / 'deployment'
DEPLOYMENT_ENTRY_PIN = 'fb12dc6e357baea45224114b02db0ac6f65ae660fd77675d94d659d438274e11'
APPROVAL_PIN = 'd6b2b78a3a77f4a6c431c5dac3039ee16ab35437e28a5895149f98d737b56c5b'
BOOTSTRAP_PIN = '0a1eca6877ef7b78cd851d2e5de15528c166bf31da96ca361f705cd48b7b4a00'
ACTIVE_JOURNAL_PIN = 'c47b1e8036d3145b4c016e9d398f20ca5e34a7f98bc07459ef213ad6601aa576'
ACTIVE_RECEIPT_PIN = 'e652841c669138c7b92a78135dd3735b49d27f534d4eb2ce3ca9c29c1b69da50'
UNIT_PIN = '201a985896999b4ee0c484175ed9393be0576656b4781eb2ca16db9fb1ad2c28'
PINS = {
    'embraer_pilot_environment': '2f69088e899d637759bdbe9f0984ef87259c2c2e1fc3f7e4d2ce0b7be35c87d6',
    'embraer_pilot_arming': 'bb1dc2ed88e2107fa8b2de21676ac4a2a7c61e4109a78712dabab285a1d91ba5',
    'embraer_operator_enrollment_input': '16c4c672a205881e25d2a6ea2dc9bc50b9a7d1d27eac326851907a5662c15b18',
}
RESTORED = {
    'native-window.json': '492e8d056870dac4004d01dbb39fd179ae0ac3f008aace9e5d69a0941e0d4e72',
    'operator-quiet-window.json': '5ed9e6f5e9a09ac5862015977ea2affa278d205ade47c337af3ca523390ca34f',
    'exchange-private/exchange.json': '4fe057dab5d0f15c35e102d73c776151469a59fb442067a1b3313aa36b5f83ca',
}
PYTHON_OVERRIDES = frozenset(('PYTHONPATH', 'PYTHONHOME', 'PYTHONPYCACHEPREFIX', 'PYTHONOPTIMIZE',
                              'PYTHONSAFEPATH', 'PYTHONINSPECT'))


def load(name, path, pin, reader=None):
    path = Path(path)
    if path.resolve(strict=True) != path or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError('Enrollment source custody changed.')
    raw = reader(path, pin) if reader else path.read_bytes()
    if sha256(raw).hexdigest() != pin or name in sys.modules:
        raise ValueError('Enrollment source pin or import origin changed.')
    module = ModuleType(name); module.__file__ = str(path); sys.modules[name] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def controls(connection, *, allowed_pilot=None):
    """Read only; never acquire or retain the wrapper scheduler lease."""
    settings = {key: json.loads(value) for key, value in connection.execute(
        "SELECT key,value FROM settings WHERE key IN ('queue_enabled','campaign_enabled','autopilot_enabled','pilot_task')")}
    tasks = [json.loads(row[0]) for row in connection.execute('SELECT state FROM tasks')]
    if (settings.get('queue_enabled', True) or settings.get('campaign_enabled', False)
            or settings.get('autopilot_enabled', False)
            or settings.get('pilot_task') not in (None, allowed_pilot)
            or any(task['status'] in ('RUNNING', 'QUEUED', 'PAUSING') for task in tasks)
            or connection.execute("SELECT 1 FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN') LIMIT 1").fetchone()
            or connection.execute('SELECT 1 FROM receipts WHERE result IS NULL LIMIT 1').fetchone()):
        raise ValueError('Coordinator controls or unfinished work prevent enrollment restart.')


def process_scope(raw, scoped):
    result, seen = {}, set()
    for item in raw.split(b'\0'):
        if not item:
            continue
        key, separator, value = item.partition(b'=')
        name = key.decode()
        if not separator or name in seen or name in PYTHON_OVERRIDES:
            raise ValueError('Unexpected wrapper startup environment.')
        seen.add(name)
        if name in scoped:
            result[name] = value.decode()
    return result


def load_runtime(entry_pin, forward, authority, projection_module):
    deployment = load('embraer_deployment_entry', DEPLOYMENT / 'native_source_release_entry.py', DEPLOYMENT_ENTRY_PIN)
    custody = load('embraer_enrollment_custody', deployment.CUSTODY, deployment.CUSTODY_PIN)
    read = custody.file_bytes
    read(Path(__file__).resolve(), entry_pin)
    approval = json.loads(read(DEPLOYMENT / 'APPLY_APPROVAL.json', APPROVAL_PIN, private=True))
    bootstrap = load('release_admission_bootstrap', PROJECT / 'release_admission_bootstrap.py', BOOTSTRAP_PIN, read)
    bootstrap._load_environment(PROJECT / '.env')
    runtime = bootstrap._validate_runtime(PROJECT, ROOT)
    if (runtime.get('state') != 'COMPLETE' or runtime.get('release_id') != approval['source_approval']['release_id']
            or runtime.get('source_manifest_sha256') != approval['source_approval']['source_sha256']):
        raise ValueError('The exact deployed Embraer runtime is required before application imports.')
    read(ROOT / 'integration-release-journal.json', ACTIVE_JOURNAL_PIN, private=True)
    read(ROOT / 'native-runtime-releases' / runtime['release_id'] / 'receipt.json', ACTIVE_RECEIPT_PIN, private=True)
    package = json.loads(read(DEPLOYMENT / 'PREPARED_PACKAGE.json', approval['package_sha256'], private=True))
    pair = package['package_files'][projection_module.RELATIVE]
    projection = projection_module.Projection(PROJECT, DEPLOYMENT / 'staged' / projection_module.RELATIVE,
        pair['staged'], pair['owner'], authority, forward)
    projection.verify()
    for name, pair in package['package_files'].items():
        read(projection.archived if name == projection_module.RELATIVE else PROJECT / name, pair['staged']['sha256'])
    sys.path[:0] = [str(PROJECT / 'src'), str(TOOLS)]
    from job_search_helper.cli import load_environment
    load_environment(PROJECT / '.env')
    load('native_source_advance', DEPLOYMENT / 'native_source_advance.py',
         approval['tool_sha256']['native_source_advance.py'], read)
    owner_module = load('maintenance_source_owner', DEPLOYMENT / 'maintenance_source_owner.py',
                       approval['tool_sha256']['maintenance_source_owner.py'], read)
    owner = owner_module.MaintenanceSourceOwner(PROJECT, DEPLOYMENT, approval['package_sha256'])
    owner = projection.wrap_owner(owner)
    if owner.status()['phase'] != 'STAGED':
        raise ValueError('Embraer source transaction is not complete.')
    prior = load('embraer_enrollment_native_loader', deployment.PRIOR_ENTRY, deployment.PRIOR_ENTRY_PIN, read)
    prior.NATIVE_STAGE = STAGE / 'native-window'
    prior.INSTALLED_PINS = {**prior.INSTALLED_PINS,
                           'host_server.py': package['package_files']['dev/wrapper-coder/tools/host_server.py']['staged']['sha256']}
    loaded = prior.verify_tool_origins()
    native, modules = prior.load_native_window(loaded, approval['native']['window_sha256'])
    window = native.create_window(release_id=owner.release_id, manifest_sha256=owner.manifest_pin,
        manifest=owner.manifest, approval_check=lambda: json.loads(read(
            DEPLOYMENT / 'APPLY_APPROVAL.json', APPROVAL_PIN, private=True))['source_approval'],
        window_root=Path(approval['native']['window_root']), native_modules=modules,
        wrapper_scope_sha256=approval['native']['wrapper_scope_sha256'], source_owner=owner, resume_complete=True)
    libraries = {name: load(name, ENROLLMENT_TOOLS / (name + '.py'), pin, read) for name, pin in PINS.items()}
    return deployment, read, owner, native, window, libraries, projection

