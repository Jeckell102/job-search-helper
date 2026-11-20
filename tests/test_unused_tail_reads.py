"""Append safety and payload coverage using an offline Sheets service."""
import copy
import unittest

from job_search_helper.repository import GoogleRepository, RepositoryError
from job_search_helper.sheet_profile import COMPACT_SCHEMAS
from sheets_fixture import RangeSheets


RULE = {'strict': True, 'condition': {'type': 'ONE_OF_LIST',
        'values': [{'userEnteredValue': 'Open'}]}}


def insert(key='new', **values):
    return {'tab': 'Job History', 'identity': {'Job Key': key},
            'values': values, 'append_if_missing': True}


class UnusedTailReadTests(unittest.TestCase):
    def make(self, grid_rows=1000):
        service = RangeSheets({'Job History': [
            {'Job Key': 'one', 'Company': 'Acme'},
            {'Job Key': 'two', 'Company': 'Acme'},
        ]}, schemas=COMPACT_SCHEMAS)
        service.sheet('Job History')['properties']['gridProperties']['rowCount'] = grid_rows
        repo = GoogleRepository(service, 'fixture', schemas=COMPACT_SCHEMAS,
                                min_request_interval=0)
        return service, repo

    def test_large_empty_tail_does_not_download_dropdown_rules(self):
        service, repo = self.make(5000)
        for row in range(3, 5000):
            for header in ('Added to Opportunities?', 'Job Status', 'Review Status', 'Fit Level'):
                service.set_cell('Job History', row, header,
                                 cell={'dataValidation': copy.deepcopy(RULE)})
        result = repo.commit([insert(**{'Job Status': 'Open'})])
        self.assertEqual(result['inserted'], 1)
        # The fixture retains empty grid cells in identity-column responses.
        # Even with that overhead, the validation-heavy tail must stay absent.
        self.assertLess(service.response_bytes, 1_000_000)
        grid_ranges = [area for call in service.get_calls if not call.get('values_api')
                       for area in call.get('ranges', [])]
        self.assertIn("'Job History'!A4:Z4", grid_ranges)
        self.assertNotIn("'Job History'!A4:Z5000", grid_ranges)
        self.assertEqual(repo.read_row('Job History', 4)['Job Key'], 'new')
        cell = service.sheet('Job History')['data'][0]['rowData'][3]['values'][
            COMPACT_SCHEMAS['Job History'].index('Job Status')]
        self.assertEqual(cell['dataValidation'], RULE)

    def test_orphan_note_and_blank_formula_determine_append_position(self):
        service, repo = self.make()
        service.set_cell('Job History', 300, 'Review Notes', 'Keep my note')
        formula = {'userEnteredValue': {'formulaValue': '=IF(TRUE,"","")'},
                   'effectiveValue': {'stringValue': ''}}
        service.set_cell('Job History', 700, 'Job Title', cell=copy.deepcopy(formula))
        self.assertEqual(repo.commit([insert()])['inserted'], 1)
        self.assertEqual(repo.read_row('Job History', 702)['Job Key'], 'new')
        self.assertEqual(repo.read_row('Job History', 301)['Review Notes'], 'Keep my note')
        cell = service.sheet('Job History')['data'][0]['rowData'][700]['values'][
            COMPACT_SCHEMAS['Job History'].index('Job Title')]
        self.assertEqual(cell, formula)

    def test_zero_and_false_are_occupied_cells(self):
        service, repo = self.make()
        for row, value in [(300, {'numberValue': 0}), (700, {'boolValue': False})]:
            service.set_cell('Job History', row, 'Review Notes',
                             cell={'userEnteredValue': value, 'effectiveValue': value})
        self.assertEqual(repo.commit([insert()])['inserted'], 1)
        self.assertEqual(repo.read_row('Job History', 702)['Job Key'], 'new')

    def test_destination_validation_is_still_enforced(self):
        service, repo = self.make()
        service.set_cell('Job History', 3, 'Job Status', cell={'dataValidation': RULE})
        with self.assertRaises(RepositoryError):
            repo.commit([insert(**{'Job Status': 'Forbidden'})])
        self.assertEqual(service.batches, [])

    def test_content_arriving_at_destination_never_shifts_write_to_unchecked_row(self):
        service, repo = self.make()
        def before_read(call):
            if (not service.get_calls[-1].get('values_api')
                    and "'Job History'!A4:Z4" in call.get('ranges', [])):
                service.set_cell('Job History', 3, 'Review Notes', 'Concurrent note')
        service.before_read = before_read
        with self.assertRaisesRegex(RepositoryError, 'destination changed'):
            repo.commit([insert()])
        self.assertEqual(service.batches, [])
        service.before_read = None
        self.assertEqual(repo.read_row('Job History', 4)['Review Notes'], 'Concurrent note')

    def test_content_arriving_beyond_destination_is_caught_by_final_tail_check(self):
        service, repo = self.make()
        scans = 0
        def before_read(call):
            nonlocal scans
            if service.get_calls[-1].get('valueRenderOption') == 'FORMULA':
                scans += 1
                if scans == 2:
                    service.set_cell('Job History', 800, 'Review Notes', 'Late note')
        service.before_read = before_read
        with self.assertRaisesRegex(RepositoryError, 'tail changed'):
            repo.commit([insert()])
        self.assertEqual(service.batches, [])
        service.before_read = None
        self.assertEqual(repo.read_row('Job History', 801)['Review Notes'], 'Late note')

    def test_omitted_tail_response_aborts_before_writing(self):
        service, repo = self.make()
        execute = repo._execute
        def omitted(request, action):
            response = execute(request, action)
            if action == 'read' and service.get_calls[-1].get('valueRenderOption') == 'FORMULA':
                return {'valueRanges': []}
            return response
        repo._execute = omitted
        with self.assertRaisesRegex(RepositoryError, 'omitted an append-tail range'):
            repo.commit([insert()])
        self.assertEqual(service.batches, [])

    def test_occupied_column_without_header_is_not_silently_ignored(self):
        service, repo = self.make()
        service.set_cell('Job History', 400, 'Review Notes', '')
        cells = service.sheet('Job History')['data'][0]['rowData'][400]['values']
        cells.extend({} for _ in range(20 - len(cells)))
        cells[19] = {'userEnteredValue': {'stringValue': 'Unlabelled content'},
                     'effectiveValue': {'stringValue': 'Unlabelled content'}}
        with self.assertRaisesRegex(RepositoryError, 'no header'):
            repo.commit([insert()])
        self.assertEqual(service.batches, [])

    def test_full_grid_can_still_grow_without_out_of_bounds_reads(self):
        service, repo = self.make(3)
        self.assertEqual(repo.commit([insert()])['inserted'], 1)
        self.assertTrue(any('appendDimension' in request for batch in service.batches
                            for request in batch['body']['requests']))
        self.assertEqual(repo.read_row('Job History', 4)['Job Key'], 'new')

    def test_sequential_inserts_updates_and_replay_keep_one_row_per_identity(self):
        service, repo = self.make()
        ops = [insert('new-1', **{'Job Title': 'First'}),
               {'tab': 'Job History', 'identity': {'Job Key': 'new-1'},
                'values': {'Job Title': 'Final'}}, insert('new-2')]
        self.assertEqual(repo.commit(ops)['inserted'], 2)
        self.assertEqual(repo.commit(ops)['inserted'], 0)
        rows = repo.read('Job History')
        self.assertEqual([row['Job Key'] for row in rows], ['one', 'two', 'new-1', 'new-2'])
        self.assertEqual(rows[2]['Job Title'], 'Final')

    def test_cached_append_still_sees_new_orphan_content(self):
        service, repo = self.make()
        repo.commit([insert('new-1')])
        service.set_cell('Job History', 400, 'Review Notes', 'Later manual note')
        self.assertEqual(repo.commit([insert('new-2')])['inserted'], 1)
        self.assertEqual(repo.read_row('Job History', 402)['Job Key'], 'new-2')
        self.assertEqual(repo.read_row('Job History', 401)['Review Notes'], 'Later manual note')


if __name__ == '__main__':
    unittest.main()
