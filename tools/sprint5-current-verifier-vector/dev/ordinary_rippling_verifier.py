"""Source-only, one-attempt verifier for a private ordinary Forterra mismatch."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from urllib.parse import urlsplit
from uuid import uuid4


PENDING = 'ordinary-rippling-verification-pending-v1'
JOB = 'ordinary-rippling-verification-job-v1'
OWNER_JOB = 'ordinary-rippling-owned-verification-job-v1'
RECEIPT = 'ordinary-rippling-verifier-receipt-v1'
MODE = 'offline_saved_captures'
OBSERVATION = 'rippling-tenant-mismatch-v1'
FORTERRA_URL = 'https://www.forterra.com/careers'
FORTERRA_BOARD = 'https://ats.rippling.com/forterra/jobs'
PDW_BOARD = 'https://ats.rippling.com/pdwcareers/jobs'
TOOLS = {
    'validate_candidate.py': 'e1e5cfb34c01694f9722169343d9fe19417c16623758de79cb74c17685aca25e',
    'rippling_public_authority.py': '5297cf4832bb287c91fac89f498729ec6c2d1c1dff9dc23008a6949568ac3e57',
    'rippling_capture.py': '46a0d7372a6e73447e59fb2f6a9e3b3e25839ec48a82a3293c98b5874d87db0d',
}
MAX_SECONDS = 120
MAX_REQUESTS = 128
SMALL = 64 * 1024
LARGE = 64 * 1024 * 1024
SHA = re.compile(r'[0-9a-f]{64}')
SLUG = re.compile(r'[a-z0-9][a-z0-9_-]{0,99}')
TERMINAL = {'VERIFIED_MISMATCH', 'HOLD', 'TIMEOUT', 'BUDGET_EXHAUSTED', 'CHANGED_INPUT'}
LEASE_ENV = {'JSH_SCRAPER_ADMISSION_FD', 'JSH_SCRAPER_ADMISSION_PATH', 'JSH_SCRAPER_RUNTIME_BINDING'}


class Stop(Exception):
    def __init__(self, result, reason):
        super().__init__(reason)
        self.result = result
        self.reason = reason


class BudgetStop(BaseException):
    # Provider and dispatch code may catch Exception and treat it as evidence
    # ambiguity. A private budget stop must reach the supervisor unchanged.
    def __init__(self, result, reason):
        super().__init__(reason)
        self.result = result
        self.reason = reason


def require(condition, reason, result='HOLD'):
    if not condition:
        raise Stop(result, reason)


def digest(raw):
    return sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def parse(raw):
    def no_duplicates(pairs):
        value = dict(pairs)
        require(len(pairs) == len(value), 'duplicate_json_keys')
        return value

    return json.loads(raw, object_pairs_hook=no_duplicates)


def fields(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected.split()), 'unexpected_input_fields')


def hashes(*values):
    require(all(isinstance(value, str) and SHA.fullmatch(value) for value in values), 'invalid_identity_digest')


def read_regular(path, limit, *, directory=None, private=False):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(descriptor, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1, 'not_a_single_link_regular_file')
        if private:
            require(metadata.st_uid == os.geteuid() and not metadata.st_mode & 0o077, 'unsafe_private_file')
        data = stream.read(limit + 1)
    require(len(data) <= limit, 'input_size_limit')
    return data


def read_pin(directory, filename, expected):
    try:
        raw = read_regular(filename, SMALL, directory=directory, private=True)
    except FileNotFoundError:
        raise Stop('CHANGED_INPUT', 'pinned_private_input_missing') from None
    require(digest(raw) == expected, 'pinned_private_input_changed', 'CHANGED_INPUT')
    return parse(raw)


def slug_for_url(url):
    require(isinstance(url, str), 'invalid_configured_board')
    route = urlsplit(url)
    slug = route.path.removeprefix('/').removesuffix('/jobs')
    require(SLUG.fullmatch(slug) and url == f'https://ats.rippling.com/{slug}/jobs', 'invalid_configured_board')
    return slug


def validate_inputs(pending, job, pending_sha):
    fields(pending, 'schema owner admission observation')
    fields(job, 'schema pending_sha256 candidate_replay_pin_sha256 mismatch_response_sha256 deadline_unix_ms request_limit')
    owner, admission, observation = pending['owner'], pending['admission'], pending['observation']
    fields(owner, 'cycle_id cycle_started_at request_id request_fingerprint company_id source_revision company_source_sha256 '
                  'store_binding_sha256 observation_generation')
    fields(admission, 'authority_url configured_url capability_id capability_digest mapping_digest configuration_digest '
                      'matrix_digest runtime_binding_sha256')
    fields(observation, 'schema configured_url expected_slug observed_slug response_sha256')
    require(pending['schema'] == PENDING and job['schema'] in {JOB, OWNER_JOB}
            and observation['schema'] == OBSERVATION,
            'unsupported_verifier_scope')
    hashes(owner['request_fingerprint'], owner['source_revision'], owner['company_source_sha256'], owner['store_binding_sha256'],
           *(admission[key] for key in ('capability_digest', 'mapping_digest', 'configuration_digest', 'matrix_digest',
                                        'runtime_binding_sha256')),
           observation['response_sha256'], job['candidate_replay_pin_sha256'], job['mismatch_response_sha256'])
    require(owner['company_id'] == 'COMP-0066' and isinstance(owner['cycle_id'], str)
            and re.fullmatch(r'CYC-[A-F0-9]{12}', owner['cycle_id'])
            and isinstance(owner['cycle_started_at'], str)
            and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})', owner['cycle_started_at'])
            and isinstance(owner['request_id'], str)
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9:._-]{0,255}', owner['request_id'])
            and type(owner['observation_generation']) is int and owner['observation_generation'] > 0,
            'unsupported_ordinary_owner')
    require(datetime.fromisoformat(owner['cycle_started_at']).utcoffset() == timedelta(0),
            'ordinary_cycle_time_must_be_utc')
    require(admission['capability_id'] == 'rippling-shared-v1' and admission['authority_url'] == FORTERRA_URL,
            'unsupported_rippling_authority')
    configured = slug_for_url(admission['configured_url'])
    foreign = observation['observed_slug']
    require(isinstance(foreign, str) and SLUG.fullmatch(foreign) and observation['expected_slug'] == configured
            and observation['configured_url'] == admission['configured_url']
            and len({configured, foreign, 'forterra', 'pdwcareers'}) == 4, 'unproved_distinct_tenant_mismatch')
    require(job['pending_sha256'] == pending_sha and job['mismatch_response_sha256'] == observation['response_sha256'],
            'job_pin_conflicts_with_pending', 'CHANGED_INPUT')
    require(type(job['deadline_unix_ms']) is int and job['deadline_unix_ms'] > 0 and type(job['request_limit']) is int
            and 0 < job['request_limit'] <= MAX_REQUESTS, 'invalid_verification_budget')


class Budget:
    def __init__(self, job):
        self.limit = job['request_limit']
        self.used = 0
        duration = (job['deadline_unix_ms'] - time.time_ns() // 1_000_000) / 1000
        require(duration > 0, 'verification_deadline', 'TIMEOUT')
        require(duration <= MAX_SECONDS, 'deadline_exceeds_bound')
        self.ends = time.monotonic() + duration

    def remaining(self):
        duration = self.ends - time.monotonic()
        if duration <= 0:
            raise BudgetStop('TIMEOUT', 'verification_deadline')
        return duration

    def charge(self):
        self.remaining()
        if self.used >= self.limit:
            raise BudgetStop('BUDGET_EXHAUSTED', 'request_budget_exhausted')
        self.used += 1


def stop_timer(_signum, _frame):
    raise BudgetStop('TIMEOUT', 'verification_deadline')


def load(path, name):
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def replay_public(args, pending, job, budget, scratch):
    for name, expected in TOOLS.items():
        raw = read_regular(args.reviewed_tools / name, SMALL)
        require(digest(raw) == expected, 'reviewed_verifier_source_changed', 'CHANGED_INPUT')
        (scratch / name).write_bytes(raw)
    validator = load(scratch / 'validate_candidate.py', '_approved_candidate_validator')
    oracle = load(scratch / 'rippling_capture.py', 'rippling_capture')
    evidence = args.evidence
    with private_slot(evidence):
        pass
    pin = read_regular(evidence / 'replay-pin.json', SMALL, private=True)
    require(digest(pin) == job['candidate_replay_pin_sha256'], 'reviewed_replay_pin_changed', 'CHANGED_INPUT')
    replay_pin = parse(pin)
    validator.validate_pin(replay_pin)
    scope = replay_pin['scope'][0]
    require(scope['company_row_sha256'] == pending['owner']['company_source_sha256']
            and scope['source_revision'] == pending['owner']['source_revision']
            and scope['authority_url'] == pending['admission']['authority_url'], 'replay_company_is_not_pending_company',
            'CHANGED_INPUT')
    capture = read_regular(evidence / 'public-capture.json', LARGE, private=True)
    require(digest(capture) == replay_pin['capture_sha256'], 'reviewed_public_capture_changed', 'CHANGED_INPUT')
    parsed = parse(capture)
    require(parsed.get('schema') == 'rippling-public-capture-v1', 'public_evidence_required')
    # The mismatch is from the ordinary worker's sealed typed observation. Its
    # captured final response is independently inspected below, not refetched.
    budget.charge()
    mismatch = read_regular(evidence / 'configured-response.html', 6 * 1024 * 1024, private=True)
    require(digest(mismatch) == job['mismatch_response_sha256'], 'configured_response_changed', 'CHANGED_INPUT')
    seen = pending['observation']['observed_slug']
    board = f'https://ats.rippling.com/{seen}/jobs'
    oracle.read_listing(board, 0, mismatch.decode())
    del mismatch, parsed
    for filename, raw in (('replay-pin.json', pin), ('public-capture.json', capture)):
        (scratch / filename).write_bytes(raw)

    def charge(method):
        def invoke(self, *method_args, **kwargs):
            budget.charge()
            return method(self, *method_args, **kwargs)
        return invoke

    validator.BoardReplay.get = charge(validator.BoardReplay.get)
    validator.BoardReplay.post = charge(validator.BoardReplay.post)
    validator.EmployerReplay.get = charge(validator.EmployerReplay.get)
    # The approved loader opens this module again during public-mode dispatch.
    # Count authoritative employer records and the redirect at the replay seam,
    # independently of any optional employer discovery requests.
    original_load = validator.load_source

    def budgeted_load(name, path):
        module, pin_sha = original_load(name, path)
        if name == 'rippling_public_authority':
            check = module.check_public_authority

            def check_metered(company_id, board_url, record):
                budget.charge()
                if record.get('redirect') is not None:
                    budget.charge()
                return check(company_id, board_url, record)

            module.check_public_authority = check_metered
        return module, pin_sha

    validator.load_source = budgeted_load
    reviewed = {'schema': validator.RECEIPT_SCHEMA, 'cases': []}
    try:
        result = validator.run(args.candidate, scratch / 'replay-pin.json', scratch / 'public-capture.json',
                               args.candidate / 'release_admission_bootstrap.py', reviewed)
    except validator.ValidationError as error:
        if str(error) in {'measurement_tool_digest_mismatch', 'candidate_pin_mismatch_before_dispatch',
                          'candidate_pin_mismatch_after_dispatch', 'frozen_candidate_pin_mismatch',
                          'frozen_candidate_changed_during_dispatch', 'executed_package_manifest_mismatch'}:
            raise Stop('CHANGED_INPUT', 'reviewed_candidate_identity_changed') from None
        raise
    budget.remaining()
    forterra, pdw = reviewed['cases']
    require(result == 'PUBLIC_EVIDENCE_ACCEPTED' and reviewed['release_qualification'] is False
            and forterra['board_url'] == FORTERRA_BOARD and pdw['board_url'] == PDW_BOARD,
            'complete_public_candidate_and_control_required')
    evidence = {'configured_observation_sha256': job['mismatch_response_sha256'],
                'authority_extraction_digest': digest(canonical(forterra['authority'])),
                'candidate_inventory_digest': forterra['posting_evidence_sha256'],
                'regression_inventory_digest': pdw['posting_evidence_sha256'],
                'candidate_vector': reviewed['candidate'], 'replay_capture_sha256': reviewed['capture_sha256'],
                'replay_receipt_sha256': digest(canonical(reviewed))}
    return evidence


def worker(args):
    budget = None
    try:
        require(args.worker >= 3, 'private_worker_gate_required')
        with os.fdopen(args.worker, 'rb', buffering=0) as gate:
            require(stat.S_ISFIFO(os.fstat(gate.fileno()).st_mode), 'private_worker_gate_required')
            os.set_blocking(gate.fileno(), False)
            admission = gate.read(SMALL)
        identity = verification_identity(args)
        with private_slot(args.slot) as directory:
            require(admission == canonical({'owner_pid': os.getppid(), 'identity': identity,
                                            'slot_identity': physical_identity(os.fstat(directory))}),
                    'private_worker_gate_required')
            check_owner_slot(args, directory, identity)
            require(optional_read(directory, 'reservation.json') == identity, 'private_worker_reservation_required')
            pending = read_pin(directory, 'pending.json', args.pending_sha256)
            job = read_pin(directory, 'job.json', args.job_sha256)
        validate_inputs(pending, job, args.pending_sha256)
        budget = Budget(job)
        signal.signal(signal.SIGALRM, stop_timer)
        signal.setitimer(signal.ITIMER_REAL, budget.remaining())
        try:
            with TemporaryDirectory(prefix='jsh-rippling-verifier-', dir='/tmp') as scratch:
                evidence = replay_public(args, pending, job, budget, Path(scratch))
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    except (Stop, BudgetStop) as failure:
        value = {'result': failure.result, 'reason': failure.reason, 'evidence': None}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, ImportError, AttributeError):
        value = {'result': 'HOLD', 'reason': 'offline_replay_did_not_verify', 'evidence': None}
    else:
        value = {'result': 'VERIFIED_MISMATCH', 'reason': 'exact_pending_observation_and_public_control_verified',
                 'evidence': evidence}
    value['requests_used'] = budget.used if budget is not None else 0
    return value


@contextmanager
def private_slot(path):
    require(path.is_absolute() and path.resolve() == path and path.is_relative_to('/tmp') and path != Path('/tmp'),
            'private_slot_must_be_an_exact_temporary_path')
    directory = os.open(path, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        require(info.st_uid == os.geteuid() and not info.st_mode & 0o077, 'unsafe_private_directory')
        yield directory
    finally:
        os.close(directory)


def physical_identity(info):
    return [info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode)]


def check_named_slot(path, directory):
    try:
        named = os.stat(path, follow_symlinks=False)
    except OSError:
        raise Stop('CHANGED_INPUT', 'private_slot_path_changed') from None
    require(physical_identity(named) == physical_identity(os.fstat(directory)),
            'private_slot_path_changed', 'CHANGED_INPUT')


def publish(directory, filename, value):
    temporary = f'.verifier-{uuid4().hex}'
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        # The private mutex serializes all authorized publishers in this slot.
        try:
            os.stat(filename, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            os.replace(temporary, filename, src_dir_fd=directory, dst_dir_fd=directory)
        else:
            raise Stop('HOLD', 'private_record_already_exists')
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
    os.fsync(directory)


def optional_read(directory, filename):
    try:
        return parse(read_regular(filename, SMALL, directory=directory, private=True))
    except FileNotFoundError:
        return None


def verification_identity(args):
    hashes(args.pending_sha256, args.job_sha256)
    return {'pending_sha256': args.pending_sha256, 'job_sha256': args.job_sha256,
            'verifier_sha256': digest(Path(__file__).read_bytes()), 'reviewed_tools_sha256': digest(canonical(TOOLS))}


def check_owner_slot(args, directory, identity):
    """Keep an assigned application slot bound across a process launch."""
    proof = getattr(args, 'owner_slot', None)
    owner = optional_read(directory, 'owner.json')
    job = read_pin(directory, 'job.json', args.job_sha256)
    require(isinstance(job, dict), 'unexpected_input_fields')
    if proof is None:
        require(owner is None and job.get('schema') == JOB, 'assigned_offline_slot_requires_owner_proof')
        return
    require(isinstance(proof, str) and re.fullmatch(r'(?:[1-9][0-9]{0,20}:){4}[a-f0-9]{64}', proof)
            and args.evidence == args.slot and isinstance(owner, dict) and job.get('schema') == OWNER_JOB,
            'invalid_owner_slot_proof', 'CHANGED_INPUT')
    root_device, root_inode, slot_device, slot_inode, manifest = proof.split(':')
    expected_root = [int(root_device), int(root_inode)]
    expected_slot = [int(slot_device), int(slot_inode)]
    name = args.slot.name
    hashes(name)
    require(physical_identity(os.fstat(directory))[:2] == expected_slot
            and owner.get('schema') == 'ordinary-verifier-offline-work-v1'
            and owner.get('mode') == MODE and owner.get('identity') == identity
            and owner.get('dispatch_sha256') == name and owner.get('root_identity') == expected_root
            and owner.get('slot_identity') == expected_slot and digest(canonical(owner)) == manifest,
            'assigned_offline_slot_changed', 'CHANGED_INPUT')
    with private_slot(args.slot.parent) as root:
        require(physical_identity(os.fstat(root))[:2] == expected_root
                and optional_read(root, name + '.json') == {
                    'schema': 'ordinary-verifier-offline-owner-v1', 'dispatch_sha256': name,
                    'slot_identity': expected_slot, 'owner_manifest_sha256': manifest,
                }, 'assigned_offline_owner_changed', 'CHANGED_INPUT')
        check_named_slot(args.slot.parent, root)
    check_named_slot(args.slot, directory)


def supervise(args):
    require(not LEASE_ENV.intersection(os.environ), 'inherited_application_lease_present')
    identity = verification_identity(args)
    with private_slot(args.slot) as directory:
        check_owner_slot(args, directory, identity)
        mutex = os.open('verifier.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
        try:
            info = os.fstat(mutex)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid()
                    and not info.st_mode & 0o077, 'unsafe_private_mutex')
            try:
                fcntl.flock(mutex, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {'delivery': 'BUSY', 'result': 'HOLD', 'reason': 'private_verifier_attempt_in_progress'}
            return own_attempt(directory, args, identity)
        finally:
            os.close(mutex)


def own_attempt(directory, args, identity):
    check_named_slot(args.slot, directory)
    job = read_pin(directory, 'job.json', args.job_sha256)
    pending = read_pin(directory, 'pending.json', args.pending_sha256)
    validate_inputs(pending, job, args.pending_sha256)
    reservation = optional_read(directory, 'reservation.json')
    prior = optional_read(directory, 'receipt.json')
    check_owner_slot(args, directory, identity)
    if prior is not None:
        fields(prior, 'receipt receipt_sha256')
        receipt = prior['receipt']
        require(reservation == identity and prior['receipt_sha256'] == digest(canonical(receipt)),
                'conflicting_private_receipt')
        validate_receipt(receipt, identity, job)
        return {'delivery': 'REUSED', 'result': receipt['result'], **prior}
    delivery = 'NEW'
    if reservation is not None:
        require(reservation == identity, 'conflicting_private_reservation')
        # An interrupted same-generation attempt already reserved this entire
        # budget. Retire it without making any further replay requests.
        expired = time.time_ns() // 1_000_000 >= job['deadline_unix_ms']
        response = {'result': 'TIMEOUT' if expired else 'HOLD',
                    'reason': 'verification_deadline' if expired else 'interrupted_reserved_attempt',
                    'evidence': None, 'requests_used': None}
        delivery = 'INTERRUPTED'
    else:
        publish(directory, 'reservation.json', identity)
        response = run_child(args, job, physical_identity(os.fstat(directory)))
    check_named_slot(args.slot, directory)
    if getattr(args, 'owner_slot', None) is not None:
        check_owner_slot(args, directory, identity)
    try:
        read_pin(directory, 'job.json', args.job_sha256)
        read_pin(directory, 'pending.json', args.pending_sha256)
    except (Stop, OSError, ValueError, TypeError):
        response.update(result='CHANGED_INPUT', reason='private_input_changed_during_verification', evidence=None)
    receipt = {'schema': RECEIPT, 'mode': MODE, 'identity': identity, 'request_limit': job['request_limit'],
               'deadline_unix_ms': job['deadline_unix_ms'], **response}
    validate_receipt(receipt, identity, job)
    record = {'receipt': receipt, 'receipt_sha256': digest(canonical(receipt))}
    publish(directory, 'receipt.json', record)
    return {'delivery': delivery, 'result': receipt['result'], **record}


def validate_receipt(receipt, identity, job):
    fields(receipt, 'schema mode identity request_limit deadline_unix_ms result reason evidence requests_used')
    result, evidence, used = receipt['result'], receipt['evidence'], receipt['requests_used']
    require(receipt['schema'] == RECEIPT and receipt['mode'] == MODE and receipt['identity'] == identity and result in TERMINAL
            and receipt['request_limit'] == job['request_limit'] and receipt['deadline_unix_ms'] == job['deadline_unix_ms']
            and isinstance(receipt['reason'], str) and re.fullmatch(r'[a-z_]+', receipt['reason'])
            and (used is None or type(used) is int and 0 <= used <= job['request_limit']),
            'conflicting_private_receipt')
    if result == 'VERIFIED_MISMATCH':
        fields(evidence, 'configured_observation_sha256 authority_extraction_digest candidate_inventory_digest '
                         'regression_inventory_digest candidate_vector replay_capture_sha256 replay_receipt_sha256')
        require(evidence['configured_observation_sha256'] == job['mismatch_response_sha256']
                and receipt['reason'] == 'exact_pending_observation_and_public_control_verified'
                and type(used) is int and used > 0, 'conflicting_private_receipt')
        fields(evidence['candidate_vector'], 'source_manifest_sha256 config_sha256 dependency_manifest_sha256')
        hashes(*evidence['candidate_vector'].values(), *(value for key, value in evidence.items()
                                                        if key != 'candidate_vector'))
    else:
        require(evidence is None, 'nonverifying_receipt_contains_positive_evidence')


def run_child(args, job, slot_identity):
    try:
        budget = Budget(job)
        read_fd, write_fd = os.pipe()
        with os.fdopen(read_fd, 'rb') as gate:
            with os.fdopen(write_fd, 'wb') as sender:
                sender.write(canonical({'owner_pid': os.getpid(), 'identity': verification_identity(args),
                                        'slot_identity': slot_identity}))
            command = [sys.executable, '-I', '-S', '-B', str(Path(__file__).resolve()), '--worker', str(gate.fileno())]
            for field in ('slot', 'evidence', 'candidate', 'reviewed_tools', 'pending_sha256', 'job_sha256'):
                command.extend(('--' + field.replace('_', '-'), str(getattr(args, field))))
            if getattr(args, 'owner_slot', None) is not None:
                command.extend(('--owner-slot', args.owner_slot))
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, close_fds=True,
                                    pass_fds=(gate.fileno(),), env={}, timeout=budget.remaining(), check=False)
        budget.remaining()
        require(result.returncode == 0 and len(result.stdout) <= SMALL, 'offline_worker_exited_without_evidence')
        value = parse(result.stdout)
        fields(value, 'result reason evidence requests_used')
        require(value['result'] in TERMINAL and type(value['requests_used']) is int
                and 0 <= value['requests_used'] <= job['request_limit'], 'malformed_offline_worker_receipt')
        return value
    except subprocess.TimeoutExpired:
        return {'result': 'TIMEOUT', 'reason': 'verification_deadline', 'evidence': None, 'requests_used': None}
    except (Stop, BudgetStop) as failure:
        return {'result': failure.result, 'reason': failure.reason, 'evidence': None, 'requests_used': None}
    except (OSError, ValueError, TypeError, KeyError):
        return {'result': 'HOLD', 'reason': 'offline_worker_exited_without_evidence', 'evidence': None, 'requests_used': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=int, help=argparse.SUPPRESS)
    for name in ('slot', 'evidence', 'candidate', 'reviewed-tools'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--pending-sha256', required=True)
    parser.add_argument('--job-sha256', required=True)
    parser.add_argument('--owner-slot')
    args = parser.parse_args()
    try:
        require(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode, 'isolated_python_required')
        value = worker(args) if args.worker is not None else supervise(args)
    except Stop as failure:
        value = {'delivery': 'REJECTED', 'result': failure.result, 'reason': failure.reason}
    except (OSError, ValueError, TypeError, KeyError):
        value = {'delivery': 'REJECTED', 'result': 'HOLD', 'reason': 'private_inputs_or_receipt_unavailable'}
    print(canonical(value).decode())
    return 0 if args.worker is not None or value['result'] == 'VERIFIED_MISMATCH' else 1


if __name__ == '__main__':
    sys.exit(main())
