from contextlib import closing
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from shutil import copy2, copytree
import sys
from tempfile import mkdtemp
from unittest.mock import Mock, patch

from coordinator import Coordinator
from job_search_helper.engine import State
from job_search_helper.scrape_outcome_delivery import CONSUMER
from job_search_helper import scrape_outcome_delivery
from job_search_helper.sqlite_repository import SQLiteRepository


def guard(event, _):
    if event.startswith(('socket.connect', 'socket.getaddrinfo', 'socket.bind', 'socket.gethostbyname')):
        raise RuntimeError('offline fixture forbids network')


sys.addaudithook(guard)
with patch.object(Path, 'read_text', return_value='fixture-token'):
    from host_server import AmphenolRecipeEnrollment

SOURCE = Path('/tmp/jsh-s5-closeout-independent.vw980gx4/run/test_saved_publication0')
REHEARSAL = Path('/tmp/jsh-s5-amphenol-publication-rehearsal')
ORIGINAL = Path('/tmp/jsh-s5-amphenol-owned-replay/stores/coordinator/tasks.sqlite3')


def setup(kind):
    root = Path(mkdtemp(prefix=kind + '-', dir=Path(__file__).parent))
    app = root / 'application'
    app.mkdir()
    for name in ('state.db', 'jobs.sqlite3', 'inventories.sqlite3', 'integration-release-journal.json', 'last-scan-request.json'):
        copy2(SOURCE / name, app / name)
    for name in ('repair-retry', 'company-event-bridge', 'ordinary-event-inventory'):
        copytree(REHEARSAL / 'test-project/.state' / name, app / name)
    owner = root / 'qualification'
    copytree(REHEARSAL / 'fixture-qualification-owner', owner)
    copytree(REHEARSAL / 'records', root / 'records')
    path = app / 'integration-release-journal.json'
    journal = json.loads(path.read_bytes())
    journal['record'] = str(root / 'records' / journal['release_id'])
    path.write_text(json.dumps(journal))
    qualification = owner / (journal['release_id'] + '.json')
    identity = owner.stat()
    receiver = root / 'coordinator'
    receiver.mkdir()
    copy2(ORIGINAL, receiver / 'tasks.sqlite3')
    co = Coordinator(receiver, model=Mock(side_effect=AssertionError('no fixture model')))
    with closing(SQLiteRepository(app/'jobs.sqlite3', 'sheet', readonly=True)) as jobs:
        [origin] = [o for o in jobs.scrape_outcomes() if o['outcome'] == 'QUALIFIED_INTEGRATION_REPAIR']
        [retry] = [o for o in jobs.scrape_outcomes() if o['outcome'] == 'COMPLETE']
    scope = origin['identity']
    enrolled = AmphenolRecipeEnrollment.from_process_environment({
        'WRAPPER_AMPHENOL_RECIPE_ENROLLMENT': json.dumps({
            key: scope[key] for key in ('company_event_id','request_id','source_revision')}),
        'WRAPPER_AMPHENOL_RETRY_APPROVAL': json.dumps({
            'release_id':journal['release_id'], 'directory':str(owner), 'device':identity.st_dev,
            'inode':identity.st_ino, 'receipt_sha256':sha256(qualification.read_bytes()).hexdigest()}),
    })
    return app, co, enrolled, retry


def tick(app, co, enrolled):
    with patch.dict(os.environ, {'JOB_STORAGE_BACKEND':'sqlite', 'STATE_DB_FILE':str(app/'state.db'),
                                 'JOB_DB_FILE':str(app/'jobs.sqlite3'), 'SPREADSHEET_ID':'sheet'}):
        with patch('host_server.JOB_SEARCH_ROOT', app):
            return enrolled.catch_up(co)


def duplicate():
    app, co, enrolled, retry = setup('duplicate')
    with closing(State(app/'state.db')) as state:
        exact = state.cycle(retry['identity']['cycle_id'])
        state.save_cycle({**exact, 'id': 'CYC-DDDDDDDDDDDD'})
    observed = tick(app, co, enrolled)
    print('duplicate State retry:', observed['state'])
    if observed['state'] == 'RECIPE_RETRY_CONFIRMED':
        assert len(co.store.retry_lifecycle(retry['identity']['attempt_id'])['events']) == 1
    return observed['state']


def lost_response():
    app, co, enrolled, retry = setup('lost-response')
    command = co.command
    deliveries = []
    clock = [datetime.now().timestamp()]

    class FixtureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(clock[0], tz)

    def response(request):
        reply = command(request)
        if request.get('action') == 'ingest-scrape-outcome-delivery-v1':
            assert request['record'] == retry
            deliveries.append(reply['receipt'])
            if len(deliveries) == 1:
                raise TimeoutError('receiver committed before fixture response was lost')
        return reply

    co.command = response
    with patch.object(scrape_outcome_delivery, 'datetime', FixtureClock):
        assert tick(app, co, enrolled)['state'] == 'HELD_EXACT_RETRY_TERMINAL'
        assert len(co.store.retry_lifecycle(retry['identity']['attempt_id'])['events']) == 1
        assert tick(app, co, enrolled)['state'] == 'HELD_EXACT_RETRY_TERMINAL' and len(deliveries) == 1
        clock[0] += 1000
        terminal = tick(app, co, enrolled)
        assert terminal['state'] == 'RECIPE_RETRY_CONFIRMED'
        assert deliveries == [deliveries[0], deliveries[0]]
        assert tick(app, co, enrolled) == terminal and len(deliveries) == 2
        assert len(co.store.retry_lifecycle(retry['identity']['attempt_id'])['events']) == 1
    co.model.assert_not_called()
    print('receiver-commit response loss: hold, no early replay, one lifecycle, exact receipt reconfirmed')


if __name__ == '__main__':
    assert duplicate() == 'HELD_EXACT_RETRY_TERMINAL'
    lost_response()
