"""One-use baseline correction for Crown's exact pre-inference hold."""

from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
from shutil import copy2, copytree
import sqlite3
import time


TASK = 'WRAP-640c600390'
OUTCOME = 'OUT-5f5280ed5ac3c1db0b85a6c4'
REPAIR = '65790438527934f3e9e5d88dd024531a6f2671732d4d4e1dbfac2ebc78a38611'
BEFORE = '44d317f6ac920a55993c50343d8a423b745bf709682aff1d71d000c2e51fbffc'
RECEIPTS = 'fbb10c6652d2a3a3f8da6c0e398424a8a5904a132e455b946fbe4f3f21b44251'
OLD_BASELINE = '3cddf0386aa4547bf36d05bd0cecb0aeea62c3bdc2db7dce54ee113808d30e1d'
NEW_BASELINE = '81d33e14f5bdfe508d6533c0f5aff546a6cf1cf02df3b56730cbf635d35c183d'
OLD_HEAD = '96c16d4e8a0de995b4ef168b87bf15658b1c368f'
PROTOCOL = 'docs/wrapper-development-test-protocol.md'
PROTOCOL_PIN = '4c95994b3124f4c8b45cc4a7ba64b3f9777d6fce16d3403689b69a945a59a3c6'


def digest(raw):
    return sha256(raw if isinstance(raw, bytes) else raw.encode()).hexdigest()


def check_paused_owner(db):
    raw, = db.execute('SELECT state FROM tasks WHERE id=?', (TASK,)).fetchone()
    state = json.loads(raw)
    controls = dict(db.execute(
        "SELECT key,value FROM settings WHERE key IN "
        "('pilot_task','queue_enabled','campaign_enabled','autopilot_enabled')"
    ))
    other_work = db.execute(
        "SELECT 1 FROM tasks WHERE json_extract(state,'$.status') IN ('RUNNING','QUEUED','PAUSING') LIMIT 1"
    ).fetchone()
    inference = db.execute(
        "SELECT 1 FROM inference_receipts WHERE task=? OR status IN ('DISPATCHING','UNCERTAIN') LIMIT 1", (TASK,)
    ).fetchone()
    unfinished = db.execute("SELECT 1 FROM receipts WHERE result IS NULL LIMIT 1").fetchone()
    receipts = db.execute('SELECT * FROM receipts WHERE task=? ORDER BY id', (TASK,)).fetchall()
    owner = db.execute('SELECT outcome_id,status,task_id FROM repair_intake WHERE repair_key=?', (REPAIR,)).fetchone()
    delivery = db.execute(
        "SELECT sink_status FROM scrape_outcome_delivery_receipts WHERE outcome_id=?", (OUTCOME,),
    ).fetchone()
    if (digest(raw) != BEFORE or state['status'] != 'PAUSED_ERROR' or state['phase'] != 'inspect'
            or [state[key] for key in ('sessions', 'calls', 'tokens')] != [0, 0, 0]
            or not 0 <= time.time() - state['activated_at'] < 3600
            or json.loads(controls.get('pilot_task', 'null')) != TASK or controls.get('queue_enabled') != 'false'
            or controls.get('campaign_enabled', 'false') != 'false' or controls.get('autopilot_enabled', 'false') != 'false'
            or other_work or inference or unfinished
            or digest(json.dumps(receipts, separators=(',', ':'))) != RECEIPTS
            or owner != (OUTCOME, 'PROMOTED_PAUSED', TASK) or delivery != ('HELD_FOR_REPAIR_TRIAGE',)):
        raise ValueError('The original zero-inference Crown owner or its live budget changed.')
    return raw, state


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    sync_dir(path.parent)


def sync_dir(path):
    fd = os.open(path, os.O_DIRECTORY | os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def amend(task_folder, database, baseline):
    """Caller must hold the stopped coordinator's scheduler and supervision locks."""
    import coding_tools as code
    from coordinator_baseline import binding, files

    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        raw, state = check_paused_owner(db)

    repo = task_folder / 'repo'
    protocol = baseline / PROTOCOL
    original_manifest = state['assignment_baseline']['manifest']
    corrected = {**original_manifest, PROTOCOL: PROTOCOL_PIN}
    if (PROTOCOL in original_manifest or state['manifest'] != original_manifest
            or state['assignment_baseline']['digest'] != OLD_BASELINE
            or binding(corrected)['digest'] != NEW_BASELINE
            or files(baseline) != corrected or files(repo) != original_manifest
            or json.loads((repo / 'baseline-manifest.json').read_text()) != original_manifest
            or digest(protocol.read_bytes()) != PROTOCOL_PIN):
        raise ValueError('The paused Crown workspace does not match the approved one-file delta.')

    delta = task_folder / 'crown-protocol-correction'
    delta.mkdir(mode=0o700)
    old = delta / 'original-repo'
    staged = delta / 'corrected-repo'
    copytree(repo, staged)
    copy2(protocol, staged / PROTOCOL)
    token = code.WORKSPACE.set(staged)
    try:
        if (code.git('rev-parse', 'HEAD').strip() != OLD_HEAD
                or code.git('status', '--porcelain').strip() not in (
                    f'?? baseline-manifest.json\n?? {PROTOCOL}', f'?? {PROTOCOL}\n?? baseline-manifest.json')):
            raise ValueError('The Crown repository contains another edit.')
        code.git('add', '--', PROTOCOL)
        code.git('commit', '--quiet', '-m', 'Add the approved host-owned development protocol')
        if code.git('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').strip() != PROTOCOL:
            raise ValueError('The corrected Git baseline added unexpected content.')
        new_head = code.git('rev-parse', 'HEAD').strip()
    finally:
        code.WORKSPACE.reset(token)
    path = staged / 'baseline-manifest.json'
    path.unlink()
    save(path, corrected)
    if files(staged) != corrected:
        raise ValueError('Corrected workspace files changed during preparation.')

    update = {**state, 'assignment_baseline': binding(corrected), 'manifest': corrected}
    updated_raw = json.dumps(update)
    intent = {'task_id': TASK, 'outcome_id': OUTCOME, 'prior_state_sha256': BEFORE,
              'corrected_state_sha256': digest(updated_raw), 'prior_git_head': OLD_HEAD,
              'corrected_git_head': new_head, 'protocol_sha256': PROTOCOL_PIN,
              'activation_preserved': state['activated_at']}
    save(delta / 'intent.json', intent)
    with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True)) as db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        if check_paused_owner(db)[0] != raw:
            raise ValueError('The paused Crown task changed before the exact update.')
        swapped = False
        try:
            repo.rename(old)
            try:
                staged.rename(repo)
            except BaseException:
                old.rename(repo)
                raise
            swapped = True
            sync_dir(task_folder)
            sync_dir(delta)
            changed = db.execute('UPDATE tasks SET state=? WHERE id=? AND state=?', (updated_raw, TASK, raw))
            if changed.rowcount != 1:
                raise ValueError('The exact Crown task update was not applied.')
            db.commit()
        except BaseException:
            db.rollback()
            if swapped and db.execute('SELECT state FROM tasks WHERE id=?', (TASK,)).fetchone() == (raw,):
                repo.rename(staged)
                old.rename(repo)
                sync_dir(task_folder)
                sync_dir(delta)
            raise
    save(delta / 'receipt.json', {**intent, 'state': 'CROWN_PROTOCOL_BASELINE_CORRECTED'})
    return intent


def settle_interruption(task_folder, database, *, allow_restore=False):
    """Restore an uncommitted copy or recognize the committed correction."""
    import coding_tools as code
    from coordinator_baseline import files

    delta = task_folder / 'crown-protocol-correction'
    repo = task_folder / 'repo'
    old = delta / 'original-repo'
    staged = delta / 'corrected-repo'
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        raw, = db.execute('SELECT state FROM tasks WHERE id=?', (TASK,)).fetchone()
    state = json.loads(raw)
    expected = state['assignment_baseline']['manifest']
    before = digest(raw) == BEFORE
    intent_path = delta / 'intent.json'
    intent = json.loads(intent_path.read_text()) if intent_path.is_file() else None

    def exact_checkout(path, head):
        if path.is_symlink() or not path.is_dir() or files(path) != expected:
            return False
        if json.loads((path / 'baseline-manifest.json').read_text()) != expected:
            return False
        token = code.WORKSPACE.set(path)
        try:
            return code.git('rev-parse', 'HEAD').strip() == head
        finally:
            code.WORKSPACE.reset(token)

    if before:
        if exact_checkout(repo, OLD_HEAD):
            return 'ORIGINAL'
        if not allow_restore:
            raise ValueError('The original workspace must be inspected while the wrapper is stopped.')
        if intent is None or intent['prior_state_sha256'] != BEFORE or not exact_checkout(old, OLD_HEAD):
            raise ValueError('Uncommitted correction has no exact original workspace to restore.')
        if repo.exists():
            if staged.exists() or files(repo) != {**expected, PROTOCOL: PROTOCOL_PIN}:
                raise ValueError('Unexpected workspace during correction rollback.')
            repo.rename(staged)
        old.rename(repo)
        sync_dir(task_folder)
        sync_dir(delta)
        return 'ORIGINAL'
    if (intent is not None and intent['task_id'] == TASK and intent['outcome_id'] == OUTCOME
            and digest(raw) == intent['corrected_state_sha256']
            and state['assignment_baseline']['digest'] == NEW_BASELINE
            and exact_checkout(repo, intent['corrected_git_head'])):
        return 'CORRECTED'
    raise ValueError('The task and workspace do not identify one exact recovery side.')
