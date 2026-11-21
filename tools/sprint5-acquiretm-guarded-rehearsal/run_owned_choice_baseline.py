"""Opt-in single Jetson choice for one pinned, application-owned replay."""
from contextlib import ExitStack, closing, contextmanager
from dataclasses import replace
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys


ROOT = Path('/tmp/jsh-s5-amphenol-owned-replay')
STAGE = Path('/tmp/jsh-s5-amphenol-receipt-choice.aH9Skdfa')
NATIVE = Path('/home/chris/job-search-helper_old/dev/wrapper-coder')
HISTORIC = Path('/tmp/jsh-s5-amphenol-recipe-choice-enum')
RECIPE_DIR = Path('/tmp/jsh-s5-acquiretm-membership-repair.20261121/repair_recipe')
HISTORIC_WITNESS = Path('/tmp/jsh-s5-amphenol-typed-live/result.json')
SUPPORT = Path('/tmp/jsh-s5-public-capture-transport-pin.Cp0PpA1z/capsule/support')
FIXTURE = ROOT / 'stores'
PREPARED_SHA = 'bb93a85d4d791901ad644c42fa2c1528be76108b5eaffc2e0b2b0132f2862df6'
HISTORIC_SHA = 'd10331c3e89b63ef00a8a26af7ac4c69f66beb95167e3b2005b4d9e101cd0602'
RECIPE_SHA = 'd6465801a0932a85895441914170d11e0258e642927f2d3349e2d044dfebc377'
CANDIDATE_SHA = '895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d'
TARGET = 'src/job_search_helper/acquiretm.py'
TEST = 'tests/test_acquiretm.py'
PROTOCOL = 'docs/wrapper-development-test-protocol.md'
OWNER_LANES = (NATIVE / 'tasks', HISTORIC / 'tasks',
               Path('/tmp/jsh-s5-amphenol-guided.dev/tasks'), Path('/tmp/jsh-s5-amphenol-recipe-choice/tasks'))
CATALOG_PINS = {
    'dev/wrapper-coder/tools': '3ec4c03fe71aaecdbd0d43a2b58f20a45088db2ff605613a849fa770af44d554',
    'src': 'c5bfd6432339f99b8dd84a78b8e59cb5fa33554572b10210a4e85e4b564af8d8',
    'tests': '75837865687f5f34f3e09c209cfe0379e556d650f9c5e406350e3523c5d095f1',
}
SELECTION_KEYS = ('cycle_id', 'request_id', 'company_event_id', 'source_revision', 'request_sha256', 'outcome_id')
CHOICE = {'summary': 'W1', 'next_action': 'listing_membership_change', 'outcome': 'phase_done'}
PROVENANCE = 'owned_disposable_stores_from_captured_public_pages_no_live_provider_or_workbook'
CHECKPOINT_CLOSING = {'role': 'user', 'content': (
    'Checkpoint now using worker_checkpoint. Describe completed work and the exact next action. '
    'No more source tools this session. If the next action is a permitted tool read or edit for the next session, '
    'use outcome continue; session closing is not a blocker. Use blocked only for unavailable external access '
    'or a required operator decision, and name that obstacle.'
)}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return sha256(data).hexdigest()


def plain(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and path.resolve() == path,
            f'File custody changed: {path.name}')
    return path


def pinned(path, expected):
    data = plain(path).read_bytes()
    require(digest(data) == expected, f'File pin changed: {path.name}')
    return data


def verify_catalogs():
    for relative, expected in CATALOG_PINS.items():
        base = STAGE / relative
        manifest = {}
        for path in sorted(base.rglob('*')):
            if '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            require(not path.is_symlink(), f'Link in source catalog: {path.name}')
            if path.is_file():
                manifest[path.relative_to(base).as_posix()] = digest(plain(path).read_bytes())
        wire = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
        require(digest(wire) == expected, f'Source catalog changed: {relative}')


def read_only(path):
    return sqlite3.connect(plain(path).as_uri() + '?mode=ro', uri=True, timeout=3)


@contextmanager
def retained_lock(path):
    fd = os.open(plain(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        check_lock(path, fd)
        yield path, fd
    finally:
        os.close(fd)


def check_lock(path, fd):
    opened, current = os.fstat(fd), plain(path).lstat()
    require((opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino),
            f'Lock custody changed: {path.name}')


def assert_idle(path, *, empty=False):
    with closing(read_only(path)) as db:
        db.execute('BEGIN')
        controls = {key: json.loads(value) for key, value in db.execute(
            "SELECT key,value FROM settings WHERE key IN ('queue_enabled','campaign_enabled','autopilot_enabled')")}
        require(controls.get('queue_enabled') is False and all(controls.get(key, False) is False for key in (
            'campaign_enabled', 'autopilot_enabled')), f'Scheduling controls are active: {path.parent}')
        require(not db.execute("SELECT 1 FROM tasks WHERE json_extract(state,'$.status') IN "
                               "('QUEUED','RUNNING','PAUSING') LIMIT 1").fetchone(), 'Another task is active.')
        require(not db.execute("SELECT 1 FROM inference_receipts WHERE status IN "
                               "('DISPATCHING','UNCERTAIN') LIMIT 1").fetchone(), 'Unsettled inference exists.')
        if empty:
            require(not db.execute('SELECT 1 FROM tasks LIMIT 1').fetchone()
                    and not db.execute('SELECT 1 FROM inference_receipts LIMIT 1').fetchone(),
                    'The replay receiver is no longer unused.')


def write_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def run_once():
    verify_catalogs()
    raw = pinned(ROOT / 'prepared-choice.json', PREPARED_SHA)
    prepared = json.loads(raw)
    require(prepared.pop('test_provenance') == PROVENANCE, 'Prepared provenance is not the controlled replay.')
    witness = pinned(HISTORIC_WITNESS, HISTORIC_SHA)
    recipe_file = RECIPE_DIR / 'acquiretm_membership_recipe.py'
    recipe_bytes = pinned(recipe_file, RECIPE_SHA)
    require(json.loads(prepared['messages'][1]['content'])['W1'] == json.loads(witness)['failure']['evidence'],
            'Owned W1 does not equal the historic compiler witness fields.')
    tools = STAGE / 'dev/wrapper-coder/tools'
    installed_libraries = NATIVE.parent.parent/'.venv/lib/python3.11/site-packages'
    sys.path[:0] = list(map(str, (tools, STAGE/'src', STAGE/'tests', SUPPORT,
                                 NATIVE/'tools/coordinator_vendor', installed_libraries)))
    import coding_tools as code
    import coordinator as existing
    import coordinator_budget as budget_runtime
    from amphenol_recipe_choice_input import prepare_choice_input
    from coordinator_baseline import files, verify
    from coordinator_store import Store
    from coordinator_workspace import workspace
    from test_amphenol_receipt_choice_input import _verified_readbacks

    class ReadOnlyStore(Store):
        def __init__(self, path):
            self.path = path

        @contextmanager
        def connect(self):
            with closing(read_only(self.path)) as db:
                yield db

    source_db = FIXTURE / 'coordinator/tasks.sqlite3'
    selection = {key: prepared['binding'][key] for key in SELECTION_KEYS}

    def owner_readback(path=source_db):
        current = _verified_readbacks(FIXTURE, ReadOnlyStore(path), selection)
        require(current is not None and prepare_choice_input(**current, enabled=True) == prepared,
                'Prepared input no longer matches the exact owner readback.')
        return current

    def current_revision(company_id):
        snapshot = owner_readback()['company']
        return snapshot['source_revision'] if company_id == snapshot['company_id'] else None

    with ExitStack() as locks:
        leases = [locks.enter_context(retained_lock(path)) for path in (
            FIXTURE/'scraper.lock', FIXTURE/'writer.lock')]

        def preflight():
            for path, fd in leases:
                check_lock(path, fd)
            for lane in OWNER_LANES:
                assert_idle(lane/'tasks.sqlite3')
            assert_idle(source_db, empty=True)
            require(pinned(ROOT/'prepared-choice.json', PREPARED_SHA) == raw, 'Prepared input drifted.')
            return owner_readback()

        current = preflight()
        budget_runtime._RESOURCE_DIR = NATIVE/'tools/resources/qwen35'
        measured = existing.estimate(prepared['messages'], prepared['tools'])
        require(measured.available_generation_tokens >= 1000, 'Installed tokenizer cannot fit the pinned choice.')

        run = ROOT / 'single-owned-choice-run'
        run.mkdir(mode=0o700)
        private_db = run/'tasks/tasks.sqlite3'
        private_db.parent.mkdir(mode=0o700)
        with closing(read_only(source_db)) as original, closing(sqlite3.connect(private_db)) as copy:
            original.backup(copy)
        require(owner_readback(private_db)['held'] == current['held'], 'Private held receipt differs from its owner.')

        queue_base = run/'queue-base'
        for name, pin in files(STAGE).items():
            target = queue_base/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(pinned(STAGE/name, pin))
        for filename, pin in (
            (PROTOCOL, '4c95994b3124f4c8b45cc4a7ba64b3f9777d6fce16d3403689b69a945a59a3c6'),
            ('pyproject.toml', '52b51a880ef0983d7ff1990df4e7ce1859adc8e341bb9638e262bbfedb89512c'),
        ):
            target = queue_base/filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(pinned(HISTORIC/'queue-base'/filename, pin))
        verify_catalogs()
        pinned(queue_base/'title-blacklist.txt', '10cd5b18b2bd72da4967bfc47221092b40fe5c301639991f4435aa91782bcc27')
        pinned(queue_base/'title-review-list.txt', '75987d1ab9d891b33ba0df8f49adbf742e5ceefa938bfc3a70b0d889cb4d2fed')
        pinned(queue_base/TARGET, 'a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61')
        pinned(queue_base/TEST, 'dca8d436b5c7840beecba2c14b6ffc01d4d279adab3a5fb5083d681713d891f1')
        code.BASE, code.ROOT, code.VENV = run, run/'repo', NATIVE.parent.parent/'.venv'
        existing.MAX_CALLS = 1
        [existing.CHECKPOINT_SCHEMA] = prepared['tools']
        answer = []
        attempted = False

        def bounded_budget(messages, offered):
            value = existing.estimate(messages, offered)
            return replace(value, available_generation_tokens=min(1000, value.available_generation_tokens))

        def infer(messages, offered, limit):
            nonlocal attempted
            preflight()
            verify_catalogs()
            verify(coordinator.store.get(task_id), code.root())
            require(not attempted and offered == prepared['tools']
                    and messages == [*prepared['messages'], CHECKPOINT_CLOSING] and 900 <= limit <= 1000,
                    'Reserved invocation differs from the one closed choice.')
            attempted = True
            reply = existing.infer(messages, offered, limit)
            answer.append(reply)
            return reply

        class ReplayChoice(existing.Coordinator):
            def messages(self, state, protocol):
                require((state['id'], state['mode'], state['phase']) == (task_id, 'review', 'inspect'),
                        'Task is outside the exact review/inspect scope.')
                return json.loads(json.dumps(prepared['messages']))

            def execute(self, state, name, args, names):
                require((state['phase'], name, args) == ('baseline', 'code_test', {'paths': TEST}),
                        'Replay choice permits only the normal offline baseline action.')
                return super().execute(state, name, args, names)

        proposal = {'source_revision': selection['source_revision'], 'mode': 'review', 'max_sessions': 1,
                    'objective': 'Choose the narrated W1 pagination strategy in tests/test_acquiretm.py.',
                    'integration': {'company_id': 'COMP-0490', 'company': 'Amphenol Aerospace', 'ats': 'AcquireTM',
                                    'configured_url': prepared['binding']['board'], 'tests': [TEST],
                                    'source_targets': [TARGET]}}
        coordinator = ReplayChoice(private_db.parent, model=infer, budget=bounded_budget,
                                   company_revision_resolver=current_revision,
                                   repair_profile_selector=lambda held: proposal if held == current['held'] else None)
        scheduler = coordinator._acquire_scheduler()
        try:
            with source_context(code, queue_base):
                result = coordinator.command({'action': 'prepare-held-repair', 'repair_key': current['held']['repair_key']})
            task_id = result['id']
            paused = coordinator.store.get(task_id)
            require(paused['status'] == 'PAUSED' and paused['stop_requested'] and paused['isolated_workspace']
                    and paused['repair_provenance']['outcome_id'] == selection['outcome_id'], 'Wrong promoted task.')
            write_new(run/'task-binding.json', {'task_id': task_id, 'prepared_sha256': PREPARED_SHA,
                                                'binding': prepared['binding'], 'provenance': PROVENANCE})
            preflight()
            token_path = run/'bridge-token'
            token_path.symlink_to(plain(NATIVE/'bridge-token'))
            try:
                coordinator.command({'action': 'pilot-start', 'id': task_id})
                claimed = coordinator.store.claim_pilot(task_id)
                require(claimed is not None, 'The existing pilot did not claim the exact task.')
                with workspace(coordinator.store, claimed):
                    coordinator._step(task_id)
                baseline = coordinator.store.get(task_id)
                require((baseline['phase'], baseline['status'], baseline['baseline_passed']) == ('inspect', 'QUEUED', True),
                        'The normal offline baseline did not authorize inspection.')
                state = coordinator.store.claim_pilot(task_id)
                require(state is not None and state['phase'] == 'inspect' and state['status'] == 'RUNNING',
                        'Inspection ownership was lost.')
                with workspace(coordinator.store, state):
                    coordinator.session(state)
            finally:
                if not coordinator.store.unresolved_inferences():
                    coordinator.store.stop_pilot()
                    coordinator.store.stop_at_boundary(task_id, 'Single replay choice has ended.')
                    token_path.unlink()
                coordinator.export(task_id)
        finally:
            coordinator._release_scheduler(scheduler)

        inference = coordinator.store.inference_receipts(task_id)
        final = coordinator.store.get(task_id)
        response = answer[0] if len(answer) == 1 else {}
        calls = response.get('message', {}).get('tool_calls', [])
        completed = (len(inference) == 1 and final['calls'] == 1 and inference[0]['status'] == 'COMPLETED'
                     and inference[0]['phase'] == 'inspect'
                     and inference[0]['prompt_digest'] == existing.inference_digest([*prepared['messages'], CHECKPOINT_CLOSING])
                     and inference[0]['tools_digest'] == existing.inference_digest(prepared['tools'])
                     and inference[0]['response_digest'] == existing.inference_digest(response))
        chosen = (completed and response.get('usage', {}).get('done_reason') != 'length' and len(calls) == 1
                  and calls[0]['function']['name'] == 'worker_checkpoint'
                  and calls[0]['function'].get('arguments') == CHOICE)
        receipt = {'task_id': task_id, 'task_state': final['status'], 'calls': final['calls'],
                   'status': 'CHOICE_ACCEPTED' if chosen else 'HELD_NO_VALID_CHOICE',
                   'prepared_sha256': PREPARED_SHA, 'owned_binding': prepared['binding'],
                   'historic_witness_sha256': HISTORIC_SHA, 'recipe_sha256': RECIPE_SHA,
                   'inference': [{k: item[k] for k in ('request_id', 'response_digest', 'status')} for item in inference]}
        write_new(run/'choice-receipt.json', receipt)
        if not chosen:
            return 2
        preflight()
        generated = materialize(run, queue_base, recipe_file, recipe_bytes, witness, receipt)
        write_new(run/'choice-proof.json', {
            'disposition': 'OWNED_REPLAY_CHOICE_ACCEPTED', 'prepared_sha256': PREPARED_SHA,
            'outcome_id': selection['outcome_id'], 'candidate_source_sha256': CANDIDATE_SHA,
            'model_response_sha256': inference[0]['response_digest'], 'test_provenance': PROVENANCE,
            'generated_source_path': str(generated),
        })
        print(generated, flush=True)
        return 0


@contextmanager
def source_context(code, path):
    token = code.WORKSPACE.set(path)
    try:
        yield
    finally:
        code.WORKSPACE.reset(token)


def materialize(run, baseline, recipe_file, recipe_bytes, witness, receipt):
    namespace = {}
    exec(compile(recipe_bytes, str(recipe_file), 'exec'), namespace)
    output = namespace['build'](plain(baseline/TARGET).read_bytes(),
                                {'strategy': CHOICE['next_action'], 'evidence': CHOICE['summary']}, witness)
    source = output['source'].encode()
    require(digest(source) == CANDIDATE_SHA, 'Reviewed recipe output changed.')
    candidate = run/'candidate'
    shutil.copytree(baseline, candidate)
    (candidate/TARGET).write_bytes(source)
    pinned(candidate/TARGET, CANDIDATE_SHA)
    (candidate/'reviewed.patch').write_text(output['diff'], encoding='utf-8')
    write_new(candidate/'build-receipt.json', {**output['receipt'], 'owned_binding': receipt['owned_binding'],
                                              'choice_receipt_sha256': digest((run/'choice-receipt.json').read_bytes())})
    return candidate/TARGET


if __name__ == '__main__':
    if sys.argv[1:] != ['--run-one-replay-choice']:
        raise SystemExit('Held by default. Explicit --run-one-replay-choice is required.')
    require(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode, 'Use system Python -I -S -B.')
    require(Path(__file__).resolve().parent == ROOT, 'Launch from the pinned private harness path.')
    os.umask(0o077)
    raise SystemExit(run_once())
