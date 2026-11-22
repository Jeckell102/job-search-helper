"""Join one verified live Embraer continuation to its existing candidate freezer."""

import json
from hashlib import sha256
from pathlib import Path

from embraer_terminal_candidate import (
    PARSER, derive_embraer_final_diff, read_embraer_terminal_candidate,
)
from freeze_embraer_candidate import freeze_embraer_candidate
from job_search_helper.integration_release import digest


PROJECT = Path('/home/chris/job-search-helper_old')
ATS = 'src/job_search_helper/ats.py'


def prepare_continuation_qualification(enrollment, store, *, jobs, destination, child_id, output):
    """Write an exact private qualification bundle only after live terminal proof."""
    task_root = PROJECT / 'dev/wrapper-coder/tasks'
    output = Path(output)
    if (Path(store.base) != task_root or Path(store.path) != task_root / 'tasks.sqlite3'
            or Path(store.path).resolve(strict=True) != Path(store.path)
            or output.parent.resolve(strict=True) != output.parent
            or enrollment.request_id != 'operator-embraer-20261122-03'):
        raise ValueError('The handoff requires the exact production #03 enrolled repair.')
    task = store.get(child_id)
    diff = derive_embraer_final_diff(
        task, store, pilot_baseline=enrollment.baseline_path, expected_task_id=child_id)
    if diff is None:
        raise ValueError('No current exact child diff is available.')
    binding = read_embraer_terminal_candidate(
        enrollment, store, project=PROJECT, jobs=jobs, destination=destination,
        current_source_manifest=diff['source_manifest'],
        current_acceptance_source_manifest=diff['acceptance_source_manifest'],
        final_diff=diff, expected_task_id=child_id)
    if (not binding or binding.get('changed_paths') != [PARSER]
            or not binding.get('continuation_authorization_id') or not binding.get('jetson_edit')):
        raise ValueError('No settled Jetson edit proves a qualified candidate handoff.')

    output.mkdir(mode=0o700)
    candidate = output / 'candidate'
    workspace = task_root / child_id / 'repo'
    manifest, measured = freeze_embraer_candidate(PROJECT, workspace, candidate, binding, diff)
    parser_hash = manifest['files'][PARSER]['after']['sha256']
    ats_hash = sha256((candidate / ATS).read_bytes()).hexdigest()
    if (parser_hash != binding['jetson_edit']['parser_sha256']
            or ats_hash != enrollment.ats_sha256
            or manifest['failed_request_id'] != binding['request_id']
            or manifest['validation_receipt_sha256'] != digest(measured)):
        raise ValueError('Frozen source differs from the exact Jetson or enrollment proof.')
    handoff = {
        'schema': 'embraer-continuation-qualification-handoff-v1',
        'status': 'AWAITING_INDEPENDENT_QUALIFICATION',
        'candidate_binding': binding,
        'release_manifest': manifest,
        'release_manifest_sha256': digest(manifest),
        'qualification_inputs': {
            'source_tree_sha256': manifest['source_manifest_sha256'],
            'ats_sha256': ats_hash,
            'shared_boards_sha256': parser_hash,
        },
    }
    # This receipt is the only completed staging marker. No release is authorized.
    with (output / 'QUALIFICATION_HANDOFF.json').open('x') as handle:
        json.dump(handoff, handle, indent=2, sort_keys=True)
        handle.write('\n')
    return handoff
