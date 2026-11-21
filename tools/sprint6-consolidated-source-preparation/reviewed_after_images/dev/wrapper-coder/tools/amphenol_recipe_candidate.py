"""Publish an isolated source-only candidate for one settled reviewed recipe."""
import json
import os
from pathlib import Path
import tempfile

from acquiretm_membership_recipe import TARGET_PATH, build_current_owned


def save_candidate(task_root, workspace, prepared, receipt):
    """Build once from the caller's exact owner and durable choice readback."""
    binding = prepared['binding']
    choice = receipt['accepted_recipe_choice']
    selection = {'strategy': choice['next_action'], 'evidence': choice['summary']}
    evidence = json.loads(prepared['messages'][1]['content'])['W1']
    source = (Path(workspace) / TARGET_PATH).read_bytes()
    built = build_current_owned(source, selection, binding['board'], evidence, binding)
    record = {
        **built['receipt'],
        'request_id': receipt['request_id'],
        'response_digest': receipt['response_digest'],
        'outcome_id': binding['outcome_id'],
        'company_id': binding['company_id'],
        'source_revision': binding['source_revision'],
    }
    files = {
        TARGET_PATH: built['source'].encode(),
        'reviewed.patch': built['diff'].encode(),
        'build-receipt.json': (json.dumps(record, indent=2, sort_keys=True) + '\n').encode(),
    }
    task_root = Path(task_root)
    target = task_root / 'recipe-candidate'
    if target.exists():
        if any((target / name).read_bytes() != data for name, data in files.items()):
            raise ValueError('Existing reviewed recipe candidate differs from its durable choice.')
        return target

    # The existing coordinator workspace lease serializes candidate writers.
    # One directory rename exposes the complete candidate and its receipt.
    with tempfile.TemporaryDirectory(prefix='recipe-', dir=task_root) as temporary:
        staging = Path(temporary) / 'candidate'
        for name, data in files.items():
            path = staging / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        staging.rename(target)
        descriptor = os.open(task_root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return target
