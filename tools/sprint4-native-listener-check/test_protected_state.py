import hashlib
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

import protected_state as witness


# Small test schemas retain the owning keys and every field used by a predicate.
FIELDS = {
    'cycles': 'id TEXT PRIMARY KEY,data TEXT',
    'inventories': 'cycle TEXT,company TEXT,payload TEXT,PRIMARY KEY(cycle,company)',
    'sync_plans': 'cycle TEXT,company TEXT,payload TEXT,cursor INTEGER,PRIMARY KEY(cycle,company)',
    'retained_sessions': 'reservation_digest TEXT PRIMARY KEY,receipt_id TEXT,intent_id TEXT,acknowledgement_id TEXT,'
                         'company_id TEXT,exception_cycle_id TEXT,request_id TEXT,state TEXT',
    'retained_publications': 'reservation_digest TEXT PRIMARY KEY,local_apply_id TEXT,receipt_id TEXT,intent_id TEXT,'
                             'acknowledgement_id TEXT,company TEXT,exception_cycle TEXT,state TEXT',
    'exact_local_acknowledgements': 'apply_id TEXT PRIMARY KEY,receipt_id TEXT,acknowledgement_id TEXT',
    'settings': 'key TEXT PRIMARY KEY,value TEXT',
    'tasks': 'id TEXT PRIMARY KEY,state TEXT',
    'inference_receipts': 'request_id TEXT PRIMARY KEY,status TEXT,data TEXT',
    'scrape_outcomes': 'outcome_id TEXT PRIMARY KEY,payload TEXT',
    'scrape_outcome_deliveries': 'outcome_id TEXT,consumer TEXT,acknowledged_at TEXT,PRIMARY KEY(outcome_id,consumer)',
    'scrape_outcome_delivery_receipts': 'outcome_id TEXT,consumer TEXT,record_sha256 TEXT,receipt TEXT,'
                                        'receipt_sha256 TEXT,PRIMARY KEY(outcome_id,consumer)',
    'scrape_outcome_delivery_attempts': 'outcome_id TEXT,consumer TEXT,PRIMARY KEY(outcome_id,consumer)',
    'records': 'tab TEXT,row_id INTEGER,data TEXT,policies TEXT,PRIMARY KEY(tab,row_id)',
    'dispatches': 'request_id TEXT PRIMARY KEY,state TEXT',
    'request_ownership': 'request_id TEXT PRIMARY KEY,state TEXT',
}


class ProtectedWitnessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'project'
        self.dbpaths = {name:self.root / rel for name, rel in witness.DATABASES.items()}
        self.dbpaths['dispatch'] = self.root / '.state' / witness.DISPATCH
        for name in witness.DATABASES:
            self.schema(name)
        state = self.root / '.state'
        for name in witness.ARCHIVES:
            directory = state / name
            directory.mkdir(parents=True)
            (directory / 'receipt.json').write_text('disposable receipt')
        profile = self.root / 'dev/wrapper-coder/tools/coordinator_repair_profiles.py'
        profile.parent.mkdir()
        profile.write_text('PROFILE_REGISTRY = ()\n')
        cycle, cid = witness.CYCLE, witness.SARONIC
        self.sql('state', 'INSERT INTO cycles VALUES (?,?)', (cycle,json.dumps({
            'id':cycle, 'status':'In Progress', 'companies':{cid:{'stage':'inventory'}}})))
        self.sql('inbox', 'INSERT INTO inventories VALUES (?,?,?)', (cycle,cid,'private contents'))
        self.sql('inbox', 'INSERT INTO sync_plans VALUES (?,?,?,?)', (cycle,cid,'sealed Saronic',67))
        self.sql('sessions','INSERT INTO retained_sessions VALUES (?,?,?,?,?,?,?,?)',
                 ('reservation','receipt','intent','ack',witness.SAMTEC,cycle,'operator-samtec-m1-20261119','SYNC_CONFIRMED'))
        self.sql('jobs','INSERT INTO retained_publications VALUES (?,?,?,?,?,?,?,?)',
                 ('reservation','apply','receipt','intent','ack',witness.SAMTEC,cycle,'FIRST_PASS_RELEASED'))
        self.sql('jobs','INSERT INTO exact_local_acknowledgements VALUES (?,?,?)',('apply','receipt','ack'))
        for tab, row in [('Companies',{'Company ID':cid}),('Scan Cycles',{'Cycle ID':cycle}),
                         ('Job History',{'Job Key':'private job','Review Notes':'private notes'}),
                         ('Opportunities',{'Company':'private company'})]:
            self.sql('jobs','INSERT INTO records VALUES (?,2,?,?)',(tab,json.dumps(row),'{}'))
        for key in witness.FLAGS:
            self.sql('coordinator','INSERT INTO settings VALUES (?,?)',(key,'false'))
        self.pin = Path(tmp.name) / 'pin'
        self.seal()

    def schema(self, name):
        path = self.dbpaths[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        tables = set(witness.TABLES[name].split())
        if name == 'coordinator':
            tables.add('settings')
        if name == 'jobs':
            tables.add('records')
        with closing(sqlite3.connect(path)) as db:
            for table in tables:
                db.execute(f'CREATE TABLE {table} ({FIELDS.get(table, "id TEXT PRIMARY KEY")})')

    def sql(self, dbname, sql, params=()):
        with closing(sqlite3.connect(self.dbpaths[dbname])) as db, db:
            db.execute(sql, params)

    def seal(self):
        self.pin.write_bytes(witness.encoded({'project':str(self.root),'schema':'protected-site-witness-v1',
                                      'witness':witness.measure_for_private_review(self.root)}))
        self.pin.chmod(0o600)
        self.digest = hashlib.sha256(self.pin.read_bytes()).hexdigest()

    def verify(self, **args):
        return witness.verify_protected_state(self.root, self.pin, self.digest,
                    verify_release_hold=args.pop('release', lambda: True), **args)

    def test_success_and_no_source_changes(self):
        def snap():
            return {p.relative_to(self.root):(witness.version(p),witness.file_digest(p))
                    for p in self.root.rglob('*') if p.is_file()}
        before = snap()
        self.assertIs(self.verify(), True)
        self.assertEqual(before, snap())
        self.assertNotIn(b'private notes',self.pin.read_bytes())

    def test_historical_cursor(self):
        self.sql('inbox','UPDATE sync_plans SET cursor=68')
        with self.assertRaisesRegex(witness.WitnessHold, 'differs'): self.verify()

    def test_manual_choice(self):
        self.sql('jobs',"UPDATE records SET data=? WHERE tab='Job History'",('{"Review Notes":"changed secret"}',))
        with self.assertRaisesRegex(witness.WitnessHold, 'differs'): self.verify()

    def test_receipt_conflict(self):
        self.sql('jobs',"UPDATE exact_local_acknowledgements SET acknowledgement_id='private'")
        with self.assertRaisesRegex(witness.WitnessHold, 'acknowledgement'): self.verify()

    def test_required_table_or_db_missing(self):
        self.sql('jobs','DROP TABLE scrape_outcome_deliveries')
        with self.assertRaisesRegex(witness.WitnessHold, 'ordinary table'): self.verify()
        self.dbpaths['state'].unlink()
        with self.assertRaises(witness.WitnessHold): self.verify()
        self.assertFalse(self.dbpaths['state'].exists())

    def test_dispatch_policy(self):
        self.schema('dispatch')
        with self.assertRaisesRegex(witness.WitnessHold, 'differs'): self.verify()
        self.seal()
        self.assertTrue(self.verify())
        self.sql('dispatch',"INSERT INTO settings VALUES ('temporary_retry_enabled','true')")
        with self.assertRaisesRegex(witness.WitnessHold, 'dispatcher enabled'): self.verify()
        self.sql('dispatch','DELETE FROM settings')
        self.sql('dispatch','DROP TABLE request_ownership')
        with self.assertRaisesRegex(witness.WitnessHold, 'ordinary table'): self.verify()

    def test_jetson_owner_or_request(self):
        self.sql('coordinator',"INSERT INTO tasks VALUES ('x',?)", ('{"status":"PAUSED","inference_session_open":true}',))
        with self.assertRaisesRegex(witness.WitnessHold,'active task'): self.verify()
        self.sql('coordinator','DELETE FROM tasks')
        self.sql('coordinator',"INSERT INTO inference_receipts VALUES ('x','UNCERTAIN',?)",('{"status":"UNCERTAIN"}',))
        with self.assertRaisesRegex(witness.WitnessHold,'unresolved inference'): self.verify()

    def test_restart_backlog(self):
        self.sql('jobs',"INSERT INTO scrape_outcomes VALUES ('out','private')")
        with self.assertRaisesRegex(witness.WitnessHold,'restart backlog'): self.verify()
        self.sql('jobs',"INSERT INTO scrape_outcome_deliveries VALUES ('out','wrapper-coordinator','now')")
        self.sql('jobs',"INSERT INTO scrape_outcome_delivery_attempts VALUES ('out','repair-coordinator')")
        with self.assertRaisesRegex(witness.WitnessHold,'pending outcome'): self.verify()

    def test_held_marker(self):
        marker = self.root / '.state/integration-release-journal.json'
        marker.write_text(json.dumps({'schema':'integration-release-journal-v1',
                           'state':'FOUNDATION_MAINTENANCE','maintenance_id':'fixture'}))
        self.assertTrue(self.verify(maintenance_id='fixture'))
        with self.assertRaises(witness.WitnessHold): self.verify(maintenance_id='alien')
        with self.assertRaises(witness.WitnessHold): self.verify()

    def test_trusted_release_gate_and_repair(self):
        with self.assertRaisesRegex(witness.WitnessHold,'release closure'): self.verify(release=lambda:False)
        policy = self.root / 'dev/wrapper-coder/tools/coordinator_repair_profiles.py'
        policy.write_text("PROFILE_REGISTRY = ('enabled',)")
        with self.assertRaisesRegex(witness.WitnessHold,'registry'): self.verify()

    def test_seal_and_unsafe_input(self):
        self.pin.write_text('private nonsense')
        with self.assertRaisesRegex(witness.WitnessHold,'seal mismatch'): self.verify()
        self.seal()
        self.pin.chmod(0o644)
        with self.assertRaisesRegex(witness.WitnessHold,'unsafe private'): self.verify()
        self.pin.chmod(0o600)
        (self.root / '.state/next-scan.json').symlink_to(self.root / 'missing')
        with self.assertRaisesRegex(witness.WitnessHold,'unsafe path'): self.verify()

    def test_committed_wal_never_ignored(self):
        with closing(sqlite3.connect(self.dbpaths['jobs'])) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute("UPDATE records SET policies='private'")
            writer.commit()
            with self.assertRaisesRegex(witness.WitnessHold,'nonempty WAL'): self.verify()
            # Exercise the WAL-aware reader branch on this disposable DB. This
            # mock models only the filesystem flag, not an actual host mount.
            with patch.object(os,'statvfs',return_value=type('Fs',(),{'f_flag':os.ST_RDONLY})()):
                with self.assertRaisesRegex(witness.WitnessHold,'differs'): self.verify()

    def test_read_only_wal_connection_during_witness_is_a_hold(self):
        path = self.dbpaths['jobs']
        with closing(sqlite3.connect(path)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
        wal, shm = (Path(str(path) + suffix) for suffix in ('-wal', '-shm'))
        self.assertFalse(wal.exists())
        self.assertFalse(shm.exists())
        with self.assertRaisesRegex(witness.WitnessHold, 'database changed during read'):
            with witness.database(path) as protected:
                original = protected.execute('SELECT COUNT(*) FROM records').fetchone()
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as reader:
                    reader.execute('PRAGMA query_only=ON')
                    self.assertEqual(reader.execute('SELECT COUNT(*) FROM records').fetchone(), original)
                    self.assertEqual(wal.stat().st_size, 0)
                    self.assertTrue(shm.is_file())
        with witness.database(path) as protected:
            self.assertEqual(protected.execute('SELECT COUNT(*) FROM records').fetchone(), original)

    def test_two_store_acknowledgement(self):
        key, consumer = 'original', 'repair-coordinator'
        payload = '{"private":"stored locally"}'
        digest = hashlib.sha256(payload.encode()).hexdigest()
        receipt = json.dumps({'outcome_id':key,'record_sha256':digest,'consumer':consumer,'disposition':'ACCEPTED'})
        fields = (key,consumer,digest,receipt,hashlib.sha256(receipt.encode()).hexdigest())
        self.sql('jobs','INSERT INTO scrape_outcomes VALUES (?,?)',(key,payload))
        self.sql('jobs',"INSERT INTO scrape_outcome_deliveries VALUES (?,'wrapper-coordinator','then')",(key,))
        self.sql('coordinator','INSERT INTO scrape_outcome_delivery_receipts VALUES (?,?,?,?,?)',fields)
        with self.assertRaisesRegex(witness.WitnessHold,'receiver committed'): self.verify()
        self.sql('jobs','INSERT INTO scrape_outcome_deliveries VALUES (?,?,?)',(key,consumer,'now'))
        self.sql('jobs','INSERT INTO scrape_outcome_delivery_receipts VALUES (?,?,?,?,?)',fields)
        self.seal()
        self.assertTrue(self.verify())
        self.sql('coordinator',"UPDATE scrape_outcome_delivery_receipts SET receipt='private drift'")
        with self.assertRaisesRegex(witness.WitnessHold,'receiver receipt differs'): self.verify()

    def test_host_checkpoint_adapter(self):
        check = witness.bind_host_witness(self.root,self.pin,self.digest,maintenance_id='test',
            verify_release_hold=lambda stage, target: target == 'INSTALLED')
        for stage in ('preflight','restoring','restored'):
            self.assertTrue(check(stage,'INSTALLED'))
        with self.assertRaises(witness.WitnessHold): check('bad','INSTALLED')
        with self.assertRaises(witness.WitnessHold): check('preflight','ROLLED_BACK')
        with self.assertRaises(witness.WitnessHold): check('held','INSTALLED')

    def test_owned_real_fixture_release_lease(self):
        path = self.root / '.state/scraper.lock'
        with path.open('wb') as lease:
            with self.assertRaises(witness.WitnessHold): witness.verify_release_lease(self.root, os.getpid())
            fcntl.flock(lease, fcntl.LOCK_EX)
            self.assertTrue(witness.verify_release_lease(self.root, os.getpid()))
            with self.assertRaises(witness.WitnessHold): witness.verify_release_lease(self.root, os.getppid())


if __name__ == '__main__':
    unittest.main()
