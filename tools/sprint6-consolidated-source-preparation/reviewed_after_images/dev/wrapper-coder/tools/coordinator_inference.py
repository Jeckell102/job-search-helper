"""Durable, non-replayable model reservations; no provider idempotency assumed."""
import hashlib
import json
import re
import time
import uuid

INFERENCE_REQUEST_ID = re.compile(r'[0-9a-f]{32}')
_DIGEST = re.compile(r'[0-9a-f]{64}')
_DONE_REASONS = {'stop', 'length', 'tool_calls', 'cancelled', 'error'}
_USAGE_FIELDS = {'prompt_eval_count', 'eval_count', 'done_reason'}
PENDING_INFERENCE = {'DISPATCHING', 'UNCERTAIN'}
TERMINAL_INFERENCE = {'COMPLETED', 'FAILED', 'CANCELLED'}
_OWNED_RECEIPT_FIELDS = {'request_id', 'status', 'created', 'updated',
                         'response_digest', 'usage', 'cancel_requested'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def valid_inference_binding(value, request_id):
    return (isinstance(value, dict)
            and set(value) == {'request_id', 'request_fingerprint', 'owner_generation'}
            and isinstance(request_id, str) and INFERENCE_REQUEST_ID.fullmatch(request_id)
            and value['request_id'] == request_id
            and all(isinstance(value[key], str) and _DIGEST.fullmatch(value[key])
                    for key in ('request_fingerprint', 'owner_generation')))


def valid_inference_usage(value):
    return (isinstance(value, dict) and set(value) == _USAGE_FIELDS
            and all(type(value[key]) is int and 0 <= value[key] <= 10000000
                    for key in ('prompt_eval_count', 'eval_count'))
            and isinstance(value['done_reason'], str) and value['done_reason'] in _DONE_REASONS)


def valid_owned_inference_receipt(value, request_id):
    if (not isinstance(value, dict) or set(value) != _OWNED_RECEIPT_FIELDS
            or value['request_id'] != request_id or not isinstance(value['status'], str)
            or value['status'] not in TERMINAL_INFERENCE | {'RUNNING', 'UNCERTAIN'}
            or type(value['cancel_requested']) is not bool
            or any(type(value[key]) not in (int, float) or not 0 <= value[key] <= 2**53
                   for key in ('created', 'updated'))):
        return False
    response_digest, usage = value['response_digest'], value['usage']
    if response_digest is None and usage is None:
        return True
    return (value['status'] in {'COMPLETED', 'CANCELLED'}
            and isinstance(response_digest, str) and _DIGEST.fullmatch(response_digest)
            and valid_inference_usage(usage))


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

    def _hold_inference_controls(self, db):
        for key, value in (('queue_enabled', False), ('campaign_enabled', False),
                           ('autopilot_enabled', False), ('pilot_task', None)):
            db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (key, json.dumps(value)))
        self._bump_control_generation(db)

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
            if (session_id and state.get('inference_session_id') == session_id
                    and state.get('inference_session_open') is True
                    and not self._inference_pending(db, task_id)):
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
                           status='DISPATCHING', observed_usage=None, response_digest=None, terminal_reason=None,
                           control_binding=None)
            db.execute('INSERT INTO inference_receipts VALUES (?,?,?,?)',
                       (receipt['request_id'], task_id, receipt['status'], json.dumps(receipt)))
            state.update(calls=state['calls'] + 1, tokens=state['tokens'] + receipt['reserved_tokens'])
            self._inference_save(db, state)
            return receipt

    def bind_inference_control(self, request_id, control):
        """Persist the exact remote ownership proof before sending it.

        A restart can then query only the matching Jetson receipt; it never
        reconstructs or guesses credentials from mutable task state.
        """
        if not valid_inference_binding(control, request_id):
            raise ValueError('Invalid inference control binding.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM inference_receipts WHERE request_id=?', (request_id,)).fetchone()
            if not row:
                raise ValueError('Unknown inference request.')
            receipt = json.loads(row[0])
            if receipt['status'] != 'DISPATCHING':
                return receipt
            if receipt.get('control_binding') not in (None, control):
                raise ValueError('Inference control binding conflicts with durable receipt.')
            state = self._inference_state(db, receipt['task'])
            if (not self._inference_allowed(db, state, receipt['max_seconds'])
                    or self._control_generation(db) != receipt['control_generation']
                    or state.get('inference_session_id') != receipt['session_id']
                    or not state.get('inference_session_open')
                    or state.get('identity_binding_digest') != receipt['identity_digest']
                    or state.get('campaign_run_id') != receipt['campaign_run_id']
                    or state['phase'] != receipt['phase']):
                return None
            receipt['control_binding'] = dict(control)
            db.execute('UPDATE inference_receipts SET data=? WHERE request_id=?', (json.dumps(receipt), request_id))
            return receipt

    def reconcile_remote_inference(self, request_id, remote):
        """Settle a retained remote terminal state without replaying inference."""
        if (not valid_owned_inference_receipt(remote, request_id)
                or remote['status'] not in TERMINAL_INFERENCE):
            return None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM inference_receipts WHERE request_id=?', (request_id,)).fetchone()
            if not row:
                raise ValueError('Unknown inference request.')
            receipt = json.loads(row[0])
            state = self._inference_state(db, receipt['task'])
            if receipt['status'] not in PENDING_INFERENCE:
                return dict(receipt=receipt, state=state, settled=False)
            if not valid_inference_binding(receipt.get('control_binding'), request_id):
                return dict(receipt=receipt, state=state, settled=False)
            usage = remote['usage']
            if usage is not None:
                receipt['observed_usage'] = dict(usage)
                consumed = usage['prompt_eval_count'] + usage['eval_count']
                if consumed:
                    state['tokens'] += consumed - receipt['reserved_tokens']
            remote_status = remote['status']
            receipt.update(
                status='RESPONSE_DROPPED' if remote_status == 'COMPLETED' else remote_status,
                terminal_reason=('Jetson retained terminal inference state without a result or usage.'
                                 if usage is None else 'Jetson retained inference evidence for an undelivered response.'),
                response_digest=remote['response_digest'], finished=time.time())
            state['inference_session_open'] = False
            if state['status'] not in ('AWAITING_LIVE_VALIDATION','REVIEW_COMPLETE_LIVE_NOT_VALIDATED','LIVE_VALIDATED'):
                state.update(status='PAUSED_RECOVERY', reason=receipt['terminal_reason'])
            self._hold_inference_controls(db)
            db.execute('UPDATE inference_receipts SET status=?,data=? WHERE request_id=?',
                       (receipt['status'], json.dumps(receipt), request_id))
            self._inference_save(db, state)
            return dict(receipt=receipt, state=state, settled=True)

    def finalize_inference(self, request_id, response=None, *, terminal_error=None, record_owned_recipe_choice=False):
        """Settle a delivered response and optionally seal its one reviewed choice."""
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
                self._hold_inference_controls(db)
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
                if (record_owned_recipe_choice is True and tools_allowed
                        and state['mode'] == 'review' and state['phase'] == 'inspect'
                        and valid_inference_binding(receipt.get('control_binding'), request_id)
                        and valid_inference_usage(usage) and usage['done_reason'] in {'stop', 'tool_calls'}
                        and len(calls) == 1 and calls[0].get('type', 'function') == 'function'):
                    choice = {'summary': 'W1', 'next_action': 'listing_membership_change', 'outcome': 'phase_done'}
                    function = calls[0]['function']
                    if function['name'] == 'worker_checkpoint' and function.get('arguments') == choice:
                        receipt['accepted_recipe_choice'] = choice
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

    def inference_receipt(self, request_id):
        with self.connect() as db:
            row = db.execute('SELECT data FROM inference_receipts WHERE request_id=?', (request_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def unresolved_inferences(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN') ORDER BY rowid")]
