"""Read the exact production ATS pilot. Never starts a task, scrape, or write."""

import argparse
import json
import os
import stat
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
ENROLLMENT = Path('/tmp/jsh-ats-classifier-release/activation/LIVE_ENROLLMENT.json')
REQUEST_ID = 'operator-ats-20261122-02'
DEVELOP_DEPLOYMENT = 'REL-4141919bb885000b0e7244c2'
BASELINE_PIN = '23df31abf76869b7df3517511418bba7b721a0abb6732de1d0ee55b22f1eb7c6'
REVISION = '08ecbb56e99f89bbcb63b60c5af1197c7535e9196a997135473370895e695a32'
FINGERPRINT = '9fdcfc10ac7273ab6e71f4e8552aab13397ae19ffcfe1234dbea61ace8d48125'
PREDECESSOR_TASK = 'WRAP-9db6388719'
PREDECESSOR_OUTCOME = 'OUT-8b214610d53e23115e70da5f'
PREDECESSOR_KEY = '0d6846138372a12f8d52398a2124f220a0bf565e2cd16cae13bd6df06e71a5be'
PREDECESSOR_STATE = '64d4ef964e53ea88bdd907d35b22532fceef7512a949217b5380d04382b8d96f'


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read_enrollment(pin):
    from ats_operator_pilot import ATSOperatorEnrollment, ENV

    require(ENROLLMENT.resolve(strict=True) == ENROLLMENT, 'The enrollment path changed.')
    info = ENROLLMENT.stat(follow_symlinks=False)
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1
            and not info.st_mode & 0o077, 'Expected the private operator enrollment.')
    raw = ENROLLMENT.read_bytes()
    require(sha256(raw).hexdigest() == pin, 'The exact ATS enrollment bytes changed.')
    enrollment = ATSOperatorEnrollment.from_process_environment({ENV: raw.decode()})
    successor = enrollment.successor
    require(enrollment.request_id == REQUEST_ID and enrollment.source_revision == REVISION
            and enrollment.baseline_sha256 == BASELINE_PIN and successor is not None
            and successor.failure_fingerprint == FINGERPRINT and successor.predecessor_task_id == PREDECESSOR_TASK
            and successor.predecessor_repair_key == PREDECESSOR_KEY
            and successor.predecessor_task_state_sha256 == PREDECESSOR_STATE
            and successor.predecessor_outcome_id == PREDECESSOR_OUTCOME and successor.outcome_id != PREDECESSOR_OUTCOME,
            'The enrollment does not bind this exact ATS successor.')
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


def edit_proof(task, call, receipts, baseline, before, after, repo):
    from ats_parser_assignment import EDIT_ANCHOR, MAX_TOKENS, TARGET
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
        and args['old'] == EDIT_ANCHOR and args['new'] and args['old'] != args['new']
        and call.get('accepted_ats_parser_edit')
        == {'path': TARGET, 'sha256': args['sha256'], 'arguments_sha256': digest(args)},
        'The parser edit arguments differ from the authorized model response.',
    )
    original = (baseline / TARGET).read_bytes()
    text = original.decode()
    require(sha256(original).hexdigest() == before[TARGET] and text.count(args['old']) == 1,
            'The exact original parser bytes do not admit this edit.')
    rebuilt = text.replace(args['old'], args['new'], 1).encode()
    require((repo / TARGET).read_bytes() == rebuilt, 'The complete classifier file differs from the single model edit.')
    replayed_hash = sha256(rebuilt).hexdigest()
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
    for name in (*task['tests'], 'tests/fixtures/ats_job_path_examples.json'):
        require(bundle['manifest'].get(name) and bundle['manifest'][name] == final.get(name),
                'Immutable acceptance inputs differ from the classifier baseline.')
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


def read_terminal(enrollment_pin, settlement_pin):
    from ats_parser_assignment import COMPANY_ID, TARGET, is_assignment
    from coordinator_baseline import binding, files
    from coordinator_evidence import manifest_digest
    from coordinator_store import task_state_digest
    from job_search_helper.inbox import InventoryInbox

    enrollment, store = read_enrollment(enrollment_pin), readonly_store()
    outcome_id = enrollment.successor.outcome_id
    from job_search_helper.operator_company_request import _digest, _read
    receipt_path = STATE / 'operator-company-requests' / 'receipts' / (_digest({'request_id': REQUEST_ID}) + '.json')
    require(receipt_path.resolve(strict=True) == receipt_path, 'The original ATS request receipt path changed.')
    request = _read(receipt_path)
    require(request.get('request_id') == REQUEST_ID and request.get('request_sha256') == enrollment.request_sha256,
            'ATS successor enrollment differs from its application request receipt.')
    jobs = STATE / 'jobs.sqlite3'
    inbox = STATE / 'inventories.sqlite3'
    for path in (jobs, inbox):
        require(path.resolve(strict=True) == path and path.is_file(), 'ATS application store path changed.')
    destination = InventoryInbox.destination_id(inbox)
    source = enrollment._source(jobs, destination)
    require(source and source['acknowledged'] and source['record']['outcome_id'] == outcome_id
            and source['record']['failure_fingerprint'] == FINGERPRINT
            and source['record']['identity']['request_id'] == REQUEST_ID
            and source['proof']['request_sha256'] == enrollment.request_sha256
            and source['proof']['settlement_sha256'] == settlement_pin
            and source['proof']['runtime']['release_id'] == DEVELOP_DEPLOYMENT
            and enrollment._sources_match(PROJECT),
            'Waiting for the exact acknowledged ATS source and settlement.')
    pair = enrollment.resolve_owned_pair(store, source)
    require(pair is not None and pair[1] is not None, 'Waiting for the ATS coordinator task.')
    held, task = pair
    expected_tests = {'tests/test_ats_job_path_examples.py', 'tests/test_ats_sitemap_parser.py',
                      'tests/test_successfactors.py'}
    predecessor = store.get(PREDECESSOR_TASK)
    require(predecessor and task_state_digest(predecessor) == PREDECESSOR_STATE
            and predecessor['status'] == 'PAUSED_TEST_FAILURE'
            and task['id'] != PREDECESSOR_TASK and held['repair_key'] == store._operator_successor_repair_key(PREDECESSOR_KEY)
            and len(task['tests']) == len(expected_tests) and set(task['tests']) == expected_tests
            and TARGET == 'src/job_search_helper/ats_job_path.py',
            'The predecessor, classifier target or required test suite differs.')
    require(
        re.fullmatch(r'WRAP-[0-9a-f]{10}', task['id']) and is_assignment(task)
        and enrollment._task_matches(held, task, enrollment._proposal(held, source['company'])),
        'The ATS task does not match the paired application outcome.',
    )
    current = {'company_id': COMPANY_ID, 'predecessor_task_id': PREDECESSOR_TASK,
               'task_id': task['id'], 'failed_request_id': REQUEST_ID,
               'outcome_id': outcome_id, 'task_status': task['status'], 'phase': task['phase'],
               'task_state_sha256': task_state_digest(task), 'reason': task['reason']}
    if (enrollment._never_activated(store, task) or task['status'] in ('RUNNING', 'QUEUED', 'PAUSING')
            or store.unresolved_inferences() or task.get('inference_session_open')):
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
    proof = edit_proof(task, calls[0], receipts, baseline, before, final, repo)
    verification = verification_proof(task, store, repo, receipts, final)
    require(store.get(task['id']) == task and store.receipts(task['id']) == receipts
            and store.inference_receipts(task['id']) == calls and not store.unresolved_inferences()
            and files(repo) == final and enrollment._source(jobs, destination) == source
            and _read(receipt_path) == request and read_enrollment(enrollment_pin) == enrollment
            and store.get(PREDECESSOR_TASK) == predecessor,
            'The candidate or its receipts changed during readback.')
    return {**current, 'state': 'ATS_TERMINAL_OFFLINE_ACK', 'settlement_sha256': settlement_pin,
            'source_revision': enrollment.source_revision, 'baseline_sha256': enrollment.baseline_sha256,
            'workspace_manifest_sha256': manifest_digest(final),
            'changed_paths': changed, 'parser_before_sha256': before[TARGET],
            'jetson_edit': proof, 'verification': verification}


def main():
    require(sys.flags.isolated and sys.flags.dont_write_bytecode and sys.pycache_prefix == '/dev/null'
            and Path(sys.prefix).resolve() == PROJECT / '.venv', 'Use isolated production Python without bytecode.')
    sys.path[:0] = [str(PROJECT / 'src'), str(TOOLS)]
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--enrollment-sha256', required=True)
    parser.add_argument('--settlement-sha256', required=True)
    args = parser.parse_args()
    try:
        require(all(re.fullmatch('[0-9a-f]{64}', v) for v in vars(args).values()), 'Expected SHA-256 evidence pins.')
        from job_search_helper.cli import load_environment

        load_environment(PROJECT / '.env')
        result = read_terminal(args.enrollment_sha256, args.settlement_sha256)
    except (AttributeError, KeyError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
        result = {'state': 'ATS_TERMINAL_HOLD', 'failed_request_id': REQUEST_ID,
                  'reason': str(exc)}
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
