"""Derive one host enrollment from ATS Corporation's exact settled application request."""

import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sys


REQUEST_ID = 'operator-ats-20261122-01'
RELEASE_ID = 'REL-aa0e7a762a8e741c03b99692'
BASELINE_PIN = '6a49ceb6ca3786c78d4b1606276390f6011c629e2157de38935fedebd13a6e58'


def build_enrollment(repository, root, project, baseline, baseline_pin, request_id):
    from coordinator_baseline import binding, files
    from job_search_helper.integration_release import source_tree_digest
    from job_search_helper.operator_company_request import _digest, _read
    from job_search_helper.operator_embraer_settlement import read_operator_partial_source
    from job_search_helper.operator_partial_scope import ATS_CORPORATION, ATS_REQUEST_ID
    from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery

    if ATS_REQUEST_ID.fullmatch(request_id) is None:
        raise ValueError('ATS Corporation requires a project-owned request ID.')
    receipts = root / 'operator-company-requests' / 'receipts'
    path = receipts / (_digest({'request_id': request_id}) + '.json')
    if path.resolve(strict=True) != path or not path.is_file():
        raise ValueError('The exact ATS Corporation request receipt is unavailable.')
    request = _read(path)
    if not isinstance(request, dict) or request.get('request_id') != request_id:
        raise ValueError('ATS Corporation request receipt identity changed.')
    request_sha = request.get('request_sha256')
    rows = repository.db.execute(
        'SELECT outcome_id FROM scrape_outcomes WHERE request_id=? LIMIT 2', (request_id,),
    ).fetchall()
    if len(rows) != 1:
        raise ValueError('ATS Corporation request lacks a unique settled repair outcome.')
    [row] = repository._outcome_delivery_rows(CONSUMER, outcome_id=rows[0][0])
    record, _, stale, _, _ = OutcomeDelivery(repository, None)._preflight(row)
    proof = None if stale else read_operator_partial_source(repository, record, request_sha, scope=ATS_CORPORATION)
    if proof is None or proof['request_id'] != request_id:
        raise ValueError('The exact current ATS Corporation outcome does not reopen from its application receipts.')
    if (baseline.resolve(strict=True) != baseline or binding(files(baseline))['digest'] != baseline_pin
            or source_tree_digest(project) != source_tree_digest(baseline)):
        raise ValueError('ATS Corporation assignment baseline differs from the installed application.')
    from ats_operator_pilot import ATSOperatorEnrollment, ENV, SOURCE_FILES

    pins = proof['source_files']
    if set(pins) != SOURCE_FILES:
        raise ValueError('ATS source proof does not name the exact assignment files.')
    for name, expected in pins.items():
        if any(sha256((base / name).read_bytes()).hexdigest() != expected for base in (project, baseline)):
            raise ValueError('ATS Corporation assignment source pin differs from the verified outcome.')
    enrollment = {
        'request_id': request_id,
        'source_revision': proof['source_revision'],
        'request_sha256': request_sha,
        'source_files': pins,
        'baseline_sha256': baseline_pin,
    }
    ATSOperatorEnrollment.from_process_environment({ENV: json.dumps(enrollment)})
    return enrollment


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.parse_args()
    project = Path('/home/chris/job-search-helper_old')
    wrapper = project / 'dev/wrapper-coder'
    root = project / '.state'
    sys.path[:0] = [str(project), str(project / 'src'), str(wrapper / 'tools')]
    from release_admission_bootstrap import _load_environment, _validate_runtime
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.sqlite_repository import SQLiteRepository

    _load_environment(project / '.env')
    runtime = _validate_runtime(project, root)
    if runtime.get('state') != 'COMPLETE' or runtime.get('release_id') != RELEASE_ID:
        raise ValueError('The verified ATS Corporation runtime is not installed.')
    baseline = wrapper / 'pilot-bases' / ('ats-' + BASELINE_PIN)
    destination = InventoryInbox.destination_id(root / 'inventories.sqlite3')
    with closing(SQLiteRepository(root / 'jobs.sqlite3', destination, readonly=True)) as repository:
        result = build_enrollment(repository, root, project, baseline, BASELINE_PIN, REQUEST_ID)
    if _validate_runtime(project, root) != runtime:
        raise ValueError('The application changed while reading ATS Corporation enrollment.')
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
