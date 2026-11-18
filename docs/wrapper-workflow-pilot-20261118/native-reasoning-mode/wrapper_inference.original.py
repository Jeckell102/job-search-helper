"""One authenticated inference turn; no task storage or tool execution on Jetson."""
import json
import time

from context_budget import estimate_context, require_output_room
from profile_policy import resolve_profile
from tool_runtime import native_turn

TOOL_NAMES = {'code_list', 'code_read', 'code_diff', 'code_edit', 'code_create',
              'code_test', 'web_read', 'web_search', 'rendered_web_read', 'worker_checkpoint'}


def infer(engine, data):
    if set(data) != {'messages', 'tools', 'max_tokens'}:
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
    message, done = native_turn(engine, data['messages'], schemas, profile, limit,
                               profile.temperature, False, lambda: False,
                               time.monotonic() + 270, foreground=False)
    # Private reasoning is neither needed by the host nor written to task records.
    return {'message': {k: message[k] for k in ('role', 'content', 'tool_calls')},
            'usage': {k: done.get(k) for k in ('done_reason', 'prompt_eval_count', 'eval_count')},
            'context_tokens': profile.context_tokens}
