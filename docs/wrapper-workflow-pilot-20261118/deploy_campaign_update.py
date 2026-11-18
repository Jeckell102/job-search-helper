"""Stopped-service release transaction; no task or workspace directory is deleted.

CLI is disabled until the reviewed controller and independent staged QA exist.
"""
import json
import os
from pathlib import Path
import shutil
import sqlite3


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


def rollout(base, prepared, archive, controller, *, fault=lambda phase: None):
    """Controller owns reviewed preflight/migration/health; callbacks close DBs.

    No controller method enables queue, campaign, or pilot. Rehearsal uses only
    a copy of the fresh backup. Source and DB share a stopped-service rollback
    boundary. Persistent journal supports inspection after process interruption.
    """
    base, prepared, archive = map(Path, (base, prepared, archive))
    if archive.exists():
        raise ValueError('Rollback archive already exists')
    controller.preflight(base, prepared)
    archive.mkdir(parents=True, mode=0o700)
    journal = dict(version=1, phase='PREPARED', base=str(base), prepared=str(prepared),
                   published=[], service_before=controller.service_state(),
                   reviewed_binding=controller.recovery_binding(base, prepared, archive))
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


def recover_archive(archive, controller):
    """Recover an interrupted transaction without interpreting absence as success."""
    archive = Path(archive)
    journal = json.loads((archive / 'journal.json').read_text())
    if (journal.get('version') != 1 or journal.get('phase') not in
            ('PREPARED', 'BACKED_UP', 'PUBLISHING', 'ROLLING_BACK', 'ROLLBACK_FAILED')
            or journal.get('published') not in ([], ['tools'], ['tools', 'jetson'])
            or type(journal.get('backup_ready', False)) is not bool
            or not isinstance(journal.get('base'), str) or not isinstance(journal.get('prepared'), str)
            or not isinstance(journal.get('service_before'), dict)):
        raise ValueError('Invalid or completed publication journal')
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
    raise SystemExit('Deployment disabled until independent staged QA and reviewed rollout controller are ready.')
