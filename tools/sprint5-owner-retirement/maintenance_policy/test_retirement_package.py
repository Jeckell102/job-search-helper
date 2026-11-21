"""Exact package policy and legacy compatibility; no install or site actions."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import stat
import sys

import pytest
import installer


ROOT = Path(__file__).resolve().parent.parent
BASE = Path('/tmp/jsh-m1-scope-backup/tools/sprint6-consolidated-source-preparation')
PACKET = json.loads((ROOT / 'SOURCE_MANIFEST.json').read_bytes())
ADDITIONS = {'src/job_search_helper/' + name + '.py' for name in (
    'control_before_prefix_runner', 'exact_legacy_migration_runner',
    'exact_recovery_pause_executor', 'retained_cycle_retirement',
    'retained_cycle_retirement_control', 'selected_recovery_runner')}


def load(tmp_path, value, *, pin=None, module=installer):
    data = module.encode(value)
    path = tmp_path / 'manifest.json'
    path.write_bytes(data)
    return module.load_manifest(path, pin or sha256(data).hexdigest())


def test_retirement_requires_exact_44_and_actual_after_images(tmp_path):
    result = load(tmp_path, PACKET)
    assert result.schema == installer.RETIREMENT_SCHEMA
    assert len(result.paths) == 44 and set(result.paths) == installer.RETIREMENT_PATHS
    assert len(installer.CONSOLIDATED_PATHS) == 38
    assert installer.RETIREMENT_PATHS - installer.CONSOLIDATED_PATHS == ADDITIONS
    files = {p.relative_to(ROOT / 'after_images').as_posix(): p
             for p in (ROOT / 'after_images').rglob('*') if p.is_file()}
    assert set(files) == set(result.paths)
    for name, path in files.items():
        info = path.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        assert (stat.S_IMODE(info.st_mode), sha256(path.read_bytes()).hexdigest()) == result.after[name]
        assert [info.st_uid, info.st_gid] == result.owners[name]


@pytest.mark.parametrize('omission', sorted(PACKET['paths']))
def test_each_omitted_path_is_refused(tmp_path, omission):
    packet = deepcopy(PACKET)
    del packet['paths'][omission]
    with pytest.raises(ValueError, match='exact reviewed source paths'):
        load(tmp_path, packet)


@pytest.mark.parametrize('extra', [
    'src/job_search_helper/other.py',
    'dev/wrapper-coder/tools/coordinator_receipt_host_bridge.py',
    'dev/wrapper-coder/tools/unreviewed.py', '../escape.py'])
def test_extra_path_is_refused(tmp_path, extra):
    packet = deepcopy(PACKET)
    packet['paths'][extra] = deepcopy(next(iter(packet['paths'].values())))
    with pytest.raises(ValueError, match='exact reviewed source paths'):
        load(tmp_path, packet)


@pytest.mark.parametrize('name', ['host_server.py', 'coordinator_store.py'])
def test_current_wrapper_endpoints_required(tmp_path, name):
    packet = deepcopy(PACKET)
    packet['paths']['dev/wrapper-coder/tools/' + name]['before'] = None
    with pytest.raises(ValueError, match='existing wrapper host and store'):
        load(tmp_path, packet)


def test_changed_manifest_cannot_reuse_approved_pin(tmp_path):
    packet = deepcopy(PACKET)
    packet['paths']['src/job_search_helper/engine.py']['after']['sha256'] = '0' * 64
    original_pin = sha256((ROOT / 'SOURCE_MANIFEST.json').read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='hash differs from the approved pin'):
        load(tmp_path, packet, pin=original_pin)


def test_existing_38_and_legacy_schema_contracts_unchanged(tmp_path):
    path = BASE / 'maintenance_policy/installer.py'
    spec = importlib.util.spec_from_file_location('original_policy', path)
    original = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = original
    spec.loader.exec_module(original)
    assert installer.CONSOLIDATED_PATHS == original.CONSOLIDATED_PATHS
    assert installer.CONSOLIDATED_WRAPPER_PATHS == original.CONSOLIDATED_WRAPPER_PATHS
    assert installer.WRAPPER_PATHS == original.WRAPPER_PATHS
    old38 = json.loads((BASE / 'original_gate/consolidated_exact_38_manifest.json').read_bytes())
    old38['schema'] = installer.CONSOLIDATED_SCHEMA
    legacy = json.loads((BASE / 'original_gate/accepted_freeform_manifest.json').read_bytes())
    for packet, count in ((old38, 38), (legacy, 47)):
        before = load(tmp_path, packet, module=original)
        after = load(tmp_path, packet)
        assert len(after.paths) == count
        assert after.schema == packet['schema']
        assert (before.before, before.after, before.owners) == (after.before, after.after, after.owners)
    with pytest.raises(ValueError, match='exact reviewed source paths'):
        load(tmp_path, {**PACKET, 'schema': installer.CONSOLIDATED_SCHEMA})
    with pytest.raises(ValueError, match='exact reviewed source paths'):
        load(tmp_path, {**old38, 'schema': installer.RETIREMENT_SCHEMA})
    with pytest.raises(ValueError, match='outside the allowed scope'):
        load(tmp_path, {**PACKET, 'schema': legacy['schema']})
    with pytest.raises(ValueError, match='canonical maintenance source manifest'):
        load(tmp_path, PACKET, module=original)
