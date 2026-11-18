"""Stopped-service release transaction; no task or workspace directory is deleted.

Invoke through the reviewed rollout_controller CLI; direct engine entrypoints share ownership.
"""
import json
import fcntl
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import sqlite3
import stat


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_json(path, value):
    temp = path.with_suffix('.new')
    with temp.open('w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    sync_directory(path.parent)


def backup_database(source, target):
    with sqlite3.connect('file:' + str(source) + '?mode=ro', uri=True) as before:
        with sqlite3.connect(target) as out:
            before.backup(out)
            if out.execute('pragma quick_check').fetchone()[0] != 'ok':
                raise ValueError('Rollback database integrity failed')
    with target.open('rb') as stream:
        os.fsync(stream.fileno())


def restore_database(backup, target):
    temporary = target.with_suffix('.rollback-new')
    shutil.copy2(backup, temporary)
    with temporary.open('rb') as stream:
        os.fsync(stream.fileno())
    for suffix in ('-wal', '-shm'):
        path = Path(str(target) + suffix)
        if path.exists():
            path.unlink()
    temporary.replace(target)
    sync_directory(target.parent)


@contextmanager
def deployment_owner(base, *, recovery_archive=None):
    """Cross-process owner plus durable unfinished-transaction barrier.

    The lock inode is permanent, outside published directories. Never unlink it.
    A crashed process releases flock, but its pending record still forbids apply.
    """
    original = Path(base).absolute()
    if not original.is_dir() or any(p.is_symlink() for p in (original, *original.parents)):
        raise ValueError('Deployment base must be an ordinary non-symlinked directory')
    base = original.resolve()
    repairs = base / 'repairs'
    if repairs.is_symlink():
        raise ValueError('Symlinked deployment ownership directory')
    repairs.mkdir(mode=0o700, exist_ok=True)
    sync_directory(base)
    lock_path = repairs / 'deployment.lock'
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
            raise ValueError('Deployment lock must have exactly one link')
        os.fsync(fd)
        sync_directory(repairs)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another deployment operation owns this base') from None
        pending_path = repairs / 'deployment-pending.json'
        if pending_path.is_symlink():
            raise ValueError('Symlinked deployment transaction record')
        try:
            pending = json.loads(pending_path.read_text()) if pending_path.exists() else None
        except (ValueError, OSError):
            raise ValueError('Unreadable durable deployment transaction record') from None
        if pending_path.exists() and (not isinstance(pending, dict) or pending.get('version') != 1
                or pending.get('base') != str(base) or not isinstance(pending.get('archive'), str)
                or not isinstance(pending.get('initial_journal'), dict)):
            raise ValueError('Invalid durable deployment transaction record')
        if recovery_archive is None:
            if pending is not None:
                raise ValueError('Unfinished deployment requires matching recovery')
        elif (not isinstance(pending, dict) or pending.get('version') != 1
              or pending.get('base') != str(base)
              or pending.get('archive') != str(Path(recovery_archive).resolve())):
            raise ValueError('No matching unfinished deployment transaction')
        yield pending_path, pending
    finally:
        os.close(fd)


def _clear_pending(pending_path):
    pending_path.unlink()
    sync_directory(pending_path.parent)


def rollout(base, prepared, archive, controller, *, fault=lambda phase: None):
    raw_base = base
    base, prepared, archive = map(lambda p: Path(p).resolve(), (base, prepared, archive))
    with deployment_owner(raw_base) as (pending_path, _):
        try:
            return _rollout_owned(base, prepared, archive, controller, pending_path, fault=fault)
        finally:
            if pending_path.exists() and (archive / 'journal.json').exists():
                journal = json.loads((archive / 'journal.json').read_text())
                if journal.get('phase') in ('INSTALLED_PAUSED', 'ROLLED_BACK'):
                    _clear_pending(pending_path)


def _rollout_owned(base, prepared, archive, controller, pending_path, *, fault=lambda phase: None):
    """Controller owns reviewed preflight/migration/health; callbacks close DBs.

    No controller method enables queue, campaign, or pilot. Rehearsal uses only
    a copy of the fresh backup. Source and DB share a stopped-service rollback
    boundary. Persistent journal supports inspection after process interruption.
    """
    base, prepared, archive = map(Path, (base, prepared, archive))
    if archive.exists():
        raise ValueError('Rollback archive already exists')
    controller.preflight(base, prepared)
    journal = dict(version=1, phase='PREPARED', base=str(base), prepared=str(prepared),
                   published=[], service_before=controller.service_state(),
                   reviewed_binding=controller.recovery_binding(base, prepared, archive))
    save_json(pending_path, dict(version=1, base=str(base), archive=str(archive), initial_journal=journal))
    fault('after_pending')
    archive.mkdir(parents=True, mode=0o700)
    save_json(archive / 'journal.json', journal)
    database = base / 'tasks/tasks.sqlite3'
    published, stopped, backup_ready = [], False, False
    try:
        controller.stop()
        stopped = True
        controller.assert_stopped()
        controller.preflight(base, prepared)
        backup_database(database, archive / 'tasks-before.sqlite3')
        controller.capture_before(base, archive)
        backup_ready = True
        journal.update(phase='BACKED_UP', backup_ready=True)
        save_json(archive / 'journal.json', journal)
        controller.rehearse(archive / 'tasks-before.sqlite3', archive)
        fault('after_rehearsal')
        for name in ('tools', 'jetson'):
            old, new = base / name, prepared / name
            if not old.is_dir() or old.is_symlink() or not new.is_dir() or new.is_symlink():
                raise ValueError('Ordinary release directories required: ' + name)
            published.append(name)
            journal.update(phase='PUBLISHING', published=published[:])
            save_json(archive / 'journal.json', journal)
            old.rename(archive / (name + '-before'))
            sync_directory(base)
            sync_directory(archive)
            new.rename(old)
            sync_directory(base)
            sync_directory(prepared)
            fault('after_publish_' + name)
        controller.migrate(base, archive, fault)
        controller.verify_stopped(base, archive)
        fault('after_migration')
        controller.start()
        controller.verify_running(base, archive)
        journal['phase'] = 'INSTALLED_PAUSED'
        save_json(archive / 'journal.json', journal)
        fault('after_terminal_journal')
        return journal
    except BaseException as exc:
        journal.update(phase='ROLLING_BACK', error=type(exc).__name__ + ': ' + str(exc)[:500])
        save_json(archive / 'journal.json', journal)
        try:
            if stopped:
                controller.stop()
                controller.assert_stopped()
                for name in reversed(published):
                    current = base / name
                    if not (archive / (name + '-before')).exists():
                        continue
                    if current.exists():
                        current.rename(archive / (name + '-failed'))
                    (archive / (name + '-before')).rename(current)
                    sync_directory(base)
                    sync_directory(archive)
                if backup_ready:
                    restore_database(archive / 'tasks-before.sqlite3', database)
                    controller.verify_restored(base, archive)
                sync_directory(base)
                controller.restore_service(journal['service_before'])
            journal['phase'] = 'ROLLED_BACK'
            save_json(archive / 'journal.json', journal)
        except BaseException as rollback_error:
            journal.update(phase='ROLLBACK_FAILED', rollback_error=type(rollback_error).__name__ + ': ' + str(rollback_error)[:500])
            save_json(archive / 'journal.json', journal)
            raise RuntimeError('Rollback failed; keep scheduling stopped and inspect ' + str(archive)) from rollback_error
        raise


def validate_journal(journal):
    if (journal.get('version') != 1 or journal.get('phase') not in
            ('PREPARED', 'BACKED_UP', 'PUBLISHING', 'ROLLING_BACK', 'ROLLBACK_FAILED', 'INSTALLED_PAUSED', 'ROLLED_BACK')
            or journal.get('published') not in ([], ['tools'], ['tools', 'jetson'])
            or type(journal.get('backup_ready', False)) is not bool
            or not isinstance(journal.get('base'), str) or not isinstance(journal.get('prepared'), str)
            or not isinstance(journal.get('service_before'), dict)):
        raise ValueError('Invalid or completed publication journal')


def recover_archive(archive, controller):
    archive = Path(archive).resolve()
    # Explicit controller base, never a journal-supplied lock namespace.
    base = Path(controller.base).resolve()
    with deployment_owner(controller.base, recovery_archive=archive) as (pending_path, pending):
        initial = pending.get('initial_journal')
        if not isinstance(initial, dict):
            raise ValueError('Invalid durable transaction binding')
        validate_journal(initial)
        controller.validate_recovery(initial, archive)
        journal_path = archive / 'journal.json'
        if journal_path.exists():
            journal = json.loads(journal_path.read_text())
            validate_journal(journal)
            if any(journal.get(k) != initial.get(k) for k in ('base', 'prepared', 'service_before', 'reviewed_binding')):
                raise ValueError('Journal differs from durable transaction binding')
            controller.validate_recovery(journal, archive)
        else:
            # Pending was durable before any service or publication action.
            # Reconstruct only the matching initial journal, not a new transaction.
            archive.mkdir(parents=True, exist_ok=True, mode=0o700)
            if any(archive.iterdir()):
                raise ValueError('Unjournaled archive is not empty')
            journal = initial
            save_json(journal_path, journal)
        if journal.get('phase') == 'INSTALLED_PAUSED':
            controller.verify_running(base, archive)
            _clear_pending(pending_path)
            return journal
        if journal.get('phase') == 'ROLLED_BACK':
            controller.stop()
            controller.assert_stopped()
            if journal.get('backup_ready'):
                controller.verify_restored(base, archive)
            else:
                controller.preflight(base, Path(journal['prepared']))
            controller.restore_service(journal['service_before'])
            _clear_pending(pending_path)
            return journal
        result = _recover_owned(archive, controller)
        _clear_pending(pending_path)
        return result


def _recover_owned(archive, controller):
    """Recover an interrupted transaction without interpreting absence as success."""
    archive = Path(archive)
    journal = json.loads((archive / 'journal.json').read_text())
    validate_journal(journal)
    controller.validate_recovery(journal, archive)
    base = Path(journal['base'])
    controller.stop()
    controller.assert_stopped()
    if journal['published'] and not journal.get('backup_ready'):
        raise ValueError('Incomplete rollback evidence; service remains stopped')
    for name in reversed(journal['published']):
        old = archive / (name + '-before')
        current = base / name
        if not old.exists():
            # Intent was saved before rename, or an earlier recovery restored it.
            continue
        if current.exists():
            failed = archive / (name + '-interrupted')
            if failed.exists():
                raise ValueError('Ambiguous interrupted release; service remains stopped')
            current.rename(failed)
        old.rename(current)
        sync_directory(base)
        sync_directory(archive)
    if journal.get('backup_ready'):
        restore_database(archive / 'tasks-before.sqlite3', base / 'tasks/tasks.sqlite3')
        controller.verify_restored(base, archive)
    else:
        controller.preflight(base, Path(journal['prepared']))
    controller.restore_service(journal['service_before'])
    journal['phase'] = 'ROLLED_BACK'
    save_json(archive / 'journal.json', journal)
    return journal


if __name__ == '__main__':
    raise SystemExit('Use rollout_controller.py with reviewed inputs and independent QA approval.')
