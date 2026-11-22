"""Deliver only the deployed GA-ASI hold through the existing local receipt bridge."""

from contextlib import closing
import json
from pathlib import Path
import sys

PROJECT = Path('/home/chris/job-search-helper_old')
TOOLS = PROJECT / 'dev/wrapper-coder/tools'
TASKS = TOOLS.parent / 'tasks'
ROOT = PROJECT / '.state'
OUTCOME = 'OUT-9cea60b9d3b2cb0c215ec478'
REQUEST = 'operator-scope-hold:gaasi-sprint6-20261122'
PIN = '7b818ae9d05feb7b261147ccfc7f456f0c05c0f4b44e0e5044a8038573e57227'
RELEASE = 'REL-bc64482443373843f2f93cb5'
sys.path[:0] = [str(TOOLS), str(PROJECT / 'src'), str(PROJECT)]
from coordinator import Coordinator
from coordinator_receipt_host_bridge import ManualReceiptV1HostBridge
from job_search_helper.cli import load_environment, writer_lock
from job_search_helper.inbox import InventoryInbox
from job_search_helper.integration_release import assert_release_settled
from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held
from job_search_helper.sqlite_repository import SQLiteRepository


def forbidden(*args, **kwargs):
    raise RuntimeError('This hold may not start inference or estimate a repair.')


load_environment(PROJECT / '.env')
with writer_lock(ROOT / 'scraper.lock'), writer_lock(ROOT / 'writer.lock'):
    if assert_release_settled(ROOT).get('release_id') != RELEASE or (ROOT / 'next-scan.json').exists():
        raise ValueError('The scoped delivery requires the installed GA release and a settled queue.')
    assert_normal_lifecycle_not_held(ROOT, ROOT / 'jobs.sqlite3')
    destination = InventoryInbox.destination_id(ROOT / 'inventories.sqlite3')
    with closing(SQLiteRepository(ROOT / 'jobs.sqlite3', destination)) as repository:
        proof = repository.db.execute(
            'SELECT outcome_id FROM operator_company_scope_holds WHERE request_id=? AND request_sha256=?',
            (REQUEST, PIN),
        ).fetchone()
        found = repository.db.execute('SELECT request_id,company_id,outcome FROM scrape_outcomes WHERE outcome_id=?',
                                      (OUTCOME,)).fetchone()
        if proof != (OUTCOME,) or found != (REQUEST, 'COMP-0072', 'BLOCKED'):
            raise ValueError('The exact GA-ASI hold proof is missing.')
        coordinator = Coordinator(base=TASKS, model=forbidden, budget=forbidden)
        result = ManualReceiptV1HostBridge(coordinator, lambda: repository, enabled=True).manual_drain(
            outcome_id=OUTCOME)
        if result.get('results') != [{'outcome_id': OUTCOME, 'disposition': 'ACCEPTED'}]:
            raise ValueError('The named outcome did not settle with an accepted receipt.')
        print(json.dumps(result, sort_keys=True))
