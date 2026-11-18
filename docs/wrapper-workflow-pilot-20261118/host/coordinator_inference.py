"""Durable, non-replayable model reservations; no provider idempotency assumed."""
import hashlib
import json
import time
import uuid


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class InferenceStore:
    def _inference_allowed(self, db, state, max_seconds=3600):
        self._require_current_identity(db, state)
        controls = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM settings')}
        campaign = (controls.get('campaign_enabled', False)
                    and state.get('campaign_id') == controls.get('active_campaign_id')
                    and state.get('campaign_disposition') == 'SELECTED')
        pilot = controls.get('pilot_task') == state['id']
        generic = (controls.get('queue_enabled', True) and not controls.get('campaign_enabled', False)
                   and not state.get('campaign_id') and not state.get('campaign_disposition'))
        start = state.get('activated_at') if state.get('workflow_version') == 2 else state['created']
        return (state['status'] == 'RUNNING' and not state.get('stop_requested')
                and (campaign or pilot or generic)
                and (start is None or time.time() < start + max_seconds))

    @staticmethod
    def _inference_state(db, task_id):
        row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise ValueError('Task not found.')
        return json.loads(row[0])

    @staticmethod
    def _inference_save(db, state):
        db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), state['id']))

    @staticmethod
    def _inference_pending(db, task_id=None):
        if task_id is None:
            return db.execute("SELECT 1 FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN') LIMIT 1").fetchone()
        return db.execute("SELECT 1 FROM inference_receipts WHERE task=? AND status IN ('DISPATCHING','UNCERTAIN')", (task_id,)).fetchone()

    def start_inference_session(self, task_id, *, max_calls=48, max_tokens=120000, max_seconds=3600):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._inference_state(db, task_id)
            if (not self._inference_allowed(db, state, max_seconds)
                    or self._inference_pending(db) or state.get('inference_session_open')
                    or state['sessions'] >= state['max_sessions']
                    or state['calls'] >= max_calls or state['tokens'] >= max_tokens):
                return None
            state.update(sessions=state['sessions'] + 1, inference_session_id=uuid.uuid4().hex, inference_session_open=True)
            self._inference_save(db, state)
            return state

    def end_inference_session(self, task_id, session_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._inference_state(db, task_id)
            if state.get('inference_session_id') == session_id and not self._inference_pending(db, task_id):
                state['inference_session_open'] = False
                self._inference_save(db, state)

    def reserve_inference(self, task_id, *, phase, prompt_digest, tools_digest,
                          prompt_tokens, output_tokens, expected_control_generation, session_id,
                          max_calls=48, max_tokens=120000, max_seconds=3600, min_output_tokens=256):
        if type(prompt_tokens) is not int or prompt_tokens < 0 or type(output_tokens) is not int or output_tokens <= 0:
            raise ValueError('Invalid model reservation estimate.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._inference_state(db, task_id)
            if (not self._inference_allowed(db, state, max_seconds)
                    or self._control_generation(db) != expected_control_generation
                    or state.get('inference_session_id') != session_id or not session_id
                    or not state.get('inference_session_open')
                    or state['phase'] != phase or self._inference_pending(db)
                    or not 0 < state['sessions'] <= state['max_sessions']
                    or state['calls'] >= max_calls):
                return None
            output_tokens = min(output_tokens, max_tokens - state['tokens'] - prompt_tokens)
            if output_tokens < min_output_tokens:
                state.update(status='PAUSED_BUDGET', reason='Remaining cumulative token allowance cannot fit inference.')
                self._inference_save(db, state)
                return None
            receipt = dict(request_id=uuid.uuid4().hex, task=task_id, phase=phase,
                           campaign_id=state.get('campaign_id'), campaign_run_id=state.get('campaign_run_id'),
                           company_id=state.get('campaign_company_id'),
                           session_id=session_id, identity_digest=state.get('identity_binding_digest'),
                           integration_identity_digest=state.get('integration_identity_digest'),
                           prompt_digest=prompt_digest, tools_digest=tools_digest,
                           reserved_prompt_tokens=prompt_tokens, reserved_output_tokens=output_tokens,
                           reserved_tokens=prompt_tokens + output_tokens,
                           pre_counters={k: state[k] for k in ('sessions', 'calls', 'tokens')},
                           control_generation=expected_control_generation, max_seconds=max_seconds,
                           created=time.time(), finished=None, provider_request_id=None,
                           status='DISPATCHING', observed_usage=None, response_digest=None, terminal_reason=None)
            db.execute('INSERT INTO inference_receipts VALUES (?,?,?,?)',
                       (receipt['request_id'], task_id, receipt['status'], json.dumps(receipt)))
            state.update(calls=state['calls'] + 1, tokens=state['tokens'] + receipt['reserved_tokens'])
            self._inference_save(db, state)
            return receipt

    def finalize_inference(self, request_id, response=None, *, terminal_error=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM inference_receipts WHERE request_id=?', (request_id,)).fetchone()
            if not row:
                raise ValueError('Unknown inference request.')
            receipt = json.loads(row[0])
            state = self._inference_state(db, receipt['task'])
            if receipt['status'] != 'DISPATCHING':
                return dict(receipt=receipt, state=state, tools_allowed=False)
            malformed = not isinstance(response, dict) or not isinstance(response.get('message'), dict)
            if not malformed:
                calls = response['message'].get('tool_calls', [])
                malformed = (not isinstance(calls, list) or any(
                    not isinstance(call, dict) or not isinstance(call.get('function'), dict)
                    or not isinstance(call['function'].get('name'), str)
                    for call in calls))
            tools_allowed = False
            if terminal_error is not None or malformed:
                receipt.update(status='UNCERTAIN', terminal_reason=terminal_error or 'Malformed model response.')
                for key, value in (('queue_enabled', False), ('campaign_enabled', False), ('autopilot_enabled', False), ('pilot_task', None)):
                    db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value)))
                self._bump_control_generation(db)
                if state['status'] not in ('AWAITING_LIVE_VALIDATION','REVIEW_COMPLETE_LIVE_NOT_VALIDATED','LIVE_VALIDATED'):
                    state.update(status='PAUSED_RECOVERY', reason='Uncertain inference requires inspection; automatic replay is blocked.')
            else:
                receipt['response_digest'] = digest(response)
                receipt['provider_request_id'] = response.get('id')
                usage = response.get('usage')
                counters = [usage.get(k) for k in ('prompt_eval_count','eval_count')] if isinstance(usage, dict) else []
                valid = len(counters) == 2 and all(type(n) is int and n >= 0 for n in counters) and sum(counters) > 0
                consumed = sum(counters) if valid else receipt['reserved_tokens']
                receipt['observed_usage'] = ({key: usage.get(key) for key in ('prompt_eval_count', 'eval_count', 'done_reason')} if isinstance(usage, dict) else None)
                state['tokens'] += consumed - receipt['reserved_tokens']
                try:
                    owned = (self._inference_allowed(db, state, receipt['max_seconds'])
                             and self._control_generation(db) == receipt['control_generation']
                             and state.get('inference_session_id') == receipt['session_id']
                             and state.get('identity_binding_digest') == receipt['identity_digest']
                             and state.get('campaign_run_id') == receipt['campaign_run_id']
                             and state['phase'] == receipt['phase'])
                except ValueError:
                    owned = False
                tools_allowed = owned and valid and consumed <= receipt['reserved_tokens']
                receipt.update(status='COMPLETED' if tools_allowed else 'RESPONSE_DROPPED',
                               terminal_reason=None if tools_allowed else 'Control loss or invalid/over-reservation usage.')
                if not valid or consumed > receipt['reserved_tokens']:
                    if state['status'] == 'RUNNING':
                        state.update(status='PAUSED_USAGE_ERROR', reason='Invalid or over-reservation inference usage; inspect model receipt.')
                elif not owned and state['status'] == 'RUNNING':
                    start = state.get('activated_at') if state.get('workflow_version') == 2 else state['created']
                    expired = start is not None and time.time() >= start + receipt['max_seconds']
                    state.update(status='PAUSED_BUDGET' if expired else 'PAUSED', reason='Inference response dropped after control, identity, or deadline change.')
            receipt['finished'] = time.time()
            db.execute('UPDATE inference_receipts SET status=?,data=? WHERE request_id=?',
                       (receipt['status'], json.dumps(receipt), request_id))
            self._inference_save(db, state)
            return dict(receipt=receipt, state=state, tools_allowed=tools_allowed)

    def inference_receipts(self, task_id):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT data FROM inference_receipts WHERE task=? ORDER BY rowid', (task_id,))]

    def unresolved_inferences(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN') ORDER BY rowid")]
