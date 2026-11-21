"""Independent negative probe: foreign concurrent duplicate row is not atomically excluded."""
import pytest

import scoped_manual_pilot_intake_v2 as intake
import test_scoped_manual_pilot_intake_v2 as candidate
from job_search_helper.repository import RepositoryError


def test_foreign_marker_and_duplicate_row_can_split_the_atomic_claim(tmp_path):
    fixture = candidate.enrolled.__wrapped__(tmp_path)
    enrolled = next(fixture)
    try:
        _local, remote, service, _custody, scope = enrolled
        row = intake._row(scope)

        def foreign_append_between_preflight_and_candidate_batch():
            sheet = service.sheet(candidate.TAB)
            bounds = sheet['tables'][0]['range']
            values = [
                {'userEnteredValue': {'stringValue': row[header]},
                 'effectiveValue': {'stringValue': row[header]}}
                if header in row else {}
                for header in candidate.HEADERS
            ]
            sheet['data'][0]['rowData'].insert(
                bounds['endRowIndex'], {'values': values})
            bounds['endRowIndex'] += 1
            service.markers[987654321] = {
                'metadataId': 987654321, 'metadataKey': 'foreign',
                'metadataValue': 'foreign', 'location': {'spreadsheet': True},
                'visibility': 'DOCUMENT',
            }

        service.before_write = foreign_append_between_preflight_and_candidate_batch
        with pytest.raises(RepositoryError, match='Multiple rows'):
            candidate.invoke(enrolled)
        assert len(remote.read(candidate.TAB)) == 4
        assert len(enrolled[0].read(candidate.TAB)) == 1
    finally:
        next(fixture, None)
