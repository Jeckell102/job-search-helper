"""Read one complete Embraer operator outcome into a non-authorizing pilot input."""

from contextlib import closing
from pathlib import Path
import re

from job_search_helper.scrape_outcome_delivery import OutcomeDelivery


COMPANY_ID = 'COMP-0634'
RELEASE_ID = 'REL-2a5c7bb2ad922f73cf868d15'
BASELINE_SHA256 = 'dc4b353766486a305a742ec10ada5494885f42967b60adb269db610f01b6063d'
_HEX = re.compile(r'[0-9a-f]{64}\Z')


def read_operator_embraer_enrollment(*, state_root, request_id, request_sha256,
                                     expected_source_manifest_sha256,
                                     repository_factory, source_reader):
    """Return the six process fields only after reopening the durable proof.

    The two injected readers make this function suitable for a native armer and
    for an offline fixture; neither queues, fetches, nor changes the database.
    """
    root = Path(state_root)
    if (not root.is_absolute() or root.is_symlink() or root.resolve(strict=True) != root
            or not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{2,127}', request_id)
            or not isinstance(request_sha256, str) or not _HEX.fullmatch(request_sha256)
            or not isinstance(expected_source_manifest_sha256, str)
            or not _HEX.fullmatch(expected_source_manifest_sha256)):
        raise ValueError('embraer_enrollment_input')
    with closing(repository_factory(root / 'jobs.sqlite3')) as repository:
        rows = repository.db.execute(
            'SELECT outcome_id FROM scrape_outcomes WHERE request_id=? LIMIT 2', (request_id,)).fetchall()
        if len(rows) != 1:
            raise ValueError('embraer_enrollment_outcome')
        row = repository._outcome_delivery_rows('repair-coordinator', outcome_id=rows[0][0])
        if len(row) != 1:
            raise ValueError('embraer_enrollment_delivery')
        record, _digest, stale, _acknowledged, _ = OutcomeDelivery(repository, None)._preflight(row[0])
        if stale:
            raise ValueError('embraer_enrollment_stale')
        proof = source_reader(repository, record, request_sha256)
    source_files = proof.get('source_files') if isinstance(proof, dict) else None
    runtime = proof.get('runtime') if isinstance(proof, dict) else None
    if (not isinstance(proof, dict)
            or not isinstance(record, dict) or record.get('outcome_id') != rows[0][0]
            or record.get('identity', {}).get('company_id') != COMPANY_ID
            or proof.get('request_id') != request_id or proof.get('request_sha256') != request_sha256
            or proof.get('source_revision') != record.get('identity', {}).get('source_revision')
            or proof.get('evidence_code') != 'breezy_embraer_brand_heading'
            or not isinstance(source_files, dict)
            or set(source_files) != {'src/job_search_helper/shared_boards.py', 'src/job_search_helper/ats.py'}
            or any(not isinstance(value, str) or not _HEX.fullmatch(value) for value in source_files.values())
            or not isinstance(runtime, dict) or runtime.get('state') != 'COMPLETE'
            or runtime.get('release_id') != RELEASE_ID
            or runtime.get('source_manifest_sha256') != expected_source_manifest_sha256):
        raise ValueError('embraer_enrollment_authority')
    return {
        'request_id': request_id, 'request_sha256': request_sha256,
        'source_revision': proof['source_revision'],
        'shared_boards_sha256': source_files['src/job_search_helper/shared_boards.py'],
        'ats_sha256': source_files['src/job_search_helper/ats.py'],
        'baseline_sha256': BASELINE_SHA256,
    }, record['outcome_id']
