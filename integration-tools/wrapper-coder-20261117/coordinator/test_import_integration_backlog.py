import pathlib
import tempfile
import unittest
from import_integration_backlog import prepare


class ImportTests(unittest.TestCase):
    def test_completed_claimed_and_missing_tests_are_preserved_outside_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root/'tests').mkdir(); (root/'tests/test_one.py').write_text('pass\n')
            text = '### Task ledger\n| W05 | COMP-0002 Two | IMPLEMENTED_AWAITING_VALIDATION | owner | saved checkpoint |\n### Progress log\n'
            rows = []
            for i, name in enumerate(('One','Two','Three','Four'), 1):
                cid = f'COMP-{i:04}'
                text += f'### {cid} — {name}\n'
                if i == 1:
                    text += '**Current implementation status:** W01 validated complete through normal dispatch.\n'
                rows.append(dict(company_id=cid, company=name, candidate_tests=['tests/test_one.py'] if i != 3 else [], configured_url='https://example.com', work_order='W05'))
            queue, held = prepare(text, {'companies': rows}, root)
            self.assertEqual([q['company_id'] for q in queue], ['COMP-0004'])
            self.assertEqual([h['disposition'] for h in held], ['RECORDED_COMPLETE', 'EXISTING_VALIDATION_OR_CLAIM', 'NEEDS_TEST_ASSIGNMENT'])

    def test_identity_disagreement_rejects_import(self):
        with self.assertRaisesRegex(ValueError, 'identity differs'):
            prepare('### Task ledger\n### Progress log\n### COMP-0001 — One\n',
                    {'companies': [{'company_id': 'COMP-0001', 'company': 'Different'}]}, pathlib.Path('/tmp'))
