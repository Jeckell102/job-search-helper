"""Exact one-file coordinator maintenance; no task, app or inference writes."""
from hashlib import sha256
import json
from pathlib import Path
import stat

RELATIVE = 'dev/wrapper-coder/tools/coordinator.py'
BEFORE = 'dcf6f14ea4ff15e6c221ff3f46c29523419d931dfbf0dffe6e2edd6b0f427a91'
AFTER = '3d5d42249f4e8b277e3d86de57658c2275214629b78aff9cd61fbcb8d65680d4'
RELEASE = 'REL-2a5c7bb2ad922f73cf868d15'
TASK = 'WRAP-fbb9ff24d3'
SCHEMA = 'embraer-coordinator-forward-v1'
SERVICE = 'wrapper-development-host.service'


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def digest(value):
    return sha256(canonical(value)).hexdigest()


def require(value, reason):
    if not value:
        raise ValueError(reason)


def transition_record(record):
    require(isinstance(record, dict) and set(record) == {
        'schema', 'release_id', 'task_id', 'path', 'before_sha256', 'after_sha256',
        'before_reference', 'snapshot', 'snapshot_sha256', 'predecessor',
    }, 'Unknown coordinator transition record')
    require(record['schema'] == SCHEMA and record['release_id'] == RELEASE
            and record['task_id'] == TASK and record['path'] == RELATIVE
            and record['before_sha256'] == BEFORE and record['after_sha256'] == AFTER
            and record['snapshot_sha256'] == digest(record['snapshot'])
            and isinstance(record['before_reference'], list)
            and len(record['before_reference']) == 7
            and record['before_reference'][5] == BEFORE,
            'Coordinator transition differs from approved exact scope')
    return record


def apply(*, project, candidate, receipt_directory, atomic, guard, snapshot,
          approved_snapshot_sha256, stop, stopped, start, ready, reference,
          rollback_only=False):
    """Reuses accepted atomic helpers; native owner supplies guarded callbacks."""
    root = Path(receipt_directory)
    require(root.resolve(strict=True) == root and stat.S_IMODE(root.stat().st_mode) == 0o700,
            'Private physical receipt directory is required')
    target = Path(project) / RELATIVE
    require(sha256(candidate).hexdigest() == AFTER, 'Candidate differs from accepted coordinator')
    intent_path, backup, receipt_path = root/'intent.json', root/'coordinator.py.before', root/'receipt.json'
    require(not receipt_path.exists(), 'Existing terminal maintenance receipt must not be replayed')
    with atomic._deployment_lock(Path(project)), guard() as predecessor:
        current = snapshot()
        require(digest(current) == approved_snapshot_sha256, 'Paused task observation changed')
        if intent_path.exists():
            require(rollback_only, 'Unfinished forward transaction requires explicit rollback')
            intent = transition_record(json.loads(atomic._read(intent_path)[0]))
            require(intent['snapshot'] == current and intent['predecessor'] == predecessor,
                    'Recovery differs from original coordinator custody')
            before, attrs = atomic._read(backup)
        else:
            require(not rollback_only and not backup.exists(), 'Unexpected coordinator recovery state')
            before, attrs = atomic._read(target)
            require(sha256(before).hexdigest() == BEFORE, 'Installed coordinator differs from before pin')
            intent = transition_record(dict(schema=SCHEMA, release_id=RELEASE, task_id=TASK,
                path=RELATIVE, before_sha256=BEFORE, after_sha256=AFTER,
                before_reference=reference(target), snapshot=current,
                snapshot_sha256=digest(current), predecessor=predecessor))
            atomic._write_new_private(backup, before)
            atomic._write_new_private(intent_path, canonical(intent))
        require(sha256(before).hexdigest() == BEFORE, 'Backup differs from original coordinator')
        mode = intent['before_reference'][2]
        terminal_published = False
        attempted_stop = False
        try:
            attempted_stop = True
            stop(SERVICE)
            require(stopped() is True, 'Wrapper did not settle before source replacement')
            data, actual = atomic._read(target)
            require(sha256(data).hexdigest() in {BEFORE, AFTER}
                    and stat.S_IMODE(actual.st_mode) == mode
                    and [actual.st_uid, actual.st_gid] == intent['before_reference'][3:5],
                    'Coordinator drifted outside owned before/after images')
            atomic._write_atomic(target, before if rollback_only else candidate, mode)
            start(SERVICE)
            evidence = ready(BEFORE if rollback_only else AFTER, intent)
            require(snapshot() == current, 'Task or receipt changed during wrapper maintenance')
            receipt = dict(schema=SCHEMA, status='ROLLED_BACK' if rollback_only else 'INSTALLED',
                           transition=intent, current_reference=reference(target), restart=evidence)
            raw = canonical(receipt)
            try:
                atomic._write_new_private(receipt_path, raw)
            except OSError:
                if atomic._visible_exact(receipt_path, raw):
                    terminal_published = True
                raise
            terminal_published = True
            return receipt
        finally:
            if attempted_stop and not terminal_published:
                # Service transport failure never authorizes overwriting an active host.
                try:
                    stop(SERVICE)
                except Exception:
                    pass
                require(stopped() is True, 'Wrapper stop uncertain; preserve recovery intent')
                data, actual = atomic._read(target)
                require(sha256(data).hexdigest() in {BEFORE, AFTER}
                        and stat.S_IMODE(actual.st_mode) == mode
                        and [actual.st_uid, actual.st_gid] == intent['before_reference'][3:5],
                        'Refusing rollback over unrelated coordinator changes')
                atomic._write_atomic(target, before, mode)
                start(SERVICE)
                evidence = ready(BEFORE, intent)
                require(snapshot() == current, 'Task or receipts changed during rollback')
                atomic._write_new_private(receipt_path, canonical(dict(schema=SCHEMA,
                    status='ROLLED_BACK', transition=intent, current_reference=reference(target), restart=evidence)))
