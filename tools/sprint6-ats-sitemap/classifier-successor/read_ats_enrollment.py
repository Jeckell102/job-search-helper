"""Derive one host enrollment from ATS Corporation's exact settled application request."""

import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sys


REQUEST_ID = 'operator-ats-20261122-02'
RELEASE_ID = 'REL-4141919bb885000b0e7244c2'
BASELINE_PIN = '23df31abf76869b7df3517511418bba7b721a0abb6732de1d0ee55b22f1eb7c6'


PREDECESSOR = {
    'predecessor_outcome_id': 'OUT-8b214610d53e23115e70da5f',
    'predecessor_repair_key': '0d6846138372a12f8d52398a2124f220a0bf565e2cd16cae13bd6df06e71a5be',
    'predecessor_task_id': 'WRAP-9db6388719',
    'predecessor_task_state_sha256': '64d4ef964e53ea88bdd907d35b22532fceef7512a949217b5380d04382b8d96f',
    'failure_fingerprint': '9fdcfc10ac7273ab6e71f4e8552aab13397ae19ffcfe1234dbea61ace8d48125',
}
REVISION = '08ecbb56e99f89bbcb63b60c5af1197c7535e9196a997135473370895e695a32'
OLD_REQUEST_HASH = '2b81fddd38b76cc6d2007c5de68080147c9433273a466bb01cf75f34283052b0'
OLD_CYCLE = 'CYC-F0E884647EDC'
FILES = frozenset('src/job_search_helper/' + name for name in
                  ('ats.py', 'successfactors.py', 'successfactors_sitemap.py',
                   'ats_sitemap_parser.py', 'ats_job_path.py'))


def build_enrollment(repository, root, project, baseline, baseline_pin, request_id):
    from coordinator_baseline import binding, files
    from job_search_helper.integration_release import source_tree_digest
    from job_search_helper.operator_company_request import _digest, _read
    from job_search_helper.operator_embraer_settlement import read_operator_partial_source
    from job_search_helper.operator_partial_scope import ATS_CORPORATION, ATS_REQUEST_ID
    from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery

    if request_id != REQUEST_ID or baseline_pin != BASELINE_PIN or ATS_REQUEST_ID.fullmatch(request_id) is None:
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
    if (proof is None or proof['request_id'] != request_id or proof['request_sha256'] != request_sha
            or request_sha == OLD_REQUEST_HASH or proof['source_revision'] != REVISION
            or proof['runtime'].get('state') != 'COMPLETE' or proof['runtime'].get('release_id') != RELEASE_ID
            or proof['outcome_id'] != record['outcome_id'] or proof['outcome_id'] == PREDECESSOR['predecessor_outcome_id']
            or record['identity']['cycle_id'] == OLD_CYCLE or record['identity']['request_id'] != REQUEST_ID
            or record['outcome'] != 'QUALIFIED_INTEGRATION_REPAIR' or record['repair_category'] != 'pagination_regression'
            or record['failure_fingerprint'] != PREDECESSOR['failure_fingerprint']):
        raise ValueError('The exact current ATS Corporation outcome does not reopen from its application receipts.')
    if (baseline.resolve(strict=True) != baseline or binding(files(baseline))['digest'] != baseline_pin
            or source_tree_digest(project) != source_tree_digest(baseline)):
        raise ValueError('ATS Corporation assignment baseline differs from the installed application.')
    from ats_operator_pilot import ATSOperatorEnrollment, ENV, SOURCE_FILES

    pins = proof['source_files']
    if set(pins) != FILES or SOURCE_FILES != FILES:
        raise ValueError('ATS source proof does not name the exact assignment files.')
    for name, expected in pins.items():
        if any(sha256((base / name).read_bytes()).hexdigest() != expected for base in (project, baseline)):
            raise ValueError('ATS Corporation assignment source pin differs from the verified outcome.')
    enrollment = {
        'request_id': request_id,
        'successor': {**PREDECESSOR, 'outcome_id': proof['outcome_id']},
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
    if (not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.pycache_prefix != '/dev/null'
            or Path(sys.prefix).resolve() != project / '.venv'):
        raise ValueError('Use isolated production Python without bytecode.')
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
