"""Durable MuleLab task state and write-ahead tool receipts."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
import threading


DEFAULT_CAMPAIGN_ID = 'integration-backlog-20261118'
HELD_FOR_CAMPAIGN = 'HELD_FOR_CAMPAIGN'
SELECTED = 'SELECTED'
USER_PAUSED = 'USER_PAUSED'
EXCLUDED = 'EXCLUDED'
# Group 6 will replace this coarse terminal bucket with reconciled outcomes.
# It is needed now so a completed selection cannot coexist with the next one.
CAMPAIGN_FINISHED = 'CAMPAIGN_FINISHED'
CAMPAIGN_DISPOSITIONS = frozenset({
    HELD_FOR_CAMPAIGN, SELECTED, USER_PAUSED, EXCLUDED, CAMPAIGN_FINISHED,
})


def campaign_manifest_digest(state):
    """Stable digest for the reviewed assignment entry, not runtime state."""
    entry = {key: state.get(key) for key in ('objective', 'tests', 'integration')}
    encoded = json.dumps(entry, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


class Store:
    def __init__(self, base):
        self.base = Path(base)
        self.base.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.base / 'tasks.sqlite3'
        self.export_lock = threading.Lock()
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts(
                    id INTEGER PRIMARY KEY, task TEXT NOT NULL, phase TEXT NOT NULL,
                    name TEXT NOT NULL, arguments TEXT NOT NULL, result TEXT,
                    signature TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS batches(digest TEXT PRIMARY KEY, task_ids TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, objective, tests, mode, max_sessions=10, *, authorization_version=0,
               evidence_requirements=None, workflow_version=1, integration=None):
        state = self.new_state(objective, tests, mode, max_sessions, authorization_version,
                               evidence_requirements, workflow_version, integration)
        with self.connect() as db:
            db.execute('INSERT INTO tasks VALUES (?,?)', (state['id'], json.dumps(state)))
        return state

    def new_state(self, objective, tests, mode, max_sessions, authorization_version,
                  evidence_requirements, workflow_version, integration=None):
        task_id = 'WRAP-' + uuid.uuid4().hex[:10]
        state = dict(id=task_id, objective=objective, tests=tests, mode=mode,
                     status='QUEUED', phase='baseline', created=time.time(),
                     time_budget_policy='wall_time_from_creation_including_queue_and_pause',
                     sessions=0, calls=0, tokens=0, max_sessions=max_sessions,
                     checkpoint={}, manifest={}, stop_requested=False, reason='',
                     no_progress=0, errors=0, phase_start=0,
                     authorization_version=authorization_version, evidence_requirements=evidence_requirements or {},
                     workflow_version=workflow_version, workflow={}, integration=integration or {},
                     campaign_id=None, campaign_company_id=None,
                     campaign_disposition=None, campaign_selected_at=None,
                     campaign_run_id=None, campaign_manifest_digest=None)
        if workflow_version == 2:
            state.update(activated_at=None, time_budget_policy='one_hour_from_first_assignment_including_pauses')
        return state

    def enqueue_batch(self, digest, specs, held=False, campaign_id=DEFAULT_CAMPAIGN_ID):
        """Atomic and idempotent: a retried submission never duplicates work."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT task_ids FROM batches WHERE digest=?', (digest,)).fetchone()
            if existing:
                return json.loads(existing[0]), True
            states = [self.new_state(**spec) for spec in specs]
            for state in states:
                state['isolated_workspace'] = True
                if held:
                    company_id = state.get('integration', {}).get('company_id')
                    if not isinstance(campaign_id, str) or not campaign_id.strip():
                        raise ValueError('Held campaign imports require a stable campaign ID.')
                    if not isinstance(company_id, str) or not company_id:
                        raise ValueError('Held campaign imports require structured company identity.')
                    state.update(status='PAUSED', stop_requested=False,
                                 reason='Held for one-company campaign selection.',
                                 campaign_id=campaign_id,
                                 campaign_company_id=company_id,
                                 campaign_disposition=HELD_FOR_CAMPAIGN,
                                 campaign_manifest_digest=campaign_manifest_digest(state))
                db.execute('INSERT INTO tasks VALUES (?,?)', (state['id'], json.dumps(state)))
            ids = [s['id'] for s in states]
            db.execute('INSERT INTO batches VALUES (?,?)', (digest, json.dumps(ids)))
            return ids, False

    def queue_enabled(self):
        with self.connect() as db:
            value = db.execute("SELECT value FROM settings WHERE key='queue_enabled'").fetchone()
        return value is None or value[0] == 'true'

    def set_queue_enabled(self, enabled):
        with self.connect() as db:
            db.execute("INSERT INTO settings VALUES ('queue_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(enabled),))

    def autopilot_enabled(self):
        return self.campaign_enabled()

    def set_autopilot_enabled(self, enabled):
        self.configure_campaign(enabled)

    def campaign_control(self):
        with self.connect() as db:
            values = dict(db.execute(
                "SELECT key,value FROM settings WHERE key IN ('campaign_enabled','active_campaign_id','autopilot_enabled')"
            ).fetchall())
        # Read the legacy flag only for staged database compatibility. New writes
        # always persist both explicit campaign settings.
        enabled = json.loads(values.get('campaign_enabled', values.get('autopilot_enabled', 'false')))
        campaign_id = json.loads(values['active_campaign_id']) if 'active_campaign_id' in values else None
        return {'enabled': bool(enabled), 'campaign_id': campaign_id}

    def campaign_enabled(self):
        return self.campaign_control()['enabled']

    def active_campaign_id(self):
        return self.campaign_control()['campaign_id']

    def configure_campaign(self, enabled, campaign_id=DEFAULT_CAMPAIGN_ID):
        """Persist campaign identity and enabled state in one transaction.

        Queue state is kept for command compatibility, but campaign scheduling
        has its own selector and claim path and never falls through to it.
        """
        if not isinstance(campaign_id, str) or not campaign_id.strip():
            raise ValueError('Campaign ID must be a nonempty string.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            pilot = db.execute("SELECT value FROM settings WHERE key='pilot_task'").fetchone()
            if enabled and pilot and json.loads(pilot[0]) is not None:
                raise ValueError('Stop the single-company pilot before starting the backlog campaign.')
            current = db.execute("SELECT value FROM settings WHERE key='active_campaign_id'").fetchone()
            current_id = json.loads(current[0]) if current else None
            if enabled and current_id not in (None, campaign_id):
                raise ValueError('Stop the active campaign before selecting another campaign.')
            for key, value in (('campaign_enabled', bool(enabled)),
                               ('active_campaign_id', campaign_id),
                               ('autopilot_enabled', bool(enabled)),
                               ('queue_enabled', bool(enabled))):
                db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           (key, json.dumps(value)))

    def configure_autopilot(self, enabled):
        self.configure_campaign(enabled)

    def configure_queue(self, enabled):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            pilot = db.execute("SELECT value FROM settings WHERE key='pilot_task'").fetchone()
            if enabled and pilot and json.loads(pilot[0]) is not None:
                raise ValueError('Stop the single-company pilot before resuming the global queue.')
            db.execute("INSERT INTO settings VALUES ('queue_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (json.dumps(bool(enabled)),))
            if not enabled:
                # The global pause is a stop control for every scheduler mode.
                # Retain active_campaign_id and SELECTED membership so an
                # explicit campaign restart resumes the same company.
                for key in ('campaign_enabled', 'autopilot_enabled'):
                    db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                               (key, json.dumps(False)))

    def activate_next_campaign(self, campaign_id=None, *, require_enabled=True):
        """Select exactly one held member of the active campaign."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            controls = dict(db.execute(
                "SELECT key,value FROM settings WHERE key IN ('campaign_enabled','active_campaign_id','pilot_task')"
            ).fetchall())
            enabled = json.loads(controls.get('campaign_enabled', 'false'))
            active_campaign = json.loads(controls['active_campaign_id']) if 'active_campaign_id' in controls else None
            pilot = json.loads(controls['pilot_task']) if 'pilot_task' in controls else None
            selected_campaign = campaign_id or active_campaign or DEFAULT_CAMPAIGN_ID
            if require_enabled and (not enabled or active_campaign != selected_campaign):
                return None
            if pilot is not None:
                return None
            rows = db.execute('SELECT id,state FROM tasks ORDER BY rowid').fetchall()
            active = []
            candidate = None
            selected = None
            for task_id, raw in rows:
                state = json.loads(raw)
                if state['status'] in ('RUNNING', 'PAUSING'):
                    active.append(task_id)
                if (state.get('campaign_id') == selected_campaign
                        and state.get('campaign_disposition') == SELECTED):
                    if state['status'] not in ('QUEUED', 'RUNNING', 'PAUSING', 'PAUSED'):
                        state['campaign_disposition'] = CAMPAIGN_FINISHED
                        db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
                    else:
                        selected = state
                if (candidate is None and state.get('campaign_id') == selected_campaign
                        and state.get('campaign_disposition') == HELD_FOR_CAMPAIGN
                        and not state.get('stop_requested')
                        and state['status'] == 'PAUSED' and state['phase'] == 'baseline'
                        and state.get('activated_at') is None
                        and state.get('campaign_selected_at') is None
                        and state.get('selected_at') is None
                        and state.get('calls', 0) == 0 and state.get('sessions', 0) == 0
                        and state.get('tokens', 0) == 0
                        and state.get('authorization_version') == 1
                        and state.get('mode') == 'develop'
                        and state.get('integration')
                        and not db.execute('SELECT 1 FROM receipts WHERE task=? LIMIT 1',
                                           (task_id,)).fetchone()):
                    candidate = state
            if active:
                return None
            if selected is not None:
                if selected['status'] == 'PAUSED' and not selected.get('stop_requested'):
                    selected.update(status='QUEUED', reason='Campaign restarted; retained selected company.')
                    db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(selected), selected['id']))
                    return selected
                return None
            if candidate is None:
                return None
            candidate.update(status='QUEUED', stop_requested=False, errors=0,
                             campaign_disposition=SELECTED,
                             campaign_selected_at=time.time(),
                             campaign_run_id=uuid.uuid4().hex,
                             selected_at=time.time(), integration_run_id=uuid.uuid4().hex,
                             worker_context_policy='fresh_context_for_each_call_and_company',
                             reason='Selected by one-company campaign with a fresh integration worker.')
            db.execute('UPDATE tasks SET state=? WHERE id=?',
                       (json.dumps(candidate), candidate['id']))
            return candidate

    def activate_next_untouched(self):
        """Compatibility name for tests and saved callers; campaign-scoped."""
        return self.activate_next_campaign(DEFAULT_CAMPAIGN_ID)

    def claim_queued(self, task_id=None):
        """Atomically lease one queued task to a scheduler process.

        The status transition is the cross-process mutex.  A second service
        instance cannot observe the same task as QUEUED after this commit.
        Existing write-ahead receipt recovery remains the crash boundary.
        """
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT id,state FROM tasks ORDER BY rowid').fetchall()
            decoded = [(current_id, json.loads(raw)) for current_id, raw in rows]
            if any(state['status'] in ('RUNNING', 'PAUSING') for _, state in decoded):
                return None
            for current_id, state in decoded:
                if state['status'] != 'QUEUED' or task_id is not None and current_id != task_id:
                    continue
                if state.get('campaign_id') or state.get('campaign_disposition'):
                    continue
                state.update(status='RUNNING', scheduler_claimed_at=time.time())
                db.execute('UPDATE tasks SET state=? WHERE id=?',
                           (json.dumps(state), current_id))
                return state
        return None

    def claim_campaign(self, campaign_id=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            controls = dict(db.execute(
                "SELECT key,value FROM settings WHERE key IN ('campaign_enabled','active_campaign_id')"
            ).fetchall())
            enabled = json.loads(controls.get('campaign_enabled', 'false'))
            active_campaign = json.loads(controls['active_campaign_id']) if 'active_campaign_id' in controls else None
            selected_campaign = campaign_id or active_campaign
            if not enabled or not selected_campaign or active_campaign != selected_campaign:
                return None
            rows = db.execute('SELECT id,state FROM tasks ORDER BY rowid').fetchall()
            decoded = [(task_id, json.loads(raw)) for task_id, raw in rows]
            if any(state['status'] in ('RUNNING', 'PAUSING') for _, state in decoded):
                return None
            matches = [(task_id, state) for task_id, state in decoded
                       if state.get('campaign_id') == selected_campaign
                       and state.get('campaign_disposition') == SELECTED
                       and state['status'] == 'QUEUED' and not state.get('stop_requested')]
            if len(matches) != 1:
                return None
            task_id, state = matches[0]
            state.update(status='RUNNING', scheduler_claimed_at=time.time())
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
            return state

    def claim_pilot(self, task_id):
        """Targeted compatibility path; it never discovers another task."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            pilot = db.execute("SELECT value FROM settings WHERE key='pilot_task'").fetchone()
            if not pilot or json.loads(pilot[0]) != task_id:
                return None
            rows = db.execute('SELECT id,state FROM tasks ORDER BY rowid').fetchall()
            decoded = [(current_id, json.loads(raw)) for current_id, raw in rows]
            if any(state['status'] in ('RUNNING', 'PAUSING') for _, state in decoded):
                return None
            for current_id, state in decoded:
                if current_id == task_id and state['status'] == 'QUEUED' and not state.get('stop_requested'):
                    state.update(status='RUNNING', scheduler_claimed_at=time.time())
                    db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), current_id))
                    return state
            return None

    def set_campaign_disposition(self, task_id, disposition):
        if disposition not in CAMPAIGN_DISPOSITIONS:
            raise ValueError('Invalid campaign disposition.')
        state = self.get(task_id)
        if not state.get('campaign_id'):
            raise ValueError('Task is not a campaign member.')
        return self.update(task_id, campaign_disposition=disposition)

    def pause_task(self, task_id, reason='Pause requested.'):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('Task not found.')
            state = json.loads(row[0])
            if state.get('campaign_id'):
                state['campaign_disposition'] = USER_PAUSED
            state.update(stop_requested=True,
                         status='PAUSING' if state['status'] == 'RUNNING' else 'PAUSED',
                         reason=reason)
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
            return state

    def exclude_campaign_task(self, task_id):
        state = self.get(task_id)
        if not state.get('campaign_id'):
            raise ValueError('Task is not a campaign member.')
        status = 'PAUSING' if state['status'] == 'RUNNING' else 'PAUSED'
        return self.update(task_id, campaign_disposition=EXCLUDED, stop_requested=True,
                           status=status, reason='Excluded from campaign by operator.')

    def include_campaign_task(self, task_id):
        state = self.get(task_id)
        if state.get('campaign_disposition') != EXCLUDED:
            raise ValueError('Only an excluded campaign task can be included.')
        untouched = (state['phase'] == 'baseline' and state.get('activated_at') is None
                     and state.get('campaign_selected_at') is None
                     and state.get('calls', 0) == 0 and state.get('sessions', 0) == 0
                     and state.get('tokens', 0) == 0 and not self.receipts(task_id))
        if untouched:
            return self.update(task_id, campaign_disposition=HELD_FOR_CAMPAIGN,
                               stop_requested=False, status='PAUSED',
                               reason='Included in campaign; held for selection.')
        return self.update(task_id, campaign_disposition=USER_PAUSED,
                           stop_requested=True, status='PAUSED',
                           reason='Included in campaign; explicit resume required for prior work.')

    def resume_campaign_task(self, task_id, **fields):
        """Explicitly reserve one user-paused member when the lane is free."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT id,state FROM tasks ORDER BY rowid').fetchall()
            decoded = [(current_id, json.loads(raw)) for current_id, raw in rows]
            target = next((state for current_id, state in decoded if current_id == task_id), None)
            if target is None:
                raise ValueError('Task not found.')
            if target.get('campaign_disposition') == EXCLUDED:
                raise ValueError('Include the excluded campaign task before resuming it.')
            if not target.get('campaign_id'):
                raise ValueError('Task is not a campaign member.')
            conflicts = [state['id'] for _, state in decoded if state['id'] != task_id and (
                state['status'] in ('RUNNING', 'PAUSING') or
                (state.get('campaign_disposition') == SELECTED
                 and state['status'] in ('QUEUED', 'PAUSED')))]
            if conflicts:
                raise ValueError('Another task owns the campaign lane.')
            target.update(fields)
            target.update(campaign_disposition=SELECTED, status='QUEUED',
                          stop_requested=False, campaign_selected_at=time.time(),
                          campaign_run_id=uuid.uuid4().hex)
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(target), task_id))
            return target

    def pilot_task(self):
        with self.connect() as db:
            value = db.execute("SELECT value FROM settings WHERE key='pilot_task'").fetchone()
        return json.loads(value[0]) if value else None

    def set_pilot_task(self, task_id):
        if task_id is not None:
            self.get(task_id)
        with self.connect() as db:
            db.execute("INSERT INTO settings VALUES ('pilot_task',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (json.dumps(task_id),))

    def get(self, task_id):
        if not isinstance(task_id, str) or not re.fullmatch(r'WRAP-[a-f0-9]{10}', task_id):
            raise ValueError('Use a task ID from /wrapper list.')
        with self.connect() as db:
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise ValueError('Task not found.')
        return json.loads(row[0])

    def update(self, task_id, **fields):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('Task not found.')
            state = json.loads(row[0])
            state.update(fields)
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
        return state

    def all(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT state FROM tasks ORDER BY rowid')]

    def intent(self, task_id, phase, name, args):
        encoded = json.dumps(args, sort_keys=True)
        signature = hashlib.sha256((name + encoded).encode()).hexdigest()
        with self.connect() as db:
            cursor = db.execute('INSERT INTO receipts(task,phase,name,arguments,signature,created) VALUES (?,?,?,?,?,?)',
                                (task_id, phase, name, encoded, signature, time.time()))
            return cursor.lastrowid

    def active_intent(self, task_id, phase, name, args):
        """Write the intent only while this task still owns the action lane."""
        encoded = json.dumps(args, sort_keys=True)
        signature = hashlib.sha256((name + encoded).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('Task not found.')
            state = json.loads(row[0])
            queue = db.execute("SELECT value FROM settings WHERE key='queue_enabled'").fetchone()
            pilot = db.execute("SELECT value FROM settings WHERE key='pilot_task'").fetchone()
            campaign = db.execute("SELECT value FROM settings WHERE key='campaign_enabled'").fetchone()
            active_campaign = db.execute("SELECT value FROM settings WHERE key='active_campaign_id'").fetchone()
            queue_enabled = queue is None or json.loads(queue[0])
            pilot_task = json.loads(pilot[0]) if pilot else None
            campaign_enabled = bool(campaign and json.loads(campaign[0]))
            active_campaign_id = json.loads(active_campaign[0]) if active_campaign else None
            campaign_owner = (campaign_enabled
                              and state.get('campaign_id') == active_campaign_id
                              and state.get('campaign_disposition') == SELECTED)
            pilot_owner = pilot_task == task_id
            generic_owner = (queue_enabled and not campaign_enabled
                             and not state.get('campaign_id')
                             and not state.get('campaign_disposition'))
            if (state['status'] != 'RUNNING' or state.get('stop_requested')
                    or not (campaign_owner or pilot_owner or generic_owner)):
                return None
            cursor = db.execute('INSERT INTO receipts(task,phase,name,arguments,signature,created) VALUES (?,?,?,?,?,?)',
                                (task_id, phase, name, encoded, signature, time.time()))
            return cursor.lastrowid

    def finish(self, receipt_id, result):
        with self.connect() as db:
            db.execute('UPDATE receipts SET result=? WHERE id=?', (json.dumps(result), receipt_id))

    def receipts(self, task_id):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('SELECT * FROM receipts WHERE task=? ORDER BY id', (task_id,)).fetchall()
        return [{**dict(row), 'arguments': json.loads(row['arguments']),
                 'result': json.loads(row['result']) if row['result'] else None} for row in rows]

    def recover(self):
        for state in self.all():
            uncertain = (state['status'] in ('RUNNING', 'PAUSING', 'QUEUED') and
                         any(r['result'] is None for r in self.receipts(state['id'])))
            if uncertain:
                self.update(state['id'], status='PAUSED_RECOVERY',
                            reason='Interrupted action needs inspection before resume; no action was replayed.')
            elif state['status'] == 'PAUSING':
                self.update(state['id'], status='PAUSED', reason='Pause preserved across service restart.')
            elif state['status'] == 'RUNNING':
                self.update(state['id'], status='QUEUED', reason='Recovered checkpoint.')

    def export(self, task_id):
        with self.export_lock:
            return self._export(task_id)

    def _export(self, task_id):
        state = self.get(task_id)
        folder = self.base / task_id
        folder.mkdir(exist_ok=True, mode=0o700)
        checkpoint = state['checkpoint']
        text = (f"# {task_id}\n\nStatus: {state['status']}\nPhase: {state['phase']}\n\n"
                f"Objective: {state['objective']}\n\nReason: {state['reason']}\n\n" +
                ('Budgets: One hour from first assignment, including pauses; initial queue wait is excluded. ' if state.get('workflow_version') == 2 else 'Budgets: One-hour lifetime from creation, including queued and paused time. ') +
                'Resume does not reset time, calls, sessions or tokens. Already-started actions may finish; the next action is checked before dispatch.\n\n' +
                f"Worker summary (model-authored, verify against receipts):\n{checkpoint.get('summary', '')}\n\n"
                f"Next action: {checkpoint.get('next_action', 'Continue the next incomplete phase.')}\n\n"
                f"Python work plan: {json.dumps(state.get('workflow', {}).get('plan', {}))}\n\n"
                f"Resume in Wrapper Coder:\n\n`/wrapper resume {task_id}`\n\n"
                f"Inspect progress:\n\n`/wrapper status {task_id}`\n\n"
                "Live scraper validation, installation and GitHub delivery of generated wrappers require operator review.\n")
        for name, payload in [('checkpoint.json', json.dumps(state, indent=2)),
                              ('receipts.json', json.dumps(self.receipts(task_id), indent=2)),
                              ('HANDOFF.md', text)]:
            temporary = folder / (name + '.new')
            temporary.write_text(payload)
            temporary.replace(folder / name)
        return text
