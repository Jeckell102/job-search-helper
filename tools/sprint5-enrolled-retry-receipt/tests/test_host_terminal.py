"""Host catch-up settles a real saved retry without creating another worker."""
from contextlib import closing
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path
from shutil import copytree
from unittest.mock import Mock, patch

import coding_tools
from coordinator import Coordinator
from coordinator_receipt_host_bridge import ManualReceiptV1HostBridge
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.scrape_outcome_delivery import CONSUMER
from job_search_helper.sqlite_repository import SQLiteRepository


def test_host_confirms_one_retry_then_restart_preserves_exact_receipt(tmp_path, monkeypatch):
    root = Path(__file__).parent
    application = tmp_path / 'application'
    receiver = tmp_path / 'coordinator'
    copytree(root / 'fixture-application', application)
    copytree(root / 'fixture-coordinator', receiver)
    prepared = json.loads((root / 'original-prepared.private.json').read_text())['binding']
    request = json.loads((application / 'last-scan-request.json').read_text())
    retry = request['repair_retry']
    owner = root / 'fixture-qualification-owner'
    info = owner.stat()
    approval = {'release_id': retry['release']['release_id'], 'directory': str(owner),
                'device': info.st_dev, 'inode': info.st_ino,
                'receipt_sha256': sha256((owner / (retry['release']['release_id'] + '.json')).read_bytes()).hexdigest()}
    enrollment = {key: prepared[key] for key in ('company_event_id', 'request_id', 'source_revision')}
    monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')
    monkeypatch.setenv('SPREADSHEET_ID', 'sheet')
    monkeypatch.setenv('STATE_DB_FILE', str(application / 'state.db'))
    monkeypatch.setenv('JOB_DB_FILE', str(application / 'jobs.sqlite3'))
    monkeypatch.setattr(coding_tools, 'BASE', tmp_path)
    monkeypatch.setattr(coding_tools, 'ROOT', root)
    read_text = Path.read_text
    with patch.object(Path, 'read_text', lambda path, *a, **kw:
                      'disposable-fixture-token' if path.name == 'bridge-token' else read_text(path, *a, **kw)):
        host = importlib.import_module('host_server')
    monkeypatch.setattr(host, 'JOB_SEARCH_ROOT', tmp_path)
    recipe = host.AmphenolRecipeEnrollment.from_process_environment({
        'WRAPPER_AMPHENOL_RECIPE_ENROLLMENT': json.dumps(enrollment),
        'WRAPPER_AMPHENOL_RETRY_APPROVAL': json.dumps(approval),
    })
    model = Mock(side_effect=AssertionError('Terminal delivery must never invoke inference'))
    coordinator = Coordinator(receiver, model=model, company_revision_resolver=host.current_company_revision)
    commands = []
    real_command = coordinator.command

    def command(value):
        assert value['action'] == 'ingest-scrape-outcome-delivery-v1'
        commands.append(deepcopy(value))
        return real_command(value)

    coordinator.command = command
    supervision = host.build_supervision(coordinator, recipe=recipe)
    with (closing(SQLiteRepository(application / 'jobs.sqlite3', 'sheet')) as jobs,
          closing(State(application / 'state.db', readonly=True)) as state,
          closing(InventoryInbox(application / 'inventories.sqlite3', 'sheet', readonly=True)) as inbox):
        outcomes = jobs.scrape_outcomes()
        [success] = [row for row in outcomes if row['identity'].get('attempt_id') == retry['attempt_id']]
        assert success['outcome'] == 'COMPLETE'
        assert len(jobs.read('Job History')) == 18
        [origin] = jobs._outcome_delivery_rows(CONSUMER, outcome_id=prepared['outcome_id'])
        assert json.loads(origin[6])['sink_receipt_id'] == prepared['sink_receipt_id']
        other = jobs.record_scrape_outcome({
            'request_id': 'HOST-UNRELATED', 'company_id': 'COMP-OTHER', 'source_revision': 'other-rev',
            'cycle_id': 'CYC-OTHER', 'provider': 'greenhouse', 'adapter_version': 'v1',
            'source_current': True, 'company_status': 'Active', 'storage_status': 'confirmed',
            'inventory_status': 'partial', 'capability': 'unknown', 'failure': {'category': 'unknown'},
        })['outcome']
        unrelated_rows = jobs._outcome_delivery_rows(CONSUMER, outcome_id=other['outcome_id'])
        before_cycles = state.cycles()
        before_inbox = tuple(inbox.connection.iterdump())
        before_records = jobs.db.execute('SELECT * FROM records ORDER BY tab,row_id').fetchall()
        before_tasks = coordinator.store.all()
        before_controls = (coordinator.store.queue_enabled(), coordinator.store.campaign_enabled(),
                           coordinator.store.pilot_task(), coordinator.store.unresolved_inferences())
        with coordinator.store.connect() as db:
            before_origin_receipt = db.execute('SELECT * FROM scrape_outcome_delivery_receipts WHERE outcome_id=?',
                                              (prepared['outcome_id'],)).fetchone()
        assert before_origin_receipt is not None
        with coordinator.workspace_lock:
            assert supervision.catch_up() == {'state': 'HELD_WORKSPACE_BUSY'}
        assert not commands
        with patch.object(type(recipe), '_launch', side_effect=AssertionError('Must not construct/launch a worker')):
            result = supervision.catch_up()
        expected = {'state': 'RECIPE_RETRY_CONFIRMED', 'attempt_id': retry['attempt_id'],
                    'outcome_id': success['outcome_id']}
        assert result == expected
        assert len(commands) == 1 and commands[0]['record'] == success
        [sender] = jobs._outcome_delivery_rows(CONSUMER, outcome_id=success['outcome_id'])
        sender_receipt = json.loads(sender[6])
        assert sender_receipt['sink_status'] == 'VALIDATED_COMPLETE'
        lifecycle = coordinator.store.retry_lifecycle(retry['attempt_id'])
        assert lifecycle['state'] == 'VALIDATED_COMPLETE' and len(lifecycle['events']) == 1
        assert lifecycle['events'][0]['record'] == success
        with coordinator.store.connect() as db:
            receiver_receipt = db.execute('SELECT receipt FROM scrape_outcome_delivery_receipts WHERE outcome_id=?',
                                          (success['outcome_id'],)).fetchone()[0]
            assert json.loads(receiver_receipt) == sender_receipt
            assert db.execute('SELECT * FROM scrape_outcome_delivery_receipts WHERE outcome_id=?',
                              (prepared['outcome_id'],)).fetchone() == before_origin_receipt
        assert jobs._outcome_delivery_rows(CONSUMER, outcome_id=prepared['outcome_id']) == [origin]
        assert jobs._outcome_delivery_rows(CONSUMER, outcome_id=other['outcome_id']) == unrelated_rows
        assert jobs.db.execute('SELECT * FROM records ORDER BY tab,row_id').fetchall() == before_records
        assert state.cycles() == before_cycles and tuple(inbox.connection.iterdump()) == before_inbox
        assert coordinator.store.all() == before_tasks
        assert (coordinator.store.queue_enabled(), coordinator.store.campaign_enabled(),
                coordinator.store.pilot_task(), coordinator.store.unresolved_inferences()) == before_controls
        jobs_dump = tuple(jobs.db.iterdump())
        with coordinator.store.connect() as db:
            receiver_dump = tuple(db.iterdump())
        restarted = Coordinator(receiver, model=model, company_revision_resolver=host.current_company_revision)
        restarted.command = Mock(side_effect=AssertionError('Restart must not emit another receiver command'))
        restarted_supervision = host.build_supervision(restarted, recipe=recipe)
        with (patch.object(type(recipe), '_launch', side_effect=AssertionError('Restart must not launch')),
              patch.object(ManualReceiptV1HostBridge, 'manual_drain',
                           side_effect=AssertionError('Restart must preserve the already frozen receipt'))):
            assert restarted_supervision.catch_up() == expected
        assert tuple(jobs.db.iterdump()) == jobs_dump
        with restarted.store.connect() as db:
            assert tuple(db.iterdump()) == receiver_dump
        assert restarted.store.retry_lifecycle(retry['attempt_id']) == lifecycle
        restarted.command.assert_not_called()
        model.assert_not_called()
        evidence = {**expected, 'receiver_event_count': 1, 'original_failure_ack_preserved': True,
                    'identical_two_sided_receipt': True, 'restart_no_redelivery': True,
                    'worker_launches': 0, 'unrelated_outcome_untouched': True,
                    'actual_supervision_catchup': True, 'overlapping_workspace_hold': True,
                    'job_count_preserved': 18, 'native_or_live_qualification': False,
                    'receipt_sha256': sha256(receiver_receipt.encode()).hexdigest()}
        (root / 'HOST_TERMINAL_RESULT.json').write_text(json.dumps(evidence, sort_keys=True, indent=2) + '\n')
