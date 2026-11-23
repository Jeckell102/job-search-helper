"""Read the exact production ATS pilot. Never starts a task, scrape, or write."""

import json
from contextlib import closing, contextmanager
from hashlib import sha256
from pathlib import Path
import re
import sqlite3
import sys


PROJECT = Path('/home/chris/job-search-helper_old')
TOOLS = PROJECT / 'dev/wrapper-coder/tools'
TASK_ROOT = TOOLS.parent / 'tasks'
STATE = PROJECT / '.state'
ENROLLMENT = Path('/tmp/jsh-ats-native-package/activation/LIVE_ENROLLMENT.json')
ENROLLMENT_PIN = 'b1350fc595099d5d9c8a726c62a46969e2c2447f92787689a70a020c7b866c9d'
REQUEST_ID = 'operator-ats-20261122-01'
OUTCOME_ID = 'OUT-8b214610d53e23115e70da5f'
SETTLEMENT_PIN = '3875a0972c45432c187964832eb32e550333e93fe2d7eb7dd39097a922de422e'
DEVELOP_DEPLOYMENT = 'REL-aa0e7a762a8e741c03b99692'


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read_enrollment():
    from ats_operator_pilot import ATSOperatorEnrollment, ENV

    require(ENROLLMENT.resolve(strict=True) == ENROLLMENT, 'The enrollment path changed.')
    raw = ENROLLMENT.read_bytes()
    require(sha256(raw).hexdigest() == ENROLLMENT_PIN, 'The exact ATS enrollment bytes changed.')
    enrollment = ATSOperatorEnrollment.from_process_environment({ENV: raw.decode()})
    require(enrollment.request_id == REQUEST_ID, 'The enrollment names a different ATS request.')
    return enrollment


def readonly_store():
    from coordinator_store import Store

    class ReadOnlyStore(Store):
        # The normal constructor initializes schema and is inappropriate here.
        def __init__(self, base):
            self.base = base
            self.path = base / 'tasks.sqlite3'
            require(self.path.resolve(strict=True) == self.path and self.path.is_file(),
                    'The production task store path changed.')

        @contextmanager
        def connect(self):
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db:
                db.execute('BEGIN')
                yield db

    return ReadOnlyStore(TASK_ROOT)


def one_tool_receipt(receipts, phase, name):
    found = [r for r in receipts if (r['phase'], r['name']) == (phase, name)]
    require(len(found) == 1 and found[0]['result'] is not None,
            f'Expected one settled {name} receipt for {phase}.')
    return found[0]


def edit_proof(task, call, receipts, baseline, before, after):
    from ats_parser_assignment import MAX_TOKENS, TARGET
    from coordinator_inference import digest, valid_inference_binding, valid_inference_usage

    usage = call.get('observed_usage')
    response = call.get('response_digest')
    require(
        call['status'] == 'COMPLETED' and call['task'] == task['id'] and call['phase'] == 'implement'
        and call['identity_digest'] == task['identity_binding_digest']
        and call['integration_identity_digest'] == task['integration_identity_digest']
        and call['pre_counters'] == {'sessions': 1, 'calls': 0, 'tokens': 0}
        and valid_inference_binding(call.get('control_binding'), call['request_id'])
        and valid_inference_usage(usage) and usage['done_reason'] in ('stop', 'tool_calls')
        and isinstance(response, str) and re.fullmatch('[0-9a-f]{64}', response)
        and 0 < task['tokens'] == usage['prompt_eval_count'] + usage['eval_count'] <= call['reserved_tokens'] <= MAX_TOKENS,
        'The settled ATS inference receipt does not bind the single edit.',
    )
    edits = [r for r in receipts if r['name'] in ('code_edit', 'code_create')]
    require(len(edits) == 1, 'Expected exactly one model-authored action.')
    edit = one_tool_receipt(receipts, 'implement', 'code_edit')
    args = edit['arguments']
    require(
        set(args) == {'path', 'old', 'new', 'sha256'} and all(isinstance(value, str) for value in args.values())
        and args['path'] == TARGET and args['sha256'] == before[TARGET]
        and args['old'] and args['new'] and args['old'] != args['new']
        and call.get('accepted_ats_parser_edit')
        == {'path': TARGET, 'sha256': args['sha256'], 'arguments_sha256': digest(args)},
        'The parser edit arguments differ from the authorized model response.',
    )
    original = (baseline / TARGET).read_bytes()
    text = original.decode()
    require(sha256(original).hexdigest() == before[TARGET] and text.count(args['old']) == 1,
            'The exact original parser bytes do not admit this edit.')
    replayed_hash = sha256(text.replace(args['old'], args['new'], 1).encode()).hexdigest()
    require(
        replayed_hash == after[TARGET] and edit['result'].get('ok') is True
        and edit['result'].get('result') == {'path': TARGET, 'updated': True, 'sha256': replayed_hash},
        'The saved edit and exact final parser bytes do not match.',
    )
    return {'inference_request_id': call['request_id'], 'response_sha256': response,
            'arguments_sha256': digest(args), 'edit_receipt_id': edit['id'],
            'parser_sha256': replayed_hash}


def verification_proof(task, store, repo, receipts, final):
    from coordinator_acceptance import digest, files, validate_bundle, validate_scope
    from coordinator_evidence import manifest_digest

    scope = validate_scope(task)
    bundle = validate_bundle(store, task)
    editable = one_tool_receipt(receipts, 'verify', 'code_test')
    immutable = one_tool_receipt(receipts, 'verify', 'acceptance_test')
    diff = one_tool_receipt(receipts, 'verify', 'code_diff')
    normal_result, immutable_result, diff_result = (r['result'] for r in (editable, immutable, diff))
    accepted = immutable_result.get('result') or {}
    final_pin = manifest_digest(final)
    require(
        editable['arguments'] == {'paths': ' '.join(task['tests'])}
        and normal_result.get('ok') is True and normal_result['result']['exit_code'] == 0
        and not normal_result['result'].get('timed_out')
        and normal_result.get('source_unchanged_during_test') is True
        and normal_result.get('source_manifest_sha256') == final_pin,
        'Editable tests did not pass on the exact final source.',
    )
    require(
        immutable_result.get('ok') is True and accepted.get('exit_code') == 0
        and not accepted.get('timed_out') and accepted.get('independent_acceptance') is True
        and accepted.get('acceptance_bundle_digest') == bundle['digest']
        and accepted.get('edit_scope_digest') == scope['digest']
        and accepted.get('edit_scope_version') == scope['version']
        and accepted.get('source_manifest_digest') == digest(files(repo, ('src',), False)),
        'Immutable tests did not pass on the exact final source and acceptance bundle.',
    )
    require(
        diff_result.get('ok') is True and diff_result.get('source_unchanged_during_diff') is True
        and diff_result.get('source_manifest_sha256') == final_pin,
        'Final host diff receipt does not bind the verified workspace.',
    )
    return {'editable_test_receipt_id': editable['id'], 'immutable_test_receipt_id': immutable['id'],
            'diff_receipt_id': diff['id'], 'acceptance_bundle_sha256': bundle['digest']}


def read_terminal():
    from ats_parser_assignment import COMPANY_ID, TARGET, is_assignment
    from coordinator_baseline import binding, files
    from coordinator_evidence import manifest_digest
    from coordinator_store import task_state_digest
    from job_search_helper.inbox import InventoryInbox

    enrollment, store = read_enrollment(), readonly_store()
    jobs = STATE / 'jobs.sqlite3'
    inbox = STATE / 'inventories.sqlite3'
    for path in (jobs, inbox):
        require(path.resolve(strict=True) == path and path.is_file(), 'ATS application store path changed.')
    destination = InventoryInbox.destination_id(inbox)
    source = enrollment._source(jobs, destination)
    require(source and source['acknowledged'] and source['record']['outcome_id'] == OUTCOME_ID
            and source['proof']['settlement_sha256'] == SETTLEMENT_PIN
            and source['proof']['runtime']['release_id'] == DEVELOP_DEPLOYMENT
            and enrollment._sources_match(PROJECT),
            'Waiting for the exact acknowledged ATS source and settlement.')
    pair = enrollment.resolve_owned_pair(store, source)
    require(pair is not None and pair[1] is not None, 'Waiting for the ATS coordinator task.')
    held, task = pair
    require(
        re.fullmatch(r'WRAP-[0-9a-f]{10}', task['id']) and is_assignment(task)
        and enrollment._task_matches(held, task, enrollment._proposal(held, source['company'])),
        'The ATS task does not match the paired application outcome.',
    )
    current = {'company_id': COMPANY_ID, 'task_id': task['id'], 'failed_request_id': REQUEST_ID,
               'outcome_id': OUTCOME_ID, 'task_status': task['status'], 'phase': task['phase'],
               'task_state_sha256': task_state_digest(task), 'reason': task['reason']}
    if task['status'] in ('RUNNING', 'QUEUED', 'PAUSING') or store.unresolved_inferences() or task.get('inference_session_open'):
        return {**current, 'state': 'ATS_TERMINAL_HOLD', 'reason': 'The current task or inference has not settled.'}
    receipts = store.receipts(task['id'])
    calls = store.inference_receipts(task['id'])
    require(all(r['result'] is not None for r in receipts), 'The ATS task has an unresolved tool receipt.')
    if task['status'] != 'AWAITING_LIVE_VALIDATION':
        require(task['status'].startswith('PAUSED'), 'The ATS task is not at the expected terminal gate.')
        return {**current, 'state': 'ATS_TERMINAL_FAILURE', 'inference_receipts': [c['status'] for c in calls],
                'test_receipts': [{'receipt_id': r['id'], 'name': r['name'],
                                   'exit_code': (r['result'].get('result') or {}).get('exit_code')}
                                  for r in receipts if r['phase'] == 'verify'
                                  and r['name'] in ('code_test', 'acceptance_test')]}
    require(task['phase'] == 'verify' and task['sessions'] == task['calls'] == len(calls) == 1,
            'The ATS task does not have exactly one settled inference slot and call.')
    baseline = enrollment.baseline_path
    repo = store.base / task['id'] / 'repo'
    require(repo.resolve(strict=True) == repo and repo.is_dir(), 'The exact isolated task workspace changed.')
    before, final = files(baseline), files(repo)
    require(task['assignment_baseline'] == binding(before) and task['manifest'] == final,
            'The task no longer binds the private baseline and final workspace.')
    changed = sorted(name for name in before.keys() | final.keys() if before.get(name) != final.get(name))
    require(changed == [TARGET], 'The final task changed files outside the exact ATS parser.')
    proof = edit_proof(task, calls[0], receipts, baseline, before, final)
    verification = verification_proof(task, store, repo, receipts, final)
    require(store.get(task['id']) == task and store.receipts(task['id']) == receipts
            and store.inference_receipts(task['id']) == calls and not store.unresolved_inferences()
            and files(repo) == final and enrollment._source(jobs, destination) == source,
            'The candidate or its receipts changed during readback.')
    return {**current, 'state': 'ATS_TERMINAL_OFFLINE_ACK', 'settlement_sha256': SETTLEMENT_PIN,
            'source_revision': enrollment.source_revision, 'baseline_sha256': enrollment.baseline_sha256,
            'workspace_manifest_sha256': manifest_digest(final),
            'changed_paths': changed, 'parser_before_sha256': before[TARGET],
            'jetson_edit': proof, 'verification': verification}


def main():
    require(sys.flags.isolated and sys.flags.dont_write_bytecode and sys.pycache_prefix == '/dev/null'
            and Path(sys.prefix).resolve() == PROJECT / '.venv', 'Use isolated production Python without bytecode.')
    sys.path[:0] = [str(PROJECT / 'src'), str(TOOLS)]
    try:
        from job_search_helper.cli import load_environment

        load_environment(PROJECT / '.env')
        result = read_terminal()
    except (AttributeError, KeyError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
        result = {'state': 'ATS_TERMINAL_HOLD', 'failed_request_id': REQUEST_ID,
                  'outcome_id': OUTCOME_ID, 'reason': str(exc)}
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
