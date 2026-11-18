"""Explicit, reviewed paused rollout. This module never enables scheduling."""
import argparse
import fcntl
import json
import re
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

from release_bundle import (digest, metadata, tree, source_manifest, prerequisite_manifest,
                            build_release, verify_release, expected_release)
from deploy_campaign_update import backup_database, save_json, rollout, recover_archive, deployment_owner

SERVICE = 'wrapper-development-host.service'
INPUTS = ('reviewed-hold-ids.json', 'expected-legacy-cohort.json',
          'reviewed-acceptance-baseline.json', 'reviewed-assignment-baseline.json')
CAMPAIGN = 'integration-backlog-20261118'


def logical_database(path):
    """Stable logical evidence, independent of WAL/checkpoint page layout."""
    with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Database integrity failed')
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {name: sorted([list(row) for row in db.execute('SELECT * FROM "' + name.replace('"', '""') + '"')], key=lambda row: json.dumps(row, sort_keys=True)) for name in names}


def paused_database(path):
    data = logical_database(path)
    controls = {k: json.loads(v) for k, v in data.get('settings', [])}
    if (any(controls.get(k) is not False for k in ('queue_enabled', 'autopilot_enabled'))
            or controls.get('campaign_enabled', False) is not False or controls.get('pilot_task') is not None):
        raise ValueError('Scheduling controls must explicitly be OFF and pilot empty')
    states = [json.loads(row[1]) for row in data['tasks']]
    if any(s.get('status') in ('RUNNING', 'QUEUED', 'PAUSING') for s in states):
        raise ValueError('Active task prevents rollout')
    # Receipts schema is stable across the legacy and new release.
    with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as db:
        if db.execute('SELECT 1 FROM receipts WHERE result IS NULL LIMIT 1').fetchone():
            raise ValueError('Unfinished tool prevents rollout')
        if 'inference_receipts' in data and db.execute("SELECT 1 FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN') LIMIT 1").fetchone():
            raise ValueError('Unresolved inference prevents rollout')
    return {'digest': digest(data), 'controls': controls, 'task_count': len(states), 'integrity': 'ok'}


def validate_outputs(base, stage, qa, prepared=None, archive=None):
    base, stage, qa = map(lambda p: Path(p).resolve(), (base, stage, qa))
    protected = [stage, qa, *(base / name for name in ('tasks', 'tools', 'jetson', 'queue-base', 'repo'))]
    outputs = [Path(p).resolve() for p in (prepared, archive) if p is not None]
    for path in outputs:
        if path == base or path in base.parents:
            raise ValueError('Output overlaps production root')
        if any(path == root or path in root.parents or root in path.parents for root in protected):
            raise ValueError('Output overlaps protected input or production data')
        if base in path.parents and not (base / 'repairs') in path.parents:
            raise ValueError('Production-local disposable outputs must be beneath repairs')
    if len(outputs) == 2 and (outputs[0] == outputs[1] or outputs[0] in outputs[1].parents or outputs[1] in outputs[0].parents):
        raise ValueError('Prepared and archive paths overlap')


class Controller:
    def __init__(self, stage, qa, manifest, qa_report=None, *, run=subprocess.run, health=None):
        self.stage, self.qa = Path(stage).resolve(), Path(qa).resolve()
        self.manifest = json.loads(Path(manifest).read_text()) if not isinstance(manifest, dict) else manifest
        self.qa_report = json.loads(Path(qa_report).read_text()) if qa_report and not isinstance(qa_report, dict) else qa_report
        self.run, self.health_reader = run, health
        self.base = None
        self.prepared = self.archive = None

    def gate(self):
        gate = self.qa_report or {}
        if gate.get('result') != 'PASS' or gate.get('independent') is not True or gate.get('manifest_digest') != digest(self.manifest):
            raise ValueError('Independent staged PASS must bind this exact reviewed manifest')

    def inputs(self):
        if not isinstance(self.manifest.get('expected_database_digest'), str) or not re.fullmatch(r'[0-9a-f]{64}', self.manifest['expected_database_digest']):
            raise ValueError('Reviewed original database digest required')
        if self.manifest.get('version') != 1:
            raise ValueError('Unsupported reviewed manifest')
        if source_manifest(self.stage) != self.manifest['sources']:
            raise ValueError('Reviewed source changed')
        actual = {name: metadata(self.qa / name) for name in INPUTS}
        if actual != self.manifest['migration_inputs']:
            raise ValueError('Reviewed migration inputs changed')
        if digest(expected_release(self.manifest['sources'], self.manifest['prerequisites'])) != self.manifest['release_digest']:
            raise ValueError('Invalid release digest')

    def preflight(self, base, prepared):
        self.gate()
        self.inputs()
        validate_outputs(base, self.stage, self.qa, prepared, self.archive)
        self.base = Path(base).resolve()
        if prerequisite_manifest(self.base / 'tools') != self.manifest['prerequisites']:
            raise ValueError('Installed runtime prerequisites changed')
        verify_release(prepared, self.manifest['sources'], self.manifest['prerequisites'])
        return self.original_database(self.base / 'tasks/tasks.sqlite3')

    def original_database(self, path):
        evidence = paused_database(path)
        if evidence['digest'] != self.manifest['expected_database_digest']:
            raise ValueError('Original database changed since reviewed snapshot')
        return evidence

    def recovery_binding(self, base, prepared, archive):
        self.base, self.prepared, self.archive = map(lambda p: Path(p).resolve(), (base, prepared, archive))
        return {'manifest_digest': digest(self.manifest), 'base': str(self.base),
                'prepared': str(self.prepared), 'archive': str(self.archive)}

    def validate_recovery(self, journal, archive):
        self.gate()
        self.inputs()
        if self.base is None or self.prepared is None or self.archive is None:
            raise ValueError('Recovery requires explicit base, prepared, and archive paths')
        expected = {'manifest_digest': digest(self.manifest), 'base': str(self.base.resolve()),
                    'prepared': str(self.prepared.resolve()), 'archive': str(self.archive.resolve())}
        if (journal.get('reviewed_binding') != expected
                or Path(journal['base']).resolve() != self.base.resolve()
                or Path(journal['prepared']).resolve() != self.prepared.resolve()
                or Path(archive).resolve() != self.archive.resolve()):
            raise ValueError('Recovery journal review binding mismatch')
        evidence = Path(archive) / 'reviewed-binding.json'
        if evidence.exists() and json.loads(evidence.read_text()) != expected:
            raise ValueError('Recovery archive review binding mismatch')

    def unit_metadata(self):
        result = self.systemctl('show', '--property=FragmentPath,DropInPaths')
        values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        paths = [values.get('FragmentPath', '')] + values.get('DropInPaths', '').split()
        if not paths[0]:
            raise ValueError('Service unit fragment unavailable')
        return {name: metadata(Path(name)) for name in paths if name}

    def jetson_hash(self):
        result = self.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', 'jetson',
                          'sha256sum /home/chris/AI/local-ai/wrapper_commands.py'],
                         capture_output=True, text=True, check=True, timeout=20)
        value = result.stdout.split()[0]
        if value != self.manifest['sources']['jetson/wrapper_commands.py']['sha256']:
            raise ValueError('Jetson forwarder differs from reviewed unchanged version')
        return value

    def systemctl(self, *args, check=True):
        return self.run(['systemctl', '--user', *args, SERVICE], check=check, capture_output=True, text=True, timeout=30)

    def service_state(self):
        result = self.systemctl('show', '--property=ActiveState,SubState,UnitFileState,MainPID')
        values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        if values.get('ActiveState') not in ('active', 'inactive'):
            raise ValueError('Service must be stably active or inactive')
        return values

    def stop(self):
        self.systemctl('stop')

    def assert_stopped(self):
        state = self.service_state()
        if state.get('ActiveState') != 'inactive' or state.get('MainPID') != '0':
            raise ValueError('Service is not fully stopped')

    def start(self):
        self.systemctl('start')

    def capture_before(self, base, archive):
        self.assert_stopped()
        save_json(archive / 'reviewed-binding.json', {'manifest_digest': digest(self.manifest),
                  'base': str(base.resolve()), 'prepared': str(self.prepared.resolve()),
                  'archive': str(archive.resolve())})
        data = {'database': paused_database(base / 'tasks/tasks.sqlite3'),
                'tools': tree(base / 'tools'), 'jetson': tree(base / 'jetson'),
                'service': self.service_state(), 'live_units': self.unit_metadata(),
                'jetson_forwarder_sha256': self.jetson_hash(),
                'config_metadata': {name: metadata(base / name) for name in ('client-config.json', 'bridge-token')}}
        # Store hashes only; bridge credentials and task contents are never exported.
        save_json(archive / 'before-evidence.json', data)

    def migration(self, database, baseline):
        self.inputs()
        sys.path.insert(0, str(self.stage / 'host'))
        from coordinator_store import Store
        from migrate_campaign_membership import migrate_campaign_membership
        from backfill_campaign_metadata import backfill_campaign_identity
        ids = json.loads((self.qa / INPUTS[0]).read_text())
        if len(ids) != 102 or len(set(ids)) != 102:
            raise ValueError('Exactly 102 reviewed legacy tasks required')
        items = [item for path in sorted((self.stage / 'backlog').glob('batch-*.json')) for item in json.loads(path.read_text())]
        self.original_database(database)
        before = logical_database(database)
        store = Store(database.parent)
        kw = dict(reviewed_hold_ids=ids, expected_cohort=json.loads((self.qa / INPUTS[1]).read_text()))
        binding = dict(baseline_root=baseline,
                       expected_baseline_manifest=json.loads((self.qa / INPUTS[2]).read_text()),
                       expected_assignment_manifest=json.loads((self.qa / INPUTS[3]).read_text()))
        initialized = logical_database(database)
        dry = migrate_campaign_membership(store, CAMPAIGN, items, **kw)
        if logical_database(database) != initialized or not dry['clean'] or set(dry['held']) != set(ids):
            raise ValueError('Membership dry run failed')
        first_membership = migrate_campaign_membership(store, CAMPAIGN, items, apply=True, **kw)
        if set(first_membership['changed']) != set(ids) or first_membership['changed'] != dry['changed']:
            raise ValueError('One-time rollout requires all 102 original membership changes')
        midpoint = logical_database(database)
        dry_identity = backfill_campaign_identity(store, items, **binding)
        if logical_database(database) != midpoint or set(dry_identity['matched']) != set(ids):
            raise ValueError('Identity dry run failed')
        first_identity = backfill_campaign_identity(store, items, apply=True, **binding)
        if (set(first_identity['changed']) != set(ids) or set(first_identity['registered']) != set(ids)
                or first_identity != dry_identity):
            raise ValueError('One-time rollout requires all 102 original identity changes')
        first = logical_database(database)
        repeat_membership = migrate_campaign_membership(store, CAMPAIGN, items, apply=True, **kw)
        repeat_identity = backfill_campaign_identity(store, items, apply=True, **binding)
        if logical_database(database) != first or repeat_membership['changed'] or repeat_identity['changed'] or repeat_identity['registered']:
            raise ValueError('Migration second apply was not a no-op')
        old_tasks, new_tasks = dict(before['tasks']), dict(first['tasks'])
        if set(old_tasks) != set(new_tasks) or any(new_tasks[k] != v for k, v in old_tasks.items() if k not in ids):
            raise ValueError('Migration changed nonmember tasks')
        for name in ('receipts', 'inference_receipts', 'batches'):
            if before.get(name, []) != first.get(name, []):
                raise ValueError('Migration changed historical records')
        state = paused_database(database)
        return {'result': 'PASS', 'reviewed_count': 102, 'before_digest': digest(before),
                'after_digest': digest(first), 'second_apply_noop': True,
                'nonmembers_preserved': True, 'membership_changed': len(first_membership['changed']),
                'identity_changed': len(first_identity['changed']),
                'registry_created': len(first_identity['registered']), 'paused': state}

    def rehearse(self, backup, archive):
        self.assert_stopped()
        folder = archive / 'rehearsal'
        folder.mkdir(mode=0o700)
        target = folder / 'tasks.sqlite3'
        backup_database(backup, target)
        result = self.migration(target, self.base / 'queue-base')
        save_json(archive / 'rehearsal.json', result)
        return result

    def migrate(self, base, archive, fault):
        self.assert_stopped()
        result = self.migration(base / 'tasks/tasks.sqlite3', base / 'queue-base')
        expected = json.loads((archive / 'rehearsal.json').read_text())
        if result != expected:
            raise ValueError('Production migration differs from rehearsed backup')
        save_json(archive / 'migration.json', result)
        fault('migration_verified')

    def parity(self, base):
        wanted = expected_release(self.manifest['sources'], self.manifest['prerequisites'])
        for directory in ('tools', 'jetson'):
            expected = {k[len(directory)+1:]: v for k, v in wanted.items() if k.startswith(directory + '/')}
            if tree(base / directory) != expected:
                raise ValueError('Installed release byte parity failed: ' + directory)

    def tokenizer_smoke(self, base):
        python = base.parents[1] / '.venv/bin/python'
        code = "from coordinator_budget import estimate_context; e=estimate_context([{'role':'user','content':'Rollout tokenizer check.'}],10000); assert 0 < e.prompt_tokens < 10000; print('TOKENIZER_OK')"
        result = self.run([str(python), '-B', '-c', code], cwd=base / 'tools', capture_output=True, text=True, check=True, timeout=30)
        if result.stdout.strip() != 'TOKENIZER_OK':
            raise ValueError('Tokenizer smoke failed')

    def verify_stopped(self, base, archive):
        self.assert_stopped()
        self.parity(base)
        self.tokenizer_smoke(base)
        save_json(archive / 'stopped-verification.json', paused_database(base / 'tasks/tasks.sqlite3'))

    def health(self, base):
        if self.health_reader:
            return self.health_reader(base)
        token = (base / 'bridge-token').read_text().strip()
        request = urllib.request.Request('http://127.0.0.1:18789/coordinator',
            data=b'{"action":"health"}', headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)
        except Exception:
            raise ValueError('Authenticated local health request failed') from None

    def verify_running(self, base, archive):
        state = self.service_state()
        if state.get('ActiveState') != 'active' or int(state.get('MainPID', '0')) <= 0:
            raise ValueError('Installed host service is not active')
        health = {}
        for attempt in range(10):
            try:
                health = self.health(base)
            except ValueError:
                health = {}
            if health.get('ok') is True and health.get('worker_alive') is True and health.get('status') == 'healthy':
                break
            time.sleep(0.5)
        if health.get('ok') is not True or health.get('worker_alive') is not True or health.get('status') != 'healthy':
            raise ValueError('Installed scheduler health failed')
        # A second owner must be excluded even with scheduling disabled.
        with (base / 'tasks/scheduler.lock').open('r+') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)
                raise ValueError('Scheduler process ownership lock is not held')
        self.parity(base)
        before = json.loads((archive / 'before-evidence.json').read_text())
        if self.unit_metadata() != before['live_units'] or self.jetson_hash() != before['jetson_forwarder_sha256']:
            raise ValueError('Service unit or Jetson forwarder changed')
        paused = paused_database(base / 'tasks/tasks.sqlite3')
        stopped = json.loads((archive / 'stopped-verification.json').read_text())
        if paused != stopped:
            raise ValueError('Database changed during paused service startup')
        save_json(archive / 'running-verification.json', {'result': 'PASS', 'service': state,
                  'paused': paused, 'single_owner': True,
                  'healthy': True, 'live_inference_performed': False})

    def verify_restored(self, base, archive):
        self.assert_stopped()
        before = json.loads((archive / 'before-evidence.json').read_text())
        if tree(base / 'tools') != before['tools'] or tree(base / 'jetson') != before['jetson']:
            raise ValueError('Rollback source parity failed')
        if self.unit_metadata() != before['live_units']:
            raise ValueError('Rollback service unit changed')
        if {name: metadata(base / name) for name in before['config_metadata']} != before['config_metadata']:
            raise ValueError('Rollback configuration metadata changed')
        if paused_database(base / 'tasks/tasks.sqlite3') != before['database']:
            raise ValueError('Rollback database parity failed')

    def restore_service(self, previous):
        if previous['ActiveState'] == 'active':
            self.start()
        else:
            self.stop()
        actual = self.service_state()
        if any(actual.get(key) != previous.get(key) for key in ('ActiveState', 'UnitFileState')):
            raise ValueError('Original service state not restored')
        paused_database(self.base / 'tasks/tasks.sqlite3')
        if previous['ActiveState'] == 'active':
            for attempt in range(10):
                try:
                    health = self.health(self.base)
                    if health.get('ok') is True and health.get('worker_alive') is True and health.get('status') == 'healthy':
                        return
                except ValueError:
                    pass
                time.sleep(0.5)
            raise ValueError('Restored service failed health readiness')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'rehearse', 'apply', 'recover'))
    parser.add_argument('--stage', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--qa', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--qa-report', type=Path)
    parser.add_argument('--base', type=Path, default=Path('/home/chris/job-search-helper_old/dev/wrapper-coder'))
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args(argv)
    controller = Controller(args.stage, args.qa, args.manifest, args.qa_report)
    controller.base = args.base.resolve()
    controller.prepared = args.prepared.resolve() if args.prepared else None
    controller.archive = args.archive.resolve() if args.archive else None
    controller.inputs()
    validate_outputs(args.base, args.stage, args.qa, args.prepared, args.archive)
    if args.action in ('prepare', 'rehearse'):
        with deployment_owner(args.base):
            return execute_action(args, controller, parser)
    return execute_action(args, controller, parser)


def execute_action(args, controller, parser):
    if args.action == 'prepare':
        if not args.prepared:
            parser.error('--prepared is required')
        value = build_release(args.stage, args.base / 'tools', args.prepared,
                              controller.manifest['sources'], controller.manifest['prerequisites'])
        print(json.dumps({'result': 'PREPARED', 'release_digest': value}))
    elif args.action == 'rehearse':
        # Online SQLite backup only; this command does not stop the service.
        if not args.archive or args.archive.exists():
            parser.error('--archive must be a new directory')
        controller.original_database(args.base / 'tasks/tasks.sqlite3')
        args.archive.mkdir(mode=0o700)
        backup_database(args.base / 'tasks/tasks.sqlite3', args.archive / 'tasks.sqlite3')
        result = controller.migration(args.archive / 'tasks.sqlite3', args.base / 'queue-base')
        save_json(args.archive / 'rehearsal.json', result)
        print(json.dumps(result))
    elif args.action == 'apply':
        if not args.prepared or not args.archive:
            parser.error('--prepared and --archive are required')
        print(json.dumps(rollout(args.base, args.prepared, args.archive, controller)))
    else:
        if not args.archive or not args.prepared:
            parser.error('--archive and --prepared are required for recovery')
        controller.gate()
        print(json.dumps(recover_archive(args.archive, controller)))


if __name__ == '__main__':
    main()
