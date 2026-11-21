"""Read-only Sprint 4 maintenance witness. No application imports or command line."""
from contextlib import ExitStack, closing, contextmanager
from hashlib import sha256
import ast
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

CYCLE = 'CYC-B639C6D864EC'
SARONIC = 'COMP-0054'
SAMTEC = 'COMP-0739'
DISPATCH = 'company-intake-dispatch.sqlite3'
HEX = re.compile('[0-9a-f]{64}')
DATABASES = {
    'state': '.state/state.db',
    'jobs': '.state/jobs.sqlite3',
    'inbox': '.state/inventories.sqlite3',
    'sessions': '.state/retained-sessions.sqlite3',
    'coordinator': 'dev/wrapper-coder/tasks/tasks.sqlite3',
}
TABLES = {
    'state': 'cycles reviews',
    'jobs': ('manual_choices conflicts dirty delivery_attempts company_revisions company_event_outbox '
             'company_event_deliveries company_event_watermarks scrape_outcomes scrape_outcome_deliveries '
             'scrape_outcome_delivery_receipts scrape_outcome_delivery_attempts exact_local_applications '
             'exact_local_apply_chunks exact_local_acknowledgements retained_publications retained_intake_holds '
             'retained_dirty_chunks retained_dirty_cells'),
    'inbox': ('destination inventories sync_plans exact_sync_chunks exact_plan_local_state '
              'exact_remote_plans publication_receipts exact_legacy_plan_migrations '
              'exact_selected_legacy_recoveries exact_selected_legacy_recovery_archive '
              'exact_control_before_prefix_recoveries exact_legacy_plan_migration_archive '
              'exact_legacy_delivery_evidence exact_legacy_delivery_evidence_archive'),
    'sessions': 'retained_sessions retained_remote_chunks',
    'coordinator': ('tasks receipts inference_receipts scrape_outcome_intake scrape_outcome_delivery_receipts '
                    'repair_intake repair_intake_evidence repair_retry_lineage repair_retry_outcome_events '
                    'repair_retry_lifecycles'),
    'dispatch': 'settings dispatches request_ownership',
    'starts': 'retained_work_starts',
    'exceptions': 'retained_work_exceptions retained_work_admissions',
}
ARCHIVES = ('retained-operator-admission-archive', 'company-event-bridge/consumed-requests',
            'company-event-bridge/consumption-receipts', 'operator-company-requests/receipts')
RETAINED_FIRST_PASS = 'retained-first-pass'
FLAGS = ('autopilot_enabled', 'queue_enabled', 'campaign_enabled')
# Exact terminal Freeform outcome accepted by the current receipt-v1 consumer.
# Keep the historical legacy consumer rows unchanged.
FREEFORM_SETTLED = (
    'OUT-73328ca07b6f86f7d8fc8dfc', 'COMP-2522FE051E36', 'COMPLETE', 'save_without_repair',
    '8862a0fb60d4c9a5f85ce0554d5edb8e1171a3ad6e5c75f3075b34e50dba927f',
    '03f48256baa602753a20ff7d6f6648a33d9d99c4687147958fc790eeda3926b6',
)


class WitnessHold(RuntimeError):
    """Message is a fixed diagnostic and may be logged."""


def need(ok, message):
    if not ok:
        raise WitnessHold(message)


def physical(path):
    need(path.is_absolute() and path.resolve() == path, 'unsafe path')
    return path


def regular(path):
    info = physical(path).lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'unsafe file')
    return info


def version(path):
    st = regular(path)
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def file_digest(path):
    before = version(path)
    digest = sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(262144), b''):
            digest.update(block)
    need(version(path) == before, 'file changed during read')
    return digest.hexdigest()


def absent(path):
    # Only an actually missing path qualifies; a broken symlink is present.
    return not os.path.lexists(physical(path))


def sidecar(path):
    return None if absent(path) else version(path)


@contextmanager
def database(path):
    """Read checkpointed files without SQLite creating sidecars; read real WAL on a read-only mount."""
    before = version(path)
    wal, journal, shm = (Path(str(path) + suffix) for suffix in ('-wal', '-journal', '-shm'))
    wal_before, journal_before = sidecar(wal), sidecar(journal)
    need(journal_before is None or journal_before[2] == 0, 'rollback journal needs reconciliation')
    sidecar(shm)
    live_wal = wal_before is not None and wal_before[2] > 0
    if live_wal:
        need(not absent(shm) and all(os.statvfs(p).f_flag & os.ST_RDONLY
             or not os.access(p, os.W_OK, effective_ids=True) for p in (path.parent, path, wal, shm)),
             'nonempty WAL needs read-only view')
    options = '?mode=ro' if live_wal else '?mode=ro&immutable=1'
    with closing(sqlite3.connect(path.as_uri() + options, uri=True, timeout=1)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA temp_store=MEMORY')
        db.execute('BEGIN')
        yield db
    need((before, wal_before, journal_before) == (version(path), sidecar(wal), sidecar(journal)),
         'database changed during read')


def encoded(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode()


def fingerprint(rows, header=()):
    hashed = sha256(encoded(header) + b'\n')
    for row in rows:
        hashed.update(encoded(row) + b'\n')
    return hashed.hexdigest()


def table(db, name):
    ddl = db.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (name,)).fetchone()
    need(ddl and ddl[0].upper().startswith('CREATE TABLE'), 'required ordinary table unavailable')
    return ddl[0]


def table_digest(db, name):
    ddl = table(db, name)
    columns = db.execute(f'PRAGMA table_info("{name}")').fetchall()
    keys = [c[1] for c in sorted(columns, key=lambda c: c[5]) if c[5]]
    order = ','.join('"' + k.replace('"', '""') + '"' for k in keys) or 'rowid'
    return fingerprint(db.execute(f'SELECT * FROM "{name}" ORDER BY {order}'), ddl)


def no_rows(db, query, message, parameters=()):
    need(db.execute(query, parameters).fetchone() is None, message)


def historical(dbs):
    cycle = dbs['state'].execute('SELECT data FROM cycles WHERE id=?', (CYCLE,)).fetchone()
    value = json.loads(cycle[0]) if cycle else {}
    need(value.get('id') == CYCLE and SARONIC in value.get('companies', {})
         and value.get('status') not in (None, 'Complete', 'Complete with exceptions'), 'historical cycle unavailable')
    for name in ('inventories', 'sync_plans'):
        need(dbs['inbox'].execute(f'SELECT 1 FROM {name} WHERE cycle=? AND company=?',
                                  (CYCLE, SARONIC)).fetchall() == [(1,)], 'historical plan or inventory unavailable')
    sessions = dbs['sessions'].execute(
        'SELECT reservation_digest,receipt_id,intent_id,acknowledgement_id FROM retained_sessions '
        "WHERE company_id=? AND exception_cycle_id=? AND request_id=? AND state='SYNC_CONFIRMED'",
        (SAMTEC, CYCLE, 'operator-samtec-m1-20261119')).fetchall()
    need(len(sessions) == 1 and all(sessions[0]), 'retained receipt unavailable')
    reservation, receipt, intent, ack = sessions[0]
    matching = dbs['jobs'].execute(
        'SELECT p.local_apply_id FROM retained_publications p JOIN exact_local_acknowledgements a '
        'ON a.apply_id=p.local_apply_id AND a.receipt_id=p.receipt_id AND a.acknowledgement_id=p.acknowledgement_id '
        'WHERE p.reservation_digest=? AND p.receipt_id=? AND p.intent_id=? AND p.acknowledgement_id=? '
        "AND p.company=? AND p.exception_cycle=? AND p.state='FIRST_PASS_RELEASED'",
        (reservation, receipt, intent, ack, SAMTEC, CYCLE)).fetchall()
    need(len(matching) == 1, 'retained acknowledgement mismatch')
    no_rows(dbs['sessions'], "SELECT 1 FROM retained_sessions WHERE state IS NOT 'SYNC_CONFIRMED' LIMIT 1",
            'unsettled retained session')
    no_rows(dbs['jobs'], 'SELECT 1 FROM retained_intake_holds LIMIT 1', 'retained intake active')
    no_rows(dbs['jobs'], "SELECT 1 FROM retained_publications WHERE state IS NOT 'FIRST_PASS_RELEASED' LIMIT 1",
            'retained publication active')


def settled_deliveries(jobs, coordinator):
    # A receiver commit followed by sender death is unfinished transport even
    # when a local attempt row is lost. Stale suppression has no receiver.
    consumer = 'repair-coordinator'
    peer = {row[0]:row[1:] for row in coordinator.execute(
        'SELECT outcome_id,record_sha256,receipt,receipt_sha256 FROM scrape_outcome_delivery_receipts '
        'WHERE consumer=?', (consumer,))}
    senders = jobs.execute(
        'SELECT r.outcome_id,r.record_sha256,r.receipt,r.receipt_sha256,o.payload,d.acknowledged_at '
        'FROM scrape_outcome_delivery_receipts r LEFT JOIN scrape_outcomes o ON o.outcome_id=r.outcome_id '
        'LEFT JOIN scrape_outcome_deliveries d ON d.outcome_id=r.outcome_id AND d.consumer=r.consumer '
        'WHERE r.consumer=?', (consumer,))
    for key, record_hash, receipt, receipt_hash, payload, ack in senders:
        public = json.loads(receipt)
        need(ack and isinstance(payload, str) and sha256(payload.encode()).hexdigest() == record_hash
             and sha256(receipt.encode()).hexdigest() == receipt_hash and public.get('outcome_id') == key
             and public.get('consumer') == consumer and public.get('record_sha256') == record_hash,
             'sender receipt disagrees with acknowledgement')
        if public.get('disposition') == 'ACCEPTED':
            need(peer.pop(key, None) == (record_hash, receipt, receipt_hash), 'receiver receipt differs')
        else:
            need(public.get('disposition') == 'STALE_SUPPRESSED', 'unknown receipt disposition')
    need(not peer, 'receiver committed without sender acknowledgement')
    no_rows(jobs, 'SELECT 1 FROM scrape_outcome_deliveries d WHERE consumer=? AND NOT EXISTS '
            '(SELECT 1 FROM scrape_outcome_delivery_receipts r WHERE r.outcome_id=d.outcome_id '
            'AND r.consumer=d.consumer) LIMIT 1', 'sender acknowledgement lacks receipt', (consumer,))



def verify_legacy_restart_scope(jobs, coordinator):
    pending = jobs.execute(
        "SELECT o.outcome_id,o.company_id,o.outcome,o.action,o.payload,r.record_sha256,r.receipt_sha256 "
        "FROM scrape_outcomes o LEFT JOIN scrape_outcome_delivery_receipts r "
        "ON r.outcome_id=o.outcome_id AND r.consumer='repair-coordinator' "
        "WHERE NOT EXISTS (SELECT 1 FROM scrape_outcome_deliveries d "
        "WHERE d.outcome_id=o.outcome_id AND d.consumer='wrapper-coordinator')"
    ).fetchall()
    if pending:
        need(len(pending) == 1, 'legacy restart backlog')
        outcome, company, result, action, payload, record_sha, receipt_sha = pending[0]
        need((outcome, company, result, action, record_sha, receipt_sha) == FREEFORM_SETTLED
             and isinstance(payload, str) and sha256(payload.encode()).hexdigest() == record_sha,
             'legacy restart backlog')
    # The exact digest is not sufficient. Require the acknowledged sender and
    # matching receiver receipt, and retain all original delivery safeguards.
    settled_deliveries(jobs, coordinator)


def controls(dbs):
    db = dbs['coordinator']
    table(db, 'settings')
    flags = dict(db.execute("SELECT key,value FROM settings WHERE key IN "
                            "('queue_enabled','autopilot_enabled','campaign_enabled','pilot_task')"))
    need(all(flags.get(k) == 'false' for k in FLAGS) and flags.get('pilot_task', 'null') == 'null',
         'coordinator control enabled or missing')
    for (raw,) in db.execute('SELECT state FROM tasks'):
        task = json.loads(raw)
        need(isinstance(task.get('status'), str) and task['status'] not in ('QUEUED','RUNNING','PAUSING')
             and task.get('inference_session_open', False) is False, 'active task or inference owner')
    for status, raw in db.execute('SELECT status,data FROM inference_receipts'):
        need(status in ('COMPLETED','RESPONSE_DROPPED','FAILED','CANCELLED')
             and json.loads(raw).get('status') == status, 'unresolved inference receipt')
    jobs = dbs['jobs']
    verify_legacy_restart_scope(jobs, db)
    no_rows(jobs, "SELECT 1 FROM scrape_outcome_delivery_attempts WHERE consumer IN "
            "('wrapper-coordinator','repair-coordinator') LIMIT 1", 'pending outcome delivery')
    if 'dispatch' in dbs:
        dispatcher = dbs['dispatch']
        no_rows(dispatcher, "SELECT 1 FROM settings WHERE key IN "
                "('intake_enabled','retained_intake_enabled','temporary_retry_enabled') AND value IS NOT 'false'",
                'dispatcher enabled')
        no_rows(dispatcher, "SELECT 1 FROM request_ownership WHERE state NOT IN "
                "('RETAINED_CONSUMED','ORDINARY_SETTLED','NORMAL_WORKFLOW_COMPLETE') OR state IS NULL",
                'dispatcher ownership outstanding')
        no_rows(dispatcher, "SELECT 1 FROM dispatches WHERE state NOT IN ('WORKFLOW_COMPLETE','ORDINARY_SETTLED') "
                "OR state IS NULL", 'dispatcher pending')
    return fingerprint(sorted(flags.items()))


def protected_records(db):
    table(db, 'records')
    pieces = []
    for tab, field, key in [('Companies','Company ID',SARONIC), ('Scan Cycles','Cycle ID',CYCLE)]:
        rows = db.execute("SELECT row_id,data,policies FROM records WHERE tab=? AND json_extract(data,?)=?",
                          (tab, '$."' + field + '"', key)).fetchall()
        need(len(rows) == 1, 'protected Company or mirror missing')
        pieces.append(fingerprint(rows))
    fields = ('Job Key', 'Added to Opportunities?', 'Review Notes', 'Salary / Range', 'Review Status')
    expressions = ','.join('json_extract(data,?)' for _ in fields)
    pieces.append(fingerprint(db.execute("SELECT row_id,policies," + expressions +
        " FROM records WHERE tab='Job History' ORDER BY row_id", ['$."' + f + '"' for f in fields]), fields))
    pieces.append(fingerprint(db.execute("SELECT row_id,data,policies FROM records WHERE tab='Opportunities' ORDER BY row_id")))
    return fingerprint([pieces])


def retained_first_pass_digest(root):
    archive = root / RETAINED_FIRST_PASS
    if absent(archive):
        return None
    archive = physical(archive)
    rows = []
    for child in sorted(archive.iterdir()):
        need(physical(child).is_dir(), 'retained FIRST PASS bucket is not a directory')
        rows.append((child.name, None))
        rows.extend((member.relative_to(archive).as_posix(), file_digest(member))
                    for member in sorted(child.iterdir()))
    return fingerprint(rows)


def _measure(project, maintenance_id):
    project = physical(Path(project))
    root = physical(project / '.state')
    marker = root / 'integration-release-journal.json'
    if maintenance_id is None:
        need(absent(marker), 'unexpected release journal')
    else:
        regular(marker)
        need(json.loads(marker.read_bytes()) == {'schema':'integration-release-journal-v1',
             'state':'FOUNDATION_MAINTENANCE','maintenance_id':maintenance_id}, 'wrong release hold')
    for name in ('next-scan.json', 'retained-operator-admission.json'):
        need(absent(root / name), 'active request or operator journal')
    result = {RETAINED_FIRST_PASS: retained_first_pass_digest(root)}
    profile = project / 'dev/wrapper-coder/tools/coordinator_repair_profiles.py'
    result['repair_profile'] = file_digest(profile)  # Pin the independently reviewed empty-registry implementation.
    assignments = [n.value for n in ast.parse(profile.read_bytes()).body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'PROFILE_REGISTRY' for t in n.targets)]
    need(len(assignments) == 1 and isinstance(assignments[0], ast.Tuple) and not assignments[0].elts,
         'automatic repair registry is not empty')
    for name in ARCHIVES + ('repair-retry/intents','repair-retry/receipts'):
        folder = physical(root / name)
        if absent(folder):
            need(name not in ARCHIVES, 'protected archive missing')
            result[name] = None
            continue
        files = sorted(folder.iterdir())
        need(folder.is_dir() and (bool(files) or name not in ARCHIVES), 'protected archive empty')
        if name == 'repair-retry/intents':
            need(not files, 'repair retry intent requires disposition')
        result[name] = fingerprint((p.name, file_digest(p)) for p in files)
    with ExitStack() as stack:
        dbs = {k:stack.enter_context(database(project / v)) for k,v in DATABASES.items()}
        for role, filename in [('dispatch', DISPATCH), ('starts', 'retained-work-starts.sqlite3'),
                               ('exceptions', 'retained-work-exceptions.sqlite3')]:
            path = root / filename
            result[role + '_present'] = not absent(path)
            if result[role + '_present']:
                dbs[role] = stack.enter_context(database(path))
            else:
                need(all(absent(Path(str(path) + suffix)) for suffix in ('-wal','-shm','-journal')),
                     'orphaned lifecycle database sidecar')
        for role, db in dbs.items():
            for name in TABLES[role].split():
                result[role + '/' + name] = table_digest(db, name)
        historical(dbs)
        if 'starts' in dbs:
            no_rows(dbs['starts'], 'SELECT 1 FROM retained_work_starts LIMIT 1', 'retained start outstanding')
        result['controls'] = controls(dbs)
        result['protected_records'] = protected_records(dbs['jobs'])
    return result


def measure_for_private_review(project, *, maintenance_id=None):
    """Offline enrollment aid; caller supplies an externally frozen view. Returns fingerprints only."""
    try:
        return _measure(project, maintenance_id)
    except WitnessHold:
        raise
    except (OSError, ValueError, TypeError, AttributeError, RecursionError, sqlite3.Error):
        raise WitnessHold('protected evidence unavailable or malformed') from None


def verify_protected_state(project, pin_file, pin_sha256, *, verify_release_hold, maintenance_id=None):
    """Verify operator-pinned evidence under the site caller's continuous route closure."""
    try:
        path = Path(pin_file)
        st = regular(path)
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
            opened = os.fstat(stream.fileno())
            need(os.path.samestat(st, opened) and stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1
                 and opened.st_uid == os.geteuid() and stat.S_IMODE(opened.st_mode) == 0o600,
                 'unsafe private pins')
            data = stream.read(131073)
        need(len(data) <= 131072, 'private pin exceeds size limit')
        need(HEX.fullmatch(pin_sha256) and sha256(data).hexdigest() == pin_sha256, 'private pin seal mismatch')
        pin = json.loads(data)
        need(set(pin) == {'schema','project','witness'} and pin['schema'] == 'protected-site-witness-v1'
             and pin['project'] == str(physical(Path(project))), 'wrong private pin scope')
        try:
            release_closed = verify_release_hold() is True
        except Exception:
            release_closed = False
        need(release_closed, 'automatic release closure unverified')
        need(measure_for_private_review(project, maintenance_id=maintenance_id) == pin['witness'],
             'protected state differs from private pin')
        return True
    except WitnessHold:
        raise
    except Exception:
        raise WitnessHold('site witness verification failed') from None


def bind_host_witness(project, pin_file, pin_sha256, *, maintenance_id, verify_release_hold):
    """Adapt to host_checkpoint.attest's protected(stage,target) contract."""
    def protected(stage, target):
        need(target in ('INSTALLED', 'ROLLED_BACK') and stage in ('preflight', 'host-fenced', 'held',
             'pre-publish', 'published', 'admitted', 'before-host-reopen', 'restoring', 'restored'),
             'unknown host checkpoint')
        marker = Path(project) / '.state/integration-release-journal.json'
        outside = stage in ('preflight', 'restored') or stage == 'restoring' and not os.path.lexists(marker)
        return verify_protected_state(project, pin_file, pin_sha256,
            maintenance_id=None if outside else maintenance_id,
            verify_release_hold=lambda: verify_release_hold(stage, target))
    return protected


def verify_release_lease(project, controller_pid):
    """Check the real local release primitive's flock without opening/acquiring it.

    Caller authenticates controller_pid and its process start identity. This
    positive proves only exclusion of callers using this canonical SQLite lease.
    """
    need(type(controller_pid) is int and controller_pid > 0, 'release lock owner unavailable')
    path = physical(Path(project) / '.state/scraper.lock')
    before = regular(path)
    try:
        locks = Path('/proc/locks').read_text().splitlines()
        found = False
        for line in locks:
            fields = line.split()
            if (len(fields) != 8 or fields[1:5] != ['FLOCK','ADVISORY','WRITE',str(controller_pid)]
                    or fields[6:] != ['0','EOF']):
                continue
            major, minor, inode = fields[5].split(':')
            if (int(major,16), int(minor,16), int(inode)) == (
                    os.major(before.st_dev), os.minor(before.st_dev), before.st_ino):
                found = True
        need(found and os.path.samestat(before, regular(path)), 'release lease not owned by controller')
        return True
    except (OSError, ValueError):
        raise WitnessHold('release lock evidence unavailable') from None
