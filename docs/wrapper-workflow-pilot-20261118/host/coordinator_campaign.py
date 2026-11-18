"""Current-company campaign accounting and guarded host result publication."""
import hashlib
import json
import time

GATES = {'AWAITING_LIVE_VALIDATION': 'OFFLINE_READY_AWAITING_LIVE_VALIDATION',
         'REVIEW_COMPLETE_LIVE_NOT_VALIDATED': 'REVIEW_COMPLETE_AWAITING_LIVE_VALIDATION',
         'LIVE_VALIDATED': 'LIVE_VALIDATED_AWAITING_INSTALLATION'}
EXCEPTIONS = frozenset(('PAUSED_BUDGET', 'PAUSED_ERROR', 'PAUSED_BLOCKED',
    'PAUSED_TEST_FAILURE', 'PAUSED_FILES_CHANGED', 'PAUSED_RECOVERY',
    'PAUSED_AUTHORIZATION', 'PAUSED_NO_PROGRESS'))
TERMINAL = ('DRAINED', 'DRAINED_WITH_EXCEPTIONS')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def next_action(state):
    status, disposition = state['status'], state.get('campaign_disposition')
    if status == 'AWAITING_LIVE_VALIDATION':
        return 'Operator live validation required; installation is a separate gate.'
    if status == 'REVIEW_COMPLETE_LIVE_NOT_VALIDATED':
        return 'Operator review and live validation required; installation is a separate gate.'
    if status == 'LIVE_VALIDATED':
        return 'Inspect identity-bound operator live receipt; installation requires separate approval and receipt.'
    if disposition == 'EXCLUDED':
        return 'Explicitly include this company before any resume.'
    if disposition == 'HELD_FOR_CAMPAIGN':
        return 'Start the campaign to select this held company when the lane is free.'
    if status == 'PAUSED_RECOVERY':
        return 'Inspect and reconcile unfinished receipts before an explicit retry or resume.'
    started = state.get('activated_at') if state.get('workflow_version') == 2 else state.get('created')
    if (status in ('PAUSED_BUDGET', 'PAUSED_AUTHORIZATION') or state.get('sessions', 0) >= state.get('max_sessions', 10)
            or state.get('calls', 0) >= 48 or state.get('tokens', 0) >= 120000
            or started is not None and time.time() >= started + 3600):
        return 'Review evidence and explicitly create a new bounded retry; existing budgets cannot reset.'
    if disposition == 'USER_PAUSED' or status.startswith('PAUSED'):
        return 'Review the reason and receipts, then explicitly resume when the lane and budgets permit.'
    return 'Wait for the current action boundary; inspect saved receipts.'


def valid_live_evidence(state, receipts):
    """Version 1 is an explicit operator schema; unknown versions fail closed."""
    proof = state.get('live_validation')
    identity = state.get('integration_identity') or state.get('integration') or {}
    if not isinstance(proof, dict):
        return False
    # Explicit compatibility for the recorded unversioned host-validation schema.
    # Legacy noncampaign pilots retain their own receipt-bound identity.
    if 'schema_version' not in proof:
        if (proof.get('dispatch') != 'fetch_inventory' or not proof.get('operator')
                or proof.get('status') != 'complete' or not proof.get('company_id')
                or not proof.get('company') or not proof.get('configured_url')
                or not proof.get('source_url') or type(proof.get('job_count')) is not int
                or proof['job_count'] < 0):
            return False
        if identity and any(proof.get(k) != identity.get(k) for k in ('company_id','company','configured_url')):
            return False
        if state.get('campaign_id') and not identity:
            return False
        ids, lengths = proof.get('posting_ids'), proof.get('description_lengths')
        if (not isinstance(ids, list) or not isinstance(lengths, list)
                or len(ids) != proof['job_count'] or len(lengths) != proof['job_count']
                or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids)
                or any(type(n) is not int or n <= 0 for n in lengths)
                or any(proof.get(k) is not True for k in ('unique_ids','unique_urls','stable_reread'))):
            return False
        return any(r.get('name') == 'operator_live_validation'
                   and r.get('arguments') == {'company_id': proof['company_id'], 'dispatch': 'fetch_inventory'}
                   and r.get('result') == {'ok': True, 'result': proof} for r in receipts)
    if type(proof.get('schema_version')) is not int or proof.get('schema_version') != 1:
        return False
    required = {'company_id': identity.get('company_id'), 'configured_url': identity.get('configured_url'),
                'integration_identity_digest': state.get('integration_identity_digest')}
    if any(not value or proof.get(key) != value for key, value in required.items()):
        return False
    if (proof.get('status') != 'complete' or proof.get('dispatch') != 'normal'
            or type(proof.get('job_count')) is not int or proof['job_count'] < 0
            or proof.get('full_description_coverage') is not True or proof.get('stable_reread') is not True):
        return False
    postings = proof.get('postings')
    if not isinstance(postings, list) or len(postings) != proof['job_count']:
        return False
    if any(not isinstance(p, dict) or any(not isinstance(p.get(k), str) or not p[k] for k in ('id','url','description')) for p in postings):
        return False
    if len({p['id'] for p in postings}) != len(postings) or len({p['url'] for p in postings}) != len(postings):
        return False
    return any(r.get('id') == proof.get('receipt_id') and r.get('name') == 'operator_live_validation'
               and r.get('result', {}).get('ok') is True
               and r['result'].get('live_validation') == {k: v for k, v in proof.items() if k != 'receipt_id'}
               for r in receipts if isinstance(r.get('result'), dict))


def campaign_text(record):
    if not record:
        return 'No campaign selected.'
    text = (f"Campaign {record['campaign_id']}: {record['state']}; {record['total']} current companies; membership {'sealed' if record['membership_sealed'] else 'unsealed pending explicit campaign start'}.\n"
            'Python accounts for recorded work boundaries; this is not certification of live results, installation, or complete job downloads.\n'
            + json.dumps(record['counts'], sort_keys=True))
    if record.get('errors'):
        text += '\nReconciliation: ' + '; '.join(record['errors'][:10])
    for entry in record['exceptions'][:20]:
        text += f"\n{entry['company_id']} {entry['company']} ({entry['task_id']}): {entry['status']}/{entry['phase']}: {entry['reason'][:300]}. Next: {entry['next_action']}"
    if len(record['exceptions']) > 20:
        text += '\nFurther exceptions are in the complete campaign JSON report.'
    return text


class CampaignStore:
    def _reopen_campaign(self, db, campaign_id):
        if not campaign_id:
            return
        row = db.execute('SELECT data FROM campaigns WHERE campaign_id=?', (campaign_id,)).fetchone()
        if row:
            record = json.loads(row[0])
            if record['state'] in TERMINAL:
                record.update(revision=record['revision'] + 1, state='PAUSED', reconciliation_digest=None,
                              updated_at=time.time(), reopened_at=time.time())
                db.execute('UPDATE campaigns SET data=? WHERE campaign_id=?', (json.dumps(record), campaign_id))

    def campaign_history(self, campaign_id):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT data FROM campaign_snapshots WHERE campaign_id=? ORDER BY revision', (campaign_id,))]

    def _campaign_reconcile(self, db, campaign_id):
        controls = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM settings')}
        rows = db.execute('SELECT company_id,current_task_id,identity_digest FROM campaign_company_registry WHERE campaign_id=? ORDER BY company_id', (campaign_id,)).fetchall()
        oldrow = db.execute('SELECT data FROM campaigns WHERE campaign_id=?', (campaign_id,)).fetchone()
        old = json.loads(oldrow[0]) if oldrow else None
        errors, members, counts, retirements = [], [], {}, []
        membership = digest([(r[0], r[2]) for r in rows])
        seal = db.execute('SELECT membership_digest FROM campaign_seals WHERE campaign_id=?', (campaign_id,)).fetchone()
        if seal and seal[0] != membership:
            errors.append('Reviewed campaign membership changed; a new reviewed campaign is required.')
        pending = bool(self._inference_pending(db))
        if pending:
            for request, task, status, raw in db.execute("SELECT request_id,task,status,data FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN')"):
                proof = json.loads(raw)
                errors.append(f'Unresolved {status} inference {request} task {task} company {proof.get("company_id")} blocks global reconciliation.')
        unfinished = db.execute('SELECT id,task,name FROM receipts WHERE result IS NULL').fetchall()
        for receipt_id, task_id, name in unfinished:
            owner = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not owner or json.loads(owner[0]).get('status') not in ('RUNNING','PAUSING'):
                errors.append(f'Unfinished action receipt {receipt_id} task {task_id} tool {name} requires reconciliation.')
        pending = pending or bool(unfinished)
        seen = set()
        for company_id, task_id, identity_digest in rows:
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            try:
                if not row or task_id in seen:
                    raise ValueError('Missing or duplicate current registry owner.')
                seen.add(task_id)
                state = json.loads(row[0])
                self._require_current_identity(db, state)
                if state.get('campaign_id') != campaign_id or state.get('campaign_company_id') != company_id:
                    raise ValueError('Current registry ownership mismatch.')
                disposition, status = state.get('campaign_disposition'), state['status']
                receipt_rows = db.execute('SELECT id,name,arguments,result FROM receipts WHERE task=? ORDER BY id', (task_id,)).fetchall()
                receipts = [dict(id=r[0], name=r[1], arguments=json.loads(r[2]), result=json.loads(r[3]) if r[3] else None) for r in receipt_rows]
                if disposition not in ('HELD_FOR_CAMPAIGN','SELECTED','USER_PAUSED','EXCLUDED','CAMPAIGN_FINISHED'):
                    raise ValueError('Unknown campaign disposition.')
                if status == 'LIVE_VALIDATED' and not valid_live_evidence(state, receipts):
                    raise ValueError('LIVE_VALIDATED lacks matching identity-bound operator evidence.')
                if status not in GATES and status not in EXCEPTIONS and status not in ('QUEUED','RUNNING','PAUSING','PAUSED'):
                    raise ValueError('Unknown lifecycle status.')
                if disposition in ('USER_PAUSED', 'EXCLUDED'):
                    bucket, exception = disposition, True
                elif status in GATES or status in EXCEPTIONS:
                    bucket, exception = GATES.get(status, status), status in EXCEPTIONS
                    if disposition == 'SELECTED' and not pending:
                        if not state.get('campaign_run_id'):
                            raise ValueError('Selected company has no run ownership.')
                        state['campaign_disposition'] = 'CAMPAIGN_FINISHED'
                        state['campaign_outcome'] = bucket
                        state['campaign_retired_run_id'] = state['campaign_run_id']
                        retirements.append(state)
                elif disposition == 'HELD_FOR_CAMPAIGN':
                    if status != 'PAUSED' or state.get('stop_requested'):
                        raise ValueError('Held company has incompatible execution state.')
                    bucket, exception = disposition, False
                elif disposition == 'SELECTED':
                    bucket, exception = 'SELECTED', False
                else:
                    raise ValueError('Finished company has no recognized result.')
                evidence_receipt = (next((r['id'] for r in receipts if valid_live_evidence(state, [r])), None) if status == 'LIVE_VALIDATED' else (receipts[-1]['id'] if receipts else None))
                item = dict(company_id=company_id, company=(state.get('integration_identity') or {})['company'],
                            task_id=task_id, status=status, phase=state['phase'], disposition=state['campaign_disposition'],
                            bucket=bucket, exception=exception, reason=state.get('reason',''), next_action=next_action(state),
                            receipt_id=evidence_receipt, receipt_ids=[r['id'] for r in receipts])
                members.append(item)
                counts[bucket] = counts.get(bucket, 0) + 1
            except (ValueError, KeyError, TypeError) as exc:
                errors.append(f'{company_id}/{task_id}: {exc}')
        # Noncurrent predecessors are allowed only when a valid retry chain names them.
        for task_id, raw in db.execute('SELECT id,state FROM tasks'):
            state = json.loads(raw)
            if state.get('campaign_id') == campaign_id and task_id not in seen:
                descendants = [json.loads(r[0]) for r in db.execute('SELECT state FROM tasks')]
                if not any(s.get('retry_of') == task_id and s.get('campaign_id') == campaign_id for s in descendants):
                    errors.append(f'{task_id}: Campaign member is absent from current registry and retry lineage.')
        if len(members) != len(rows) or sum(counts.values()) != len(rows):
            errors.append('Campaign totals are not exhaustive.')
        if errors:
            for item in members:
                row = db.execute('SELECT state FROM tasks WHERE id=?', (item['task_id'],)).fetchone()
                item['disposition'] = json.loads(row[0]).get('campaign_disposition')
        if not errors:
            for state in retirements:
                db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), state['id']))
        active = any(json.loads(r[0]).get('status') in ('RUNNING', 'PAUSING') for r in db.execute('SELECT state FROM tasks'))
        exceptions = [m for m in members if m['exception']]
        if errors:
            result = 'PAUSED_RECONCILIATION'
        elif seal and not active and not counts.get('HELD_FOR_CAMPAIGN') and not counts.get('SELECTED'):
            result = 'DRAINED_WITH_EXCEPTIONS' if exceptions else 'DRAINED'
        else:
            result = 'RUNNING' if controls.get('campaign_enabled') and controls.get('active_campaign_id') == campaign_id else 'PAUSED'
        if errors or result in TERMINAL and (not old or old['state'] not in TERMINAL or controls.get('campaign_enabled')):
            changed = False
            for key in ('queue_enabled','campaign_enabled','autopilot_enabled'):
                if controls.get(key, key == 'queue_enabled'):
                    changed = True
                db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, 'false'))
            if errors and controls.get('pilot_task') is not None:
                db.execute("UPDATE settings SET value='null' WHERE key='pilot_task'")
                changed = True
            if changed:
                self._bump_control_generation(db)
        record = dict(campaign_id=campaign_id, membership_digest=seal[0] if seal else membership, membership_sealed=bool(seal), observed_membership_digest=membership, total=len(rows), counts=counts,
                      members=members, exceptions=exceptions, errors=errors, state=result)
        signature = digest(record)
        if old and old.get('reconciliation_digest') == signature:
            return old
        record.update(reconciliation_digest=signature, revision=old['revision'] if old else 1,
                      created_at=old['created_at'] if old else time.time(), updated_at=time.time(),
                      control_generation=self._control_generation(db))
        db.execute('INSERT INTO campaigns VALUES (?,?) ON CONFLICT(campaign_id) DO UPDATE SET data=excluded.data', (campaign_id, json.dumps(record)))
        if result in TERMINAL:
            db.execute('INSERT OR IGNORE INTO campaign_snapshots VALUES (?,?,?)', (campaign_id, record['revision'], json.dumps(record)))
        return record

    def reconcile_campaign(self, campaign_id=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if campaign_id is None:
                row = db.execute("SELECT value FROM settings WHERE key='active_campaign_id'").fetchone()
                campaign_id = json.loads(row[0]) if row else None
            if not campaign_id:
                return None
            result = self._campaign_reconcile(db, campaign_id)
        # Authoritative report remains in SQLite even if export fails.
        folder = self.base / 'campaign_reports'
        folder.mkdir(exist_ok=True)
        path = folder / (digest(campaign_id) + '.json')
        # Unique temporary filenames permit concurrent status readers.
        import uuid
        temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        temporary.write_text(json.dumps(result, indent=2))
        temporary.replace(path)
        return result

    campaign_status = reconcile_campaign

    def stop_at_boundary(self, task_id, reason, *, queued=False):
        """Acknowledge a stop without laundering a concurrently reached gate."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._inference_state(db, task_id)
            if state['status'] in GATES or state['status'] not in ('RUNNING','QUEUED','PAUSING'):
                return state
            state['status'] = 'QUEUED' if queued and not state.get('stop_requested') else 'PAUSED'
            if not state.get('stop_requested'):
                state['reason'] = reason
            self._inference_save(db, state)
            return state

    def result_snapshot(self, task_id):
        with self.connect() as db:
            db.execute('BEGIN')
            state = self._inference_state(db, task_id)
            return dict(state, result_control_generation=self._control_generation(db))

    def publish_result(self, task_id, expected_state, **fields):
        allowed = {'status','phase','reason','checkpoint','workflow','baseline_passed','no_progress','errors','manifest','activated_at'}
        if set(fields) - allowed:
            raise ValueError('Result publication cannot change identity, controls, ownership, or budgets.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._inference_state(db, task_id)
            self._require_current_identity(db, state)
            owns = all(state.get(k) == expected_state.get(k) for k in (
                'status','phase','inference_session_id','campaign_run_id','integration_identity_digest','scheduler_claimed_at'))
            same_owner = owns
            generation = expected_state.get('result_control_generation')
            owns = owns and generation is not None and generation == self._control_generation(db)
            owns = owns and state['status'] in ('RUNNING','QUEUED') and not state.get('stop_requested')
            controls = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM settings')}
            permitted = (controls.get('pilot_task') == task_id or
                controls.get('campaign_enabled') and controls.get('active_campaign_id') == state.get('campaign_id') and state.get('campaign_disposition') == 'SELECTED' or
                controls.get('queue_enabled', True) and not controls.get('campaign_enabled') and not state.get('campaign_id'))
            started = state.get('activated_at') if state.get('workflow_version') == 2 else state['created']
            expired = started is not None and time.time() >= started + 3600
            if owns and permitted and not self._inference_pending(db):
                if expired:
                    state.update(status='PAUSED_BUDGET', reason='Task deadline reached before result publication.')
                else:
                    state.update(fields)
            elif same_owner and state['status'] in ('RUNNING','QUEUED') and not state.get('stop_requested') and (not permitted or generation != self._control_generation(db)):
                state.update(status='PAUSED', reason='Scheduler controls changed before result publication; selection retained.')
            # A stale response may preserve bounded evidence, never overwrite a gate.
            elif 'checkpoint' in fields and state['status'] not in GATES:
                encoded = json.dumps(fields['checkpoint'])
                if len(encoded) <= 16000:
                    state['checkpoint'] = fields['checkpoint']
            self._inference_save(db, state)
            return state
