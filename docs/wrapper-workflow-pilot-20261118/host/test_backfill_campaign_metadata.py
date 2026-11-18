import tempfile
import unittest

from backfill_campaign_metadata import backfill
from coordinator_store import Store


class BackfillTests(unittest.TestCase):
    def test_exact_objective_backfill_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            state = store.create('Company objective', ['tests/test_a.py'], 'develop')
            store.update(state['id'], isolated_workspace=True)
            item = {'objective': 'Company objective', 'integration': {'company_id': 'COMP-0001', 'company': 'Example', 'configured_url': 'https://example.com/jobs', 'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py']}}
            self.assertEqual(backfill(store, [item])['updated'], 1)
            self.assertEqual(backfill(store, [item])['updated'], 0)
            self.assertEqual(store.get(state['id'])['integration']['company_id'], 'COMP-0001')

    def test_partial_metadata_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            state = store.create('Company objective', ['tests/test_a.py'], 'develop')
            store.update(state['id'], isolated_workspace=True)
            before = store.all()
            with self.assertRaises(ValueError):
                backfill(store, [{'objective': 'Company objective', 'integration': {'company_id': 'COMP-0001'}}])
            self.assertEqual(store.all(), before)


if __name__ == '__main__':
    unittest.main()
