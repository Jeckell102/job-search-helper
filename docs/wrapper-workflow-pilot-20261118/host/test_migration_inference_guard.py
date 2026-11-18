"""A stopped task is insufficient when an inference result remains uncertain."""
import json
from pathlib import Path
import tempfile
import unittest
from coordinator_store import Store
from migrate_campaign_membership import migrate_campaign_membership
from backfill_campaign_metadata import backfill_campaign_identity

class MigrationInferenceGuardTests(unittest.TestCase):
    def test_unresolved_inference_prevents_both_legacy_migrations(self):
        for status in ('DISPATCHING','UNCERTAIN'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                store=Store(Path(tmp));store.configure_queue(False)
                with store.connect() as db:
                    db.execute('INSERT INTO inference_receipts VALUES (?,?,?,?)',('request-1','historic-task',status,json.dumps({'status':status})))
                before=store.path.read_bytes()
                with self.assertRaisesRegex(ValueError,'unresolved inference'):
                    migrate_campaign_membership(store,'campaign',[],apply=True)
                with self.assertRaisesRegex(ValueError,'unresolved inference'):
                    backfill_campaign_identity(store,[],apply=True)
                self.assertEqual(store.path.read_bytes(),before)
if __name__=='__main__':unittest.main()
