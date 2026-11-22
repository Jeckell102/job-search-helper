"""Private measured entry for the already-installed Amphenol retry only."""

from argparse import ArgumentParser
from contextlib import ExitStack, closing, nullcontext
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
from types import ModuleType


PROJECT = Path('/home/chris/job-search-helper_old')
ROOT = PROJECT / '.state'
RELEASE = 'REL-f509ed362bf8781ea8840adc'
ATTEMPT = 'RTRY-8d1210858e4e26f325312a89'
CYCLE = 'CYC-4650772EEE1E'
COMPANY = 'COMP-0490'


def file_bytes(path, pin, *, private=False):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not os.path.samestat(info, path.stat(follow_symlinks=False))
                or (private and (info.st_uid != os.geteuid() or info.st_mode & 0o077))):
            raise ValueError('Unexpected measured file: ' + path.name)
        data = handle.read()
    if sha256(data).hexdigest() != pin:
        raise ValueError('Changed measured file: ' + path.name)
    return data


def load_pinned_module(name, path, pin):
    if name in sys.modules:
        raise ValueError('Release module was imported before measurement: ' + name)
    raw = file_bytes(path, pin)
    module = ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def main():
    parser = ArgumentParser(allow_abbrev=False)
    parser.add_argument('action', choices=('verify-inputs', 'apply'))
    parser.add_argument('--approval', required=True, type=Path)
    parser.add_argument('--approval-sha256', required=True)
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.pycache_prefix != '/dev/null':
        raise ValueError('Run the reviewed entry with installed Python -I -B -X pycache_prefix=/dev/null.')
    if Path(sys.prefix).resolve(strict=True) != PROJECT / '.venv':
        raise ValueError('Use the installed release Python environment.')
    stage = args.approval.parent.resolve(strict=True)
    if (not stage.is_relative_to('/tmp') or stage.stat().st_uid != os.geteuid()
            or stage.stat().st_mode & 0o077 or args.approval.parent != stage):
        raise ValueError('The exact recovery approval must be in its private staging directory.')
    approval = json.loads(file_bytes(args.approval, args.approval_sha256, private=True))
    if approval['schema'] not in {'amphenol-saved-retry-proposal-v1', 'amphenol-saved-retry-approval-v1'}:
        raise ValueError('Expected explicit saved-retry recovery approval.')
    if args.action == 'apply':
        if approval['schema'] != 'amphenol-saved-retry-approval-v1':
            raise ValueError('Verify-only proposal lacks the independent apply approval.')
        review = Path(approval['independent_review_path'])
        file_bytes(review, approval['independent_review_sha256'])
    pins = approval['tool_sha256']
    tools = Path(__file__).resolve().parent
    file_bytes(Path(__file__).resolve(), pins['approved_recovery_entry.py'])
    proof = approval['saved_retry']
    if (proof['company_id'], proof['cycle_id'], proof['attempt_id'], proof['release_id']) != (
            COMPANY, CYCLE, ATTEMPT, RELEASE):
        raise ValueError('Approval belongs to a different retry.')
    candidate = json.loads(file_bytes(stage / 'proposed-successor.json', proof['successor_file_sha256'],
                                      private=True))
    qualification_path = Path(approval['qualification_path'])
    qualification = json.loads(file_bytes(qualification_path, approval['qualification_sha256'], private=True))
    if qualification['release_id'] != RELEASE:
        raise ValueError('The original qualification belongs to a different release.')

    bootstrap = load_pinned_module('release_admission_bootstrap', PROJECT / 'release_admission_bootstrap.py',
                                   pins['release_admission_bootstrap.py'])
    bootstrap._load_environment(PROJECT / '.env')
    database = bootstrap._project_path(PROJECT, os.environ.get('STATE_DB_FILE', '.state/state.db'))
    layout = bootstrap._retained_operator_sqlite_layout(PROJECT, database, 'sqlite')
    if database != ROOT / 'state.db' or layout != approval['sqlite_layout']:
        raise ValueError('The exact admitted application stores changed.')
    inbox_path = ROOT / 'inventories.sqlite3'
    inbox_info = inbox_path.stat(follow_symlinks=False)
    if (not stat.S_ISREG(inbox_info.st_mode) or inbox_info.st_nlink != 1
            or [inbox_info.st_dev, inbox_info.st_ino] != approval['inventory_identity']):
        raise ValueError('The exact admitted inventory store changed.')
    lock = ROOT / 'scraper.lock'
    if args.action == 'verify-inputs':
        if bootstrap._validate_runtime(PROJECT, ROOT) != approval['runtime']:
            raise ValueError('Approved runtime is no longer installed.')
        for name in ('rejected_retry_plan.py', 'recover_saved_retry.py'):
            file_bytes(tools / name, pins[name])
        print(json.dumps({'state': 'SAVED_RETRY_INPUTS_VERIFIED', 'attempt_id': ATTEMPT}))
        return

    descriptor = os.open(lock, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as acquired:
        lock_info = os.fstat(acquired.fileno())
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1:
            raise ValueError('Invalid canonical scraper lock.')
        fcntl.flock(acquired.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        runtime = bootstrap._validate_runtime(PROJECT, ROOT)
        if (runtime != approval['runtime']
                or bootstrap._retained_operator_sqlite_layout(PROJECT, database, 'sqlite') != layout
                or not os.path.samestat(inbox_info, inbox_path.stat(follow_symlinks=False))
                or not os.path.samestat(lock_info, lock.stat(follow_symlinks=False))):
            raise ValueError('Runtime or store identity changed before scraper admission.')
        sys.path.insert(0, str(PROJECT / 'src'))
        from job_search_helper.runner import _scraper_admission

        inbound = os.dup(acquired.fileno())
        os.environ.update(JSH_SCRAPER_ADMISSION_FD=str(inbound), JSH_SCRAPER_ADMISSION_PATH=str(lock),
                          JSH_SCRAPER_RUNTIME_BINDING=json.dumps(runtime, sort_keys=True))
        # Only the inherited duplicate belongs to the application admission.
        # Keep no other reference open during the normal separately locked closeout.
    with ExitStack() as resources:
        with _scraper_admission(database, require_inherited=True) as admitted:
            result, engine, binding, owner = apply_admitted(resources, tools, pins, qualification,
                                                             candidate, approval, admitted, database)
        from job_search_helper.release_controller import _finish_qualified_release_retry

        terminal = _finish_qualified_release_retry(engine, binding, result, qualification_owner=owner)
        summary = {key: terminal[key] for key in ('state', 'cycle_id', 'held') if key in terminal}
        if terminal['state'] == 'COMPLETE':
            summary['outcome_id'] = terminal['outcome']['outcome_id']
        print(json.dumps(summary, sort_keys=True))
        return 0 if terminal['state'] == 'COMPLETE' else 1


def apply_admitted(resources, tools, pins, qualification, candidate, approval, runtime, database):
    load_pinned_module('rejected_retry_plan', tools / 'rejected_retry_plan.py', pins['rejected_retry_plan.py'])
    recovery = load_pinned_module('recover_saved_retry', tools / 'recover_saved_retry.py',
                                  pins['recover_saved_retry.py'])
    from job_search_helper import cli
    from job_search_helper.engine import Engine, State
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.release_controller import _read_qualified_retry_intent, _require_qualified_retry
    from job_search_helper.release_qualification import open_release_qualification_owner
    from job_search_helper.sheet_profile import profile_schemas
    from job_search_helper.sqlite_repository import SQLiteRepository, timestamp

    path = Path(qualification['directory'])
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    resources.callback(os.close, descriptor)
    owner = resources.enter_context(open_release_qualification_owner(
        path, descriptor, expected_owner_identity=(qualification['device'], qualification['inode']),
        approved_receipt_sha256=qualification['receipt_sha256'],
    ))
    binding = _read_qualified_retry_intent(database, ATTEMPT)
    _require_qualified_retry(database, binding, owner)
    inbox_path = ROOT / 'inventories.sqlite3'
    jobs = cli.job_database_path()
    destination = InventoryInbox.destination_id(inbox_path)
    if (cli.state_path() != database or cli.storage_backend() != 'sqlite' or jobs != ROOT / 'jobs.sqlite3'
            or destination != approval['spreadsheet_id']
            or destination != os.environ.get('SPREADSHEET_ID', '').strip()):
        raise ValueError('The installed application destination differs from approval.')
    with cli.writer_lock(ROOT / 'writer.lock'):
        local = resources.enter_context(closing(SQLiteRepository(jobs, destination)))
        state = resources.enter_context(closing(State(database)))
        inbox = resources.enter_context(closing(InventoryInbox(inbox_path, destination)))
    engine = Engine(local, state, inbox=inbox, runtime_binding=runtime,
                    error_log_path=ROOT / 'errors.jsonl')

    def remote_factory():
        return nullcontext(cli.get_remote_repository(
            write=True, schemas=profile_schemas(local.get_meta('sheets_profile')), evidence_archives=False,
        ))

    result = recovery.recover_saved_retry_admitted(engine, binding, candidate, approval['saved_retry'],
                                                  qualification_owner=owner, remote_factory=remote_factory,
                                                  timestamp=timestamp())
    return result, engine, binding, owner


if __name__ == '__main__':
    raise SystemExit(main())
