"""Derive one host enrollment from Crown's exact settled application request."""

import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sys


REQUEST_ID = 'operator-crown-20261122-01'
RELEASE_ID = 'REL-ede347339c8faf1806583810'
BASELINE_PIN = '3cddf0386aa4547bf36d05bd0cecb0aeea62c3bdc2db7dce54ee113808d30e1d'


def build_enrollment(repository, root, project, baseline, baseline_pin, request_id):
    from coordinator_baseline import binding, files
    from job_search_helper.integration_release import source_tree_digest
    from job_search_helper.operator_company_request import _digest, _read
    from job_search_helper.operator_embraer_settlement import read_operator_partial_source
    from job_search_helper.operator_partial_scope import CROWN, CROWN_REQUEST_ID
    from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery

    if CROWN_REQUEST_ID.fullmatch(request_id) is None:
        raise ValueError('Crown requires a project-owned request ID.')
    receipts = root / 'operator-company-requests' / 'receipts'
    path = receipts / (_digest({'request_id': request_id}) + '.json')
    if path.resolve(strict=True) != path or not path.is_file():
        raise ValueError('The exact Crown request receipt is unavailable.')
    request = _read(path)
    if not isinstance(request, dict) or request.get('request_id') != request_id:
        raise ValueError('Crown request receipt identity changed.')
    request_sha = request.get('request_sha256')
    rows = repository.db.execute(
        'SELECT outcome_id FROM scrape_outcomes WHERE request_id=? LIMIT 2', (request_id,),
    ).fetchall()
    if len(rows) != 1:
        raise ValueError('Crown request lacks a unique settled repair outcome.')
    [row] = repository._outcome_delivery_rows(CONSUMER, outcome_id=rows[0][0])
    record, _, stale, _, _ = OutcomeDelivery(repository, None)._preflight(row)
    proof = None if stale else read_operator_partial_source(repository, record, request_sha, scope=CROWN)
    if proof is None or proof['request_id'] != request_id:
        raise ValueError('The exact current Crown outcome does not reopen from its application receipts.')
    if (baseline.resolve(strict=True) != baseline or binding(files(baseline))['digest'] != baseline_pin
            or source_tree_digest(project) != source_tree_digest(baseline)):
        raise ValueError('Crown assignment baseline differs from the installed application.')
    adapter = 'src/job_search_helper/successfactors.py'
    dispatcher = 'src/job_search_helper/ats.py'
    for name in (adapter, dispatcher):
        expected = proof['source_files'][name]
        if any(sha256((base / name).read_bytes()).hexdigest() != expected for base in (project, baseline)):
            raise ValueError('Crown assignment source pin differs from the verified outcome.')
    return {
        'request_id': request_id,
        'source_revision': proof['source_revision'],
        'request_sha256': request_sha,
        'successfactors_sha256': proof['source_files'][adapter],
        'ats_sha256': proof['source_files'][dispatcher],
        'baseline_sha256': baseline_pin,
    }


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
        raise ValueError('The verified Crown runtime is not installed.')
    baseline = wrapper / 'pilot-bases' / ('crown-' + BASELINE_PIN)
    destination = InventoryInbox.destination_id(root / 'inventories.sqlite3')
    with closing(SQLiteRepository(root / 'jobs.sqlite3', destination, readonly=True)) as repository:
        result = build_enrollment(repository, root, project, baseline, BASELINE_PIN, REQUEST_ID)
    if _validate_runtime(project, root) != runtime:
        raise ValueError('The application changed while reading Crown enrollment.')
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
