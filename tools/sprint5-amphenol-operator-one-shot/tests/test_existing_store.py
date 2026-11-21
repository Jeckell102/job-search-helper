from contextlib import closing
from pathlib import Path
import json
import sqlite3

import pytest

import amphenol_operator_one_shot as one_shot
from coordinator import Coordinator
from coordinator_store import Store


CANARY=Path('/tmp/jsh-amphenol-one-shot-canary.080vithb/run-u3pmugo4')


def inspect(path, sql):
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        return db.execute(sql).fetchall()


def test_existing_attachment_skips_schema_changes_and_journal_mode(tmp_path):
    tasks=tmp_path/'tasks.sqlite3'
    with closing(sqlite3.connect(tasks)) as db, db:
        db.execute('CREATE TABLE repair_intake (repair_key TEXT PRIMARY KEY)')
        db.execute("INSERT INTO repair_intake VALUES('keep')")
        db.execute('CREATE TABLE repair_retry_lineage (failed_request_id TEXT PRIMARY KEY)')
    before=tasks.read_bytes()
    existing=Coordinator(base=tmp_path,existing_store_only=True).store
    with existing.connect() as db:
        assert db.execute('SELECT repair_key FROM repair_intake').fetchall()==[('keep',)]
        assert db.execute('PRAGMA journal_mode').fetchone()==('delete',)
        assert db.execute('SELECT name FROM sqlite_master WHERE type=\'table\' ORDER BY name').fetchall()==[
            ('repair_intake',),('repair_retry_lineage',)]
    assert tasks.read_bytes()==before


def test_disappeared_database_is_never_created(tmp_path):
    absent=tmp_path/'absent'
    with pytest.raises(ValueError,match='existing coordinator store is unavailable'):
        Coordinator(base=absent,existing_store_only=True)
    assert not absent.exists()
    bootstrapped=Store(tmp_path/'bootstrapped')
    existing=Store(bootstrapped.base,existing_only=True)
    existing.path.unlink()
    with pytest.raises(sqlite3.OperationalError):
        with existing.connect():
            pytest.fail('opening an existing-only Store recreated a missing file')
    assert not existing.path.exists()


def test_default_coordinator_retains_normal_store_bootstrap(tmp_path):
    base=tmp_path/'fresh'
    fresh=Coordinator(base=base).store
    assert fresh.path.is_file()
    assert inspect(fresh.path,'PRAGMA journal_mode')==[('wal',)]
    assert inspect(fresh.path,'SELECT count(*) FROM tasks')==[(0,)]
    assert inspect(fresh.path,'SELECT count(*) FROM scrape_outcome_delivery_receipts')==[(0,)]
    assert fresh.queue_enabled() is True


def test_existing_store_only_records_intended_receipt(tmp_path):
    records_path=CANARY/'project/.state/jobs.sqlite3'
    with closing(sqlite3.connect(records_path.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
        records=[json.loads(raw) for raw, in db.execute('SELECT payload FROM scrape_outcomes')]
    [origin]=[item for item in records if item['outcome']=='QUALIFIED_INTEGRATION_REPAIR']
    [retry]=[item for item in records if item['outcome']=='COMPLETE']
    base=tmp_path/'current'
    rev=origin['identity']['source_revision']
    normal=Coordinator(base=base,company_revision_resolver=lambda _:rev)
    normal.store.set_queue_enabled(False)
    action={'action':'ingest-scrape-outcome-delivery-v1','consumer':'repair-coordinator'}
    first=normal.command({**action,'record':origin})
    assert first['ok'] and first['receipt']['sink_status']=='HELD_FOR_REPAIR_TRIAGE'
    path=normal.store.path
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('PRAGMA journal_mode=DELETE').fetchone()==('delete',)
    expected_schema=inspect(path,'SELECT type,name,sql FROM sqlite_master ORDER BY type,name')
    stable_tables=['settings','tasks','inference_receipts','receipts','batches','campaigns','campaign_seals',
                   'campaign_snapshots','campaign_company_registry','repair_intake_evidence']
    stable={name:inspect(path,'SELECT * FROM '+name) for name in stable_tables}
    attached=Coordinator(base=base,company_revision_resolver=lambda _:rev,existing_store_only=True)
    terminal=attached.command({**action,'record':retry})
    assert terminal['receipt']['sink_status']=='VALIDATED_COMPLETE'
    assert attached.command({**action,'record':retry})==terminal
    assert inspect(path,'PRAGMA journal_mode')==[('delete',)]
    assert inspect(path,'SELECT type,name,sql FROM sqlite_master ORDER BY type,name')==expected_schema
    assert {name:inspect(path,'SELECT * FROM '+name) for name in stable_tables}==stable
    assert inspect(path,'SELECT count(*) FROM scrape_outcome_delivery_receipts')==[(2,)]
    assert inspect(path,'SELECT state FROM repair_retry_lifecycles')==[('VALIDATED_COMPLETE',)]
    assert inspect(path,'SELECT status FROM repair_intake')==[('SUPERSEDED_BY_REPAIRED_RETRY',)]


def test_missing_task_checkpoint_status_is_not_idle(tmp_path):
    store=Store(tmp_path/'with-task')
    store.set_queue_enabled(False)
    with store.connect() as db:
        db.execute("INSERT INTO tasks VALUES('WRAP-1111111111','{}')")
    assert one_shot._coordinator_is_idle(store.path) is False
