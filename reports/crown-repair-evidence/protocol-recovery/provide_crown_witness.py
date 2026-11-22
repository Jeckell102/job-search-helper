"""Supply verified Crown evidence through the coordinator's operator guidance field."""

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
import time


TASK = 'WRAP-640c600390'
OUTCOME = 'OUT-5f5280ed5ac3c1db0b85a6c4'
GUIDANCE = (
    'MuleLab independently captured the exact Crown SuccessFactors search page and '
    'https://us-careers.crown.com/sitemap.xml. The search has 100 distinct visible job '
    'IDs and no count or pagination controls. The employer sitemap had 535 distinct '
    'same-host canonical jobs, and all visible IDs were present. The sitemap contains '
    'the standard /job/ path plus /TheGoods/job/ and /17West/job/; exact canonical '
    'details and full descriptions were verified for one sample in each section. '
    'That proves the search excerpt is incomplete. Treat the saved evidence as the '
    'basis for the repair plan; do not request another operator scrape for this '
    'inspection. The synthetic test is intentionally offline and must pass before '
    'separate full live qualification. Checkpoint a concrete Crown-only plan: read '
    'official sitemap membership before and after detail fetches, preserve exact '
    'Crown URL and unique IDs plus every full canonical description, retain partial '
    'status for any mismatch, and preserve all other tenants. Do not hardcode counts.'
)


def update(database):
    from coordinator_identity import validate_bound_identity

    with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True)) as db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        raw, = db.execute('SELECT state FROM tasks WHERE id=?', (TASK,)).fetchone()
        state = json.loads(raw)
        validate_bound_identity(state)
        controls = dict(db.execute(
            "SELECT key,value FROM settings WHERE key IN ('queue_enabled','campaign_enabled','pilot_task')"
        ))
        if (state['status'] != 'PAUSED_BLOCKED' or state['phase'] != 'inspect'
                or state['repair_provenance']['outcome_id'] != OUTCOME
                or state['repair_provenance']['company_id'] != 'COMP-0588'
                or state['calls'] != 3 or state['sessions'] != 1
                or not state['activated_at'] < time.time() < state['activated_at'] + 3600
                or controls != {'queue_enabled': 'false', 'campaign_enabled': 'false', 'pilot_task': json.dumps(TASK)}
                or db.execute("SELECT 1 FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN') LIMIT 1").fetchone()
                or db.execute("SELECT COUNT(*) FROM inference_receipts WHERE task=? AND status='COMPLETED'", (TASK,)).fetchone() != (3,)
                or db.execute("SELECT 1 FROM receipts WHERE task=? AND name IN ('code_edit','code_create','code_commit','code_rollback') LIMIT 1", (TASK,)).fetchone()
                or db.execute("SELECT 1 FROM receipts WHERE task=? AND result IS NULL LIMIT 1", (TASK,)).fetchone()):
            raise ValueError('Crown no longer matches the settled inspection checkpoint.')
        workflow = state['workflow']
        current = workflow.get('operator_guidance')
        if current not in (None, GUIDANCE):
            raise ValueError('Existing Crown operator guidance differs.')
        updated = {**state, 'workflow': {**workflow, 'operator_guidance': GUIDANCE}}
        validate_bound_identity(updated)
        if current != GUIDANCE:
            changed = db.execute('UPDATE tasks SET state=? WHERE id=? AND state=?', (json.dumps(updated), TASK, raw))
            if changed.rowcount != 1:
                raise ValueError('The exact Crown task could not be updated.')
        db.commit()
    return {'task_id': TASK, 'outcome_id': OUTCOME, 'state': 'CROWN_WITNESS_SUPPLIED',
            'guidance_sha256': sha256(GUIDANCE.encode()).hexdigest(), 'prior_state_sha256': sha256(raw.encode()).hexdigest()}


if __name__ == '__main__':
    if not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.pycache_prefix != '/dev/null':
        raise ValueError('Use the isolated production Python without bytecode.')
    wrapper = Path('/home/chris/job-search-helper_old/dev/wrapper-coder')
    sys.path.insert(0, str(wrapper / 'tools'))
    print(json.dumps(update(wrapper / 'tasks/tasks.sqlite3'), sort_keys=True))
