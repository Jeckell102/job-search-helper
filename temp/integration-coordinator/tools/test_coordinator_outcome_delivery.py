import unittest

from coordinator_outcome_delivery import drain


class Repository:
    def __init__(self, records):
        self.records = list(records)
        self.acknowledged = []

    def pending_scrape_outcomes(self, consumer, *, limit):
        return self.records[:limit]

    def acknowledge_scrape_outcome(self, outcome_id, consumer):
        self.acknowledged.append((outcome_id, consumer))
        self.records = [item for item in self.records if item['outcome_id'] != outcome_id]


class Coordinator:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def command(self, value):
        self.calls.append(value)
        if self.error:
            raise self.error
        return self.result


class OutcomeDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.record = {'outcome_id': 'OUT-1', 'outcome': 'QUALIFIED_INTEGRATION_REPAIR'}

    def test_acknowledges_only_matching_successful_receipt(self):
        repository = Repository([self.record])
        coordinator = Coordinator({'ok': True, 'outcome_id': 'OUT-1', 'status': 'HELD_FOR_REPAIR_TRIAGE'})
        result = drain(repository, coordinator, consumer='test-consumer')
        self.assertEqual(repository.acknowledged, [('OUT-1', 'test-consumer')])
        self.assertEqual(result['remaining'], 0)

    def test_rejection_or_exception_leaves_record_pending(self):
        for coordinator in (Coordinator({'ok': False, 'outcome_id': 'OUT-1'}),
                            Coordinator({'ok': True, 'outcome_id': 'OUT-other'}),
                            Coordinator(error=RuntimeError('unavailable'))):
            with self.subTest(coordinator=coordinator.result):
                repository = Repository([self.record])
                with self.assertRaises(RuntimeError):
                    drain(repository, coordinator, consumer='test-consumer')
                self.assertEqual(repository.acknowledged, [])
                self.assertEqual(repository.records, [self.record])

    def test_rejects_boolean_limit(self):
        with self.assertRaisesRegex(ValueError, 'limit'):
            drain(Repository([]), Coordinator({}), consumer='test-consumer', limit=True)


if __name__ == '__main__':
    unittest.main()
