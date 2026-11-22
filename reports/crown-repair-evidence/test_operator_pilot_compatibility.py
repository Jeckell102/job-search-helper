"""Disposable host admission proof; application settlement verification is an I/O boundary."""
from contextlib import contextmanager
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import types

import pytest
import coding_tools
from coordinator import Coordinator
from coordinator_baseline import binding, files
from coordinator_workspace import batch_source, BATCH_SOURCE_OVERRIDE
from coordinator_receipt_host_bridge import ManualReceiptV1HostBridge
from embraer_operator_pilot import EmbraerOperatorEnrollment, ENV, TARGET, DISPATCHER, CODE
from job_search_helper.company_events import source_revision
from job_search_helper.sqlite_repository import SQLiteRepository


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    for name, content in {
        TARGET: 'value = 1\n', DISPATCHER: 'dispatcher = 1\n',
        'tests/test_shared_boards.py': 'def test_breezy(): assert True\n',
        'tests/test_embraer_typed_defect.py': 'def test_brand_heading(): assert True\n',
        'docs/wrapper-development-test-protocol.md': '# Follow bounded tests.\n',
    }.items():
        path = project / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)
    wrapper = tmp_path / 'wrapper'
    for name in ('repo', 'queue-base'):
        stale = wrapper / name
        shutil.copytree(project, stale)
        (stale / TARGET).write_text('stale = True\n')
    monkeypatch.setattr(coding_tools, 'BASE', wrapper)
    monkeypatch.setattr(coding_tools, 'ROOT', wrapper / 'repo')
    monkeypatch.setattr(coding_tools, 'git', lambda *a, **k: '')
    company = {'Company ID': 'COMP-0634', 'Company': 'Embraer', 'Company Status': 'Active',
               'Official Careers URL': 'https://www.embraer.com/careers/', 'ATS / Source': 'Breezy HR'}
    revision = source_revision(company)
    sender = SQLiteRepository(tmp_path / 'sender.sqlite3', 'fixture', initialize=True)
    sender.import_rows('Companies', [(2, company)])
    sender.set_meta('ready', 'yes')
    enrollment = EmbraerOperatorEnrollment('operator-embraer-fixture', revision, 'a' * 64,
        sha256((project / TARGET).read_bytes()).hexdigest(), sha256((project / DISPATCHER).read_bytes()).hexdigest(),
        binding(files(project))['digest'])
    shutil.copytree(project, enrollment.baseline_path)
    record = sender.record_scrape_outcome({
        'request_id': enrollment.request_id, 'company_id': 'COMP-0634', 'source_revision': revision,
        'cycle_id': 'CYC-EMBRAER-FIXTURE', 'provider': 'Breezy HR', 'adapter_version': 'normal-scraper-v1',
        'source_current': True, 'company_status': 'Active', 'storage_status': 'confirmed',
        'inventory_status': 'partial', 'capability': 'qualified',
        'failure': {'category': 'full_description_regression', 'provider_code': CODE},
    })['outcome']
    proof = {'source_files': enrollment.source_files, 'evidence_code': CODE, 'owner': 'fixture-settlement'}
    calls = []
    def read_owner(repository, actual, request_sha256):
        calls.append('owner')
        assert repository.readonly and actual == record and request_sha256 == enrollment.request_sha256
        return proof
    module = types.SimpleNamespace(read_operator_embraer_source=read_owner)
    monkeypatch.setitem(sys.modules, 'job_search_helper.operator_embraer_settlement', module)
    @contextmanager
    def scope(_self):
        yield project, sender.path, 'fixture'
    monkeypatch.setattr(EmbraerOperatorEnrollment, 'owner_scope', scope)
    coordinator = Coordinator(tmp_path / 'receiver', model=lambda *a: pytest.fail('No inference during catch-up'),
        company_revision_resolver=lambda ident: revision if ident == 'COMP-0634' else None,
        repair_profile_selector=enrollment.profile)
    coordinator.store.set_queue_enabled(False)
    original = coordinator.command
    def command(value):
        calls.append(value['action']); return original(value)
    monkeypatch.setattr(coordinator, 'command', command)
    yield types.SimpleNamespace(project=project, sender=sender, enrollment=enrollment, co=coordinator,
                                record=record, proof=proof, calls=calls, owner=module, company=company, wrapper=wrapper)
    sender.close()


def test_default_off_and_closed_enrollment():
    assert EmbraerOperatorEnrollment.from_process_environment({}) is None
    valid = dict(request_id='operator-embraer-fixture', source_revision='1'*64, request_sha256='2'*64,
                 shared_boards_sha256='3'*64, ats_sha256='4'*64, baseline_sha256='5'*64)
    assert EmbraerOperatorEnrollment.from_process_environment({ENV: json.dumps(valid)}).request_id == valid['request_id']
    for update in ({'extra': 'on'}, {'source_revision': 'stale'}, {'request_id': 'company-event:CEV-test'}):
        with pytest.raises(ValueError):
            EmbraerOperatorEnrollment.from_process_environment({ENV: json.dumps({**valid, **update})})
    with pytest.raises(ValueError):
        EmbraerOperatorEnrollment.from_process_environment({ENV: json.dumps(valid)[:-1] + ',"request_id":"duplicate"}'})


def test_exact_two_sided_delivery_prepares_one_isolated_develop_pilot_and_replay(pilot):
    p = pilot
    old = {name: files(p.wrapper / name) for name in ('repo', 'queue-base')}
    result = p.enrollment.catch_up(p.co)
    assert result['state'] == 'EMBRAER_PILOT_QUEUED', result
    task = p.co.store.get(result['task_id'])
    assert task['isolated_workspace'] and task['mode'] == 'develop' and task['status'] == 'QUEUED'
    assert task['integration']['source_targets'] == [TARGET]
    assert task['integration']['tests'] == ['tests/test_shared_boards.py', 'tests/test_embraer_typed_defect.py']
    assert 'brand heading' in task['objective']
    assert p.co.store.pilot_task() == task['id']
    assert not p.co.store.queue_enabled() and not p.co.store.campaign_enabled() and not p.co.store.autopilot_enabled()
    assert p.calls.count('pilot-start') == 1 and p.calls.count('prepare-held-repair') == 1
    assert (p.co.store.base / task['id'] / 'repo' / TARGET).read_bytes() == (p.project / TARGET).read_bytes()
    before = json.dumps(p.co.store.all(), sort_keys=True)
    assert p.enrollment.catch_up(p.co)['state'] == 'EMBRAER_PILOT_ALREADY_PREPARED'
    assert json.dumps(p.co.store.all(), sort_keys=True) == before
    assert p.calls.count('pilot-start') == 1 and p.calls.count('ingest-scrape-outcome-delivery-v1') == 1
    with p.co.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM scrape_outcome_delivery_receipts').fetchone()[0] == 1
    assert p.enrollment.profile(p.co.store.held_repair_intake()[0]) is None
    p.co.command({'action': 'pause', 'id': task['id']})
    paused = json.dumps(p.co.store.all(), sort_keys=True)
    assert p.enrollment.catch_up(p.co)['state'] == 'EMBRAER_PILOT_ALREADY_PREPARED'
    assert json.dumps(p.co.store.all(), sort_keys=True) == paused
    assert p.calls.count('pilot-start') == 1
    assert BATCH_SOURCE_OVERRIDE.get() is None and batch_source() == p.wrapper / 'queue-base'
    assert {name: files(p.wrapper / name) for name in old} == old
    assert task['assignment_baseline']['digest'] == p.enrollment.baseline_sha256


@pytest.mark.parametrize('failure', ['owner', 'source', 'revision', 'queue', 'receiver', 'stale_baseline',
                                    'source_vector', 'baseline_alias'])
def test_missing_or_conflicting_evidence_never_prepares_task(pilot, failure):
    p = pilot
    if failure == 'owner':
        p.owner.read_operator_embraer_source = lambda *a: None
    elif failure == 'source':
        (p.project / TARGET).write_text('changed = True\n')
    elif failure == 'revision':
        p.sender.import_rows('Companies', [(2, {**p.company, 'ATS / Source': 'Other'})])
    elif failure == 'queue':
        p.co.store.set_queue_enabled(True)
    elif failure == 'receiver':
        ManualReceiptV1HostBridge(p.co, lambda: p.sender, enabled=True).manual_drain(outcome_id=p.record['outcome_id'])
        with p.co.store.connect() as db:
            db.execute('DELETE FROM scrape_outcome_delivery_receipts')
    elif failure == 'stale_baseline':
        (p.enrollment.baseline_path / 'tests/test_embraer_typed_defect.py').write_text('changed = True\n')
    elif failure == 'source_vector':
        (p.project / 'src/job_search_helper/other.py').write_text('added = True\n')
    elif failure == 'baseline_alias':
        actual = p.enrollment.baseline_path.with_name('alias-target')
        p.enrollment.baseline_path.rename(actual)
        p.enrollment.baseline_path.symlink_to(actual, target_is_directory=True)
    result = p.enrollment.catch_up(p.co)
    assert result['state'].startswith('HELD_'), result
    assert p.co.store.all() == []
    assert 'pilot-start' not in p.calls


@pytest.mark.parametrize('operator_pause', [False, True])
def test_durable_promotion_cut_recovers_only_pristine_first_activation(pilot, monkeypatch, operator_pause):
    p = pilot
    command = p.co.command
    def cut(value):
        if value['action'] == 'pilot-start':
            raise RuntimeError('fixture crash before first activation')
        return command(value)
    monkeypatch.setattr(p.co, 'command', cut)
    assert p.enrollment.catch_up(p.co)['state'] == 'HELD_EMBRAER_BOUNDARY'
    [saved] = p.co.store.all()
    assert saved['status'] == 'PAUSED' and saved['activated_at'] is None
    assert p.co.store.pilot_task() is None and p.co.store.receipts(saved['id']) == []
    assert BATCH_SOURCE_OVERRIDE.get() is None and batch_source() == p.wrapper / 'queue-base'
    if operator_pause:
        p.co.store.pause_task(saved['id'])
    restarted = Coordinator(p.co.store.base, model=lambda *a: pytest.fail('No model in catch-up'),
        company_revision_resolver=lambda _ident: p.enrollment.source_revision,
        repair_profile_selector=p.enrollment.profile)
    result = p.enrollment.catch_up(restarted)
    assert len(restarted.store.all()) == 1
    assert result['task_id'] == saved['id']
    if operator_pause:
        assert result['state'] == 'EMBRAER_PILOT_ALREADY_PREPARED'
        assert restarted.store.pilot_task() is None
        assert restarted.store.get(saved['id'])['reason'] == 'Pause requested.'
    else:
        assert result['state'] == 'EMBRAER_PILOT_QUEUED'
        assert restarted.store.pilot_task() == saved['id']
        assert restarted.store.get(saved['id'])['status'] == 'QUEUED'
    assert BATCH_SOURCE_OVERRIDE.get() is None


def test_source_only_host_selection_preserves_default_and_refuses_mixed_enrollment(pilot, monkeypatch):
    path = Path(__file__).with_name('host_server.py')
    original = Path.read_text
    def read(path, *args, **kwargs):
        return 'fixture-token' if path.name == 'bridge-token' else original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    spec = importlib.util.spec_from_file_location('embraer_fixture_host', path)
    host = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, host); spec.loader.exec_module(host)
    assert host.recipe_enrollment_from_process_environment({}) is None
    value = json.dumps({key: item for key, item in pilot.enrollment.__dict__.items() if item is not None})
    assert host.recipe_enrollment_from_process_environment({ENV: value}) == pilot.enrollment
    from crown_operator_pilot import ENV as CROWN_ENV
    crown_value = json.dumps({
        'request_id': 'operator-crown-fixture', 'source_revision': '1' * 64,
        'request_sha256': '2' * 64, 'successfactors_sha256': '3' * 64,
        'ats_sha256': '4' * 64, 'baseline_sha256': '5' * 64,
    })
    assert host.recipe_enrollment_from_process_environment({CROWN_ENV: crown_value}).request_id == 'operator-crown-fixture'
    with pytest.raises(ValueError):
        host.recipe_enrollment_from_process_environment({CROWN_ENV: crown_value, ENV: value})
    with pytest.raises(ValueError):
        host.recipe_enrollment_from_process_environment({CROWN_ENV: value})
    for key in ('WRAPPER_AMPHENOL_RECIPE_ENROLLMENT', 'WRAPPER_AMPHENOL_OPERATOR_RECIPE_ENROLLMENT',
                'WRAPPER_AMPHENOL_RETRY_APPROVAL', 'WRAPPER_AMPHENOL_ACTIVATE_APPROVED_RELEASE'):
        with pytest.raises(ValueError):
            host.recipe_enrollment_from_process_environment({ENV: value, key: '{}'})
    created = []
    monkeypatch.setattr(host, 'Coordinator', lambda **kwargs: created.append(kwargs) or kwargs)
    host.build_coordinator(pilot.enrollment)
    assert set(created[0]) == {'company_revision_resolver', 'repair_profile_selector'}
