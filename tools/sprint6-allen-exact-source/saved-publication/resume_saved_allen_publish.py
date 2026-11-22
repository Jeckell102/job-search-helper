"""Resume the one saved Allen publication with its reviewed status-field correction."""

import argparse
import ast
from contextlib import closing
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys


PROJECT = Path('/home/chris/job-search-helper_old')
ROOT = PROJECT / '.state'
SAVED_FIX = Path('/tmp/jsh-s6-allen-publish.Ha9WnPpI/src/job_search_helper/sheets_sync.py')
BASE_PIN = '8202aa448b01b98af90a2ea3a088dc9f9cc1e3f47fa05a3c273afd9e1150ea9f'
FIX_PIN = 'f3de38a8e59a384e38009ba6b114869ffc94b4dd508bbc7fb657b47b2ffcb60d'
RELEASE = 'REL-d37d7d64a0fd3788e02e699f'
COMPANY = 'COMP-0164'
CYCLE = 'CYC-93DE6012E332'
EVENT = 'CEV-6e7076066ca6446bb596540f437e81bd'
SOURCE = '40cc3585c1afa64c33f04a00cb77bdf6e1f53b006156ad7dfedd24a29ca9bc54'
REQUEST_SHA = '4e3be336ac684871cbc7f4fe696cb666927d83c9ef8a766b54a4cbbe233f6231'
PLAN = '899f83a758529d9e0b280c098b8a6ee9d539d91a724e1f286ba8f93065a4844c'


def checked_tree(path, pin):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != pin:
        raise ValueError('An approved publisher image has changed.')
    return ast.parse(raw, filename=str(path))


def exact_method(tree):
    [owner] = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'SheetsSynchronizer']
    [method] = [node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == '_plan_exact_row']
    return method


def checked_method(publisher):
    installed = checked_tree(Path(publisher.__file__), BASE_PIN)
    corrected = checked_tree(SAVED_FIX, FIX_PIN)
    method = exact_method(installed)
    [status] = [node for node in ast.walk(method) if isinstance(node, ast.Set)
                and [elt.value if isinstance(elt, ast.Constant) else None for elt in node.elts]
                == ['Last Checked', 'Next Action']]
    status.elts.insert(1, ast.Constant('Last Scan Result'))
    if ast.dump(installed) != ast.dump(corrected):
        raise ValueError('The reviewed publisher must differ by only the exact scan-result field.')
    namespace = dict(vars(publisher))
    function = ast.Module(body=[exact_method(corrected)], type_ignores=[])
    exec(compile(function, str(SAVED_FIX), 'exec'), namespace)
    return namespace['_plan_exact_row']


def require_saved_cut(reader, state, runtime, inbox_path):
    from job_search_helper.exact_cycle_planner import _exact_plan_digest
    from job_search_helper.exact_cycle_receipt import load_ordinary_event_plan_context, ordinary_event_receipt_binding
    from job_search_helper.inbox import InventoryInbox

    with closing(InventoryInbox(inbox_path, reader.spreadsheet_id, readonly=True)) as inbox:
        context = load_ordinary_event_plan_context(reader, state, runtime, cycle_id=CYCLE, request_sha256=REQUEST_SHA)
        payload, blocked = inbox.get(CYCLE, COMPANY)
        plan, cursor = inbox.plan(CYCLE, COMPANY)
        binding = ordinary_event_receipt_binding(state.cycle(CYCLE), COMPANY, payload, context)
        application = reader.db.execute('SELECT plan_digest,state FROM exact_local_applications '
                                        'WHERE cycle=? AND company=?', (CYCLE, COMPANY)).fetchone()
        local = inbox.exact_local_state(CYCLE, COMPANY)
        if (blocked or binding.get('company_event_id') != EVENT or binding.get('source_revision') != SOURCE
                or plan.get('plan_digest') != PLAN or _exact_plan_digest(plan) != PLAN
                or plan.get('ordinary_company_event') != binding
                or cursor != len(plan['local_operations']) or application != (PLAN, 'VERIFIED')
                or local is None or local.get('state') != 'LOCAL_VERIFIED' or local.get('plan_digest') != PLAN
                or inbox.exact_remote_state(CYCLE, COMPANY) is not None):
            raise ValueError('The saved Allen publication is not in its exact pre-write state.')
        [operation] = [item for item in plan['remote_projection'] if item['tab'] == 'Companies']
        if (operation['identity'] != {'Company ID': COMPANY}
                or set(operation['values']) != {'Last Checked', 'Last Scan Result', 'Next Action'}
                or operation['append_if_missing'] or operation['on_insert'] or operation['append_notes']):
            raise ValueError('The frozen Allen Company status update does not match the reviewed scope.')


def publish(runtime, execute):
    from job_search_helper import ordinary_company_event_command as ordinary, sheets_sync
    from job_search_helper.cli import writer_lock
    from job_search_helper.engine import State
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.sqlite_repository import SQLiteRepository

    method = checked_method(sheets_sync)
    database, jobs, inbox_path = (ROOT / name for name in ('state.db', 'jobs.sqlite3', 'inventories.sqlite3'))
    if not execute:
        with (writer_lock(ROOT / 'writer.lock'),
              closing(SQLiteRepository(jobs, InventoryInbox.destination_id(inbox_path), readonly=True)) as reader,
              closing(State(str(database), readonly=True)) as state):
            require_saved_cut(reader, state, runtime, inbox_path)
        return {'state': 'SAVED_ALLEN_READY', 'cycle_id': CYCLE, 'plan_digest': PLAN}

    usual_plan_row = sheets_sync.SheetsSynchronizer._plan_exact_row
    usual_preflight = ordinary._publish_preflight

    def checked_preflight(local, state, actual_runtime, cycle, admission, path):
        if (cycle.get('id') != CYCLE or admission.get('request_sha256') != REQUEST_SHA
                or actual_runtime != runtime or path != inbox_path):
            raise ValueError('The saved Allen publication owner changed.')
        require_saved_cut(local, state, actual_runtime, path)
        return usual_preflight(local, state, actual_runtime, cycle, admission, path)

    ordinary._publish_preflight = checked_preflight
    sheets_sync.SheetsSynchronizer._plan_exact_row = method
    try:
        return ordinary.execute_ordinary_event('publish', (database, jobs, runtime),
                                               request_sha256=REQUEST_SHA, cycle_id=CYCLE)
    finally:
        ordinary._publish_preflight = usual_preflight
        sheets_sync.SheetsSynchronizer._plan_exact_row = usual_plan_row


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('action', choices=('verify', 'publish'))
    arguments = parser.parse_args()
    if not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.pycache_prefix != '/dev/null':
        raise ValueError('Use the installed isolated release Python.')
    sys.path[:0] = [str(PROJECT), str(PROJECT / 'src')]
    from release_admission_bootstrap import _load_environment, _validate_runtime

    _load_environment(PROJECT / '.env')
    path = ROOT / 'scraper.lock'
    with os.fdopen(os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as guard:
        info = os.fstat(guard.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not os.path.samestat(info, path.stat(follow_symlinks=False))):
            raise ValueError('Allen admission does not identify the normal scraper lock.')
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        runtime = _validate_runtime(PROJECT, ROOT)
        if (runtime['state'] != 'COMPLETE' or runtime['release_id'] != RELEASE
                or Path(sys.prefix).resolve() != PROJECT / '.venv'):
            raise ValueError('The frozen Allen runtime is not active.')
        result = publish(runtime, arguments.action == 'publish')
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get('state') in {'SAVED_ALLEN_READY', 'SYNC_CONFIRMED'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
