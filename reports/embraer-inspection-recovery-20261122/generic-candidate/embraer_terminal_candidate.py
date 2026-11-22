"""Read-only provenance binding for one terminal Embraer generic-develop task."""

WORK_ORDER = 'breezy-embraer-brand-heading-v1'


def derive_embraer_final_diff(task, store, *, pilot_baseline):
    """Read the exact isolated workspace against its saved pilot baseline.

    It returns only content digests and manifests.  The baseline and workspace
    remain unopened for writing, and a caller cannot substitute a shared tree.
    """
    try:
        from pathlib import Path
        from coordinator_baseline import binding, files
        from coordinator_acceptance import files as acceptance_files

        task_id = task.get('id')
        workspace = Path(store.base) / task_id / 'repo'
        baseline = Path(pilot_baseline)
        if (task_id != 'WRAP-fbb9ff24d3' or not workspace.is_absolute() or not baseline.is_absolute()
                or workspace.is_symlink() or baseline.is_symlink()
                or workspace.resolve(strict=True) != workspace or baseline.resolve(strict=True) != baseline
                or not workspace.is_dir() or not baseline.is_dir()):
            return None
        before, after = files(baseline), files(workspace)
        if task.get('assignment_baseline') != binding(before) or task.get('manifest') != after:
            return None
        scope = task.get('edit_scope', {}).get('paths')
        required_sources = (task.get('integration_identity') or {}).get('source_targets')
        if (not isinstance(scope, list) or not isinstance(required_sources, list)
                or not required_sources or any(not isinstance(path, str) or not path.startswith('src/') for path in required_sources)
                or any(path not in before or path not in after for path in scope)
                or any(path not in before or path not in after for path in required_sources)):
            return None
        paths = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
        if any(path not in scope for path in paths):
            return None
        if not paths or not any(path in required_sources for path in paths):
            return None
        return {'paths': paths, 'before': {path: before[path] for path in paths},
                'after': {path: after[path] for path in paths}, 'source_manifest': after,
                'acceptance_source_manifest': acceptance_files(workspace, ('src',), False)}
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return None


def _verified_receipts(receipts, source_manifest, acceptance_source_manifest, scope, bundle):
    """Require the final normal verify receipts; do not infer completion from status."""
    from coordinator_acceptance import digest as acceptance_digest
    from coordinator_evidence import manifest_digest

    # Ordinary ``Store.receipts`` rows have no status column: a null result is
    # the sole durable indication that a tool intent has not settled.
    if any(receipt.get('result') is None for receipt in receipts):
        return False
    source_digest = manifest_digest(source_manifest)
    acceptance_source_digest = acceptance_digest(acceptance_source_manifest)
    tests = [r for r in receipts if r.get('phase') == 'verify' and r.get('name') == 'code_test'
             and (r.get('result') or {}).get('ok')
             and (r['result'].get('result') or {}).get('exit_code') == 0
             and r['result'].get('source_unchanged_during_test') is True]
    acceptance = [r for r in receipts if r.get('phase') == 'verify' and r.get('name') == 'acceptance_test'
                  and (r.get('result') or {}).get('ok')
                  and (proof := r['result'].get('result') or {}).get('exit_code') == 0
                  and proof.get('independent_acceptance') is True
                  and proof.get('acceptance_bundle_digest') == bundle['digest']
                  and proof.get('edit_scope_digest') == scope['digest']
                  and proof.get('edit_scope_version') == scope['version']
                  and proof.get('source_manifest_digest') == acceptance_source_digest]
    diffs = [r for r in receipts if r.get('phase') == 'verify' and r.get('name') == 'code_diff'
             and (r.get('result') or {}).get('ok')
             and r['result'].get('source_unchanged_during_diff') is True
             and r['result'].get('source_manifest_sha256') == source_digest]
    return len(tests) >= 1 and len(acceptance) >= 1 and len(diffs) >= 1


def read_embraer_terminal_candidate(enrollment, store, *, project, jobs, destination,
                                    current_source_manifest, current_acceptance_source_manifest, final_diff):
    """Return an immutable candidate binding or ``None`` for every nonexact case.

    ``final_diff`` is an independently supplied read-only projection with
    ``paths`` and the exact current ``source_manifest``.  The caller owns any
    later candidate copy, qualification, installation, or retry.
    """
    try:
        if not enrollment._sources_match(project):
            return None
        source = enrollment._source(jobs, destination)
        if source is None:
            return None
        paired = enrollment._paired(store, source)
        if paired is None:
            return None
        held, task = paired
        proposal = enrollment._proposal(held, source['company'])
        if (proposal is None or not enrollment._task_matches(held, task, proposal)
                or task.get('id') != 'WRAP-fbb9ff24d3'
                or task.get('status') != 'AWAITING_LIVE_VALIDATION'
                or task.get('phase') != 'verify'
                or (task.get('integration') or {}).get('work_order') != WORK_ORDER
                or store.unresolved_inferences()):
            return None
        scope = task.get('edit_scope')
        if not isinstance(scope, dict) or not isinstance(scope.get('paths'), list):
            return None
        if (not isinstance(current_source_manifest, dict) or not current_source_manifest
                or not isinstance(current_acceptance_source_manifest, dict) or not current_acceptance_source_manifest
                or not isinstance(final_diff, dict) or final_diff.get('source_manifest') != current_source_manifest
                or not isinstance(final_diff.get('paths'), list) or not final_diff['paths']
                or any(path not in scope['paths'] for path in final_diff['paths'])):
            return None
        from coordinator_acceptance import validate_bundle, validate_scope
        from coordinator_evidence import manifest_digest
        if validate_scope(task) != scope or not (bundle := validate_bundle(store, task)):
            return None
        receipts = store.receipts(task['id'])
        if not _verified_receipts(receipts, current_source_manifest, current_acceptance_source_manifest, scope, bundle):
            return None
        return {
            'schema': 'embraer-generic-terminal-candidate-v1', 'task_id': task['id'],
            'outcome_id': source['record']['outcome_id'], 'request_id': enrollment.request_id,
            'company_id': 'COMP-0634', 'source_revision': enrollment.source_revision,
            'baseline_sha256': enrollment.baseline_sha256, 'edit_scope_digest': scope.get('digest'),
            'changed_paths': sorted(final_diff['paths']),
            'source_manifest_sha256': manifest_digest(current_source_manifest),
        }
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return None
