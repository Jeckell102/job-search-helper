"""One authenticated inference turn; no task storage or tool execution on Jetson."""
import hashlib
import json
import time

from context_budget import estimate_context, require_output_room
from profile_policy import resolve_profile
from tool_runtime import native_turn

TOOL_NAMES = {'code_list', 'code_read', 'code_diff', 'code_edit', 'code_create',
              'code_test', 'web_read', 'web_search', 'rendered_web_read', 'worker_checkpoint'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def infer(engine, data, control_store=None):
    allowed = {'messages', 'tools', 'max_tokens'}
    controlled = allowed | {'request_id', 'request_fingerprint', 'owner_generation'}
    if set(data) not in (allowed, controlled):
        raise ValueError('Unexpected inference arguments.')
    schemas = data['tools']
    if not isinstance(schemas, list) or len(schemas) > len(TOOL_NAMES):
        raise ValueError('Invalid tool schemas.')
    for schema in schemas:
        if not isinstance(schema, dict) or schema.get('function', {}).get('name') not in TOOL_NAMES:
            raise ValueError('Unsupported tool schema.')
    limit = data['max_tokens']
    if type(limit) is not int or not 1 <= limit <= 3072:
        raise ValueError('Invalid inference limit.')
    profile = resolve_profile('qwen-wrapper:4b')
    estimate = estimate_context(data['messages'], profile.context_tokens,
                                thinking=False, tools=schemas, internal_tools=True)
    require_output_room(estimate, limit)
    control = None
    if set(data) == controlled:
        if control_store is None:
            raise ValueError('Inference control store is unavailable.')
        expected = _digest({'messages': data['messages'], 'tools': schemas, 'max_tokens': limit})
        if data['request_fingerprint'] != expected:
            raise ValueError('Inference request fingerprint does not match payload.')
        control = control_store.begin(data['request_id'], data['request_fingerprint'], data['owner_generation'])
        if not control['start']:
            return {'control': {key: value for key, value in control.items() if key != 'start'}}
    try:
        message, done = native_turn(engine, data['messages'], schemas, profile, limit,
                                   profile.temperature, False,
                                   (lambda: control_store.cancellation_requested(data['request_id'])) if control else (lambda: False),
                                   time.monotonic() + 270, foreground=False)
    except Exception:
        if control:
            control_store.fail(data['request_id'])
        raise
    # Private reasoning is neither needed by the host nor written to task records.
    result = {'message': {k: message[k] for k in ('role', 'content', 'tool_calls')},
              'usage': {k: done.get(k) for k in ('done_reason', 'prompt_eval_count', 'eval_count')},
              'context_tokens': profile.context_tokens}
    if control:
        terminal = control_store.finish(data['request_id'], response_digest=_digest(result), usage=result['usage'])
        result['control'] = {key: terminal[key] for key in ('request_id', 'status', 'response_digest', 'usage')}
        if terminal['status'] == 'CANCELLED':
            raise ValueError('inference_cancelled')
    return result
