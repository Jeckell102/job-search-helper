"""Rehearse one app-owned event with captured pages and disposable stores."""
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

run = Path(__file__).resolve().parent
stage = Path('/tmp/jsh-s5-amphenol-receipt-choice.aH9Skdfa')
for location in (stage/'tests', stage/'src', stage/'dev/wrapper-coder/tools'):
    sys.path.insert(0, str(location))
import test_amphenol_receipt_choice_input as owner_fixture
import test_ordinary_event_no_publication as ordinary
from amphenol_recipe_choice_input import prepare_choice_input
from coordinator import Coordinator

raw = Path('/tmp/jsh-s5-amphenol-raw-fixture')
public = Path('/tmp/jsh-s5-amphenol-typed-live/result.json').read_bytes()
assert sha256(public).hexdigest() == 'd10331c3e89b63ef00a8a26af7ac4c69f66beb95167e3b2005b4d9e101cd0602'
manifest = (raw / 'result.json').read_bytes()
assert sha256(manifest).hexdigest() == 'acc0ba9b1fa8855dc588cc28d9911bf4ab6fa58816cba426e8ca9954437e4bdf'
snapshots = []
for record in json.loads(manifest)['snapshots']:
    body = (raw/record['file']).read_bytes()
    assert sha256(body).hexdigest() == record['sha256']
    snapshots.append(body.decode())
assert len(snapshots) == 4
witness = json.loads(public)['failure']['evidence']


class CapturedPage:
    def __init__(self, _):
        self.url = ordinary.SOURCE
        self.clock_ns = 0
        self.stage = 0
        self.waits = 0
        self.clicked = False

    def goto(self, url, **_):
        assert url == self.url
        self.stage = 0

    def content(self):
        body = snapshots[self.stage]
        if self.stage == 0:
            self.stage = 1
        return body

    def get_by_role(self, role, *, name, exact):
        assert (role, name, exact) == ('link', 'Go to page 2 of job results', True)
        def click(*, timeout):
            assert not self.clicked and self.stage == 1 and timeout == 8000
            self.clicked = True
        return SimpleNamespace(click=click)

    def wait_for_function(self, predicate, *, arg, timeout):
        assert self.clicked
        if self.waits == 0:
            assert 'document.body.innerHTML !== old' in predicate and arg == snapshots[1]
            self.clock_ns = witness['premature_elapsed_ms'] * 1_000_000
            self.stage = 2
        elif self.waits == 1:
            assert 'previous.has(id)' in predicate and len(set(arg['seen'])) == witness['first_page_count']
            self.clock_ns = witness['refreshed_elapsed_ms'] * 1_000_000
            self.stage = 3
        else:
            raise AssertionError('This test allows exactly two waits on one page click')
        self.waits += 1


class Output:
    def __init__(self):
        self.out = io.StringIO()
        self.err = io.StringIO()

    def readouterr(self):
        result = SimpleNamespace(out=self.out.getvalue(), err=self.err.getvalue())
        for stream in (self.out, self.err):
            stream.seek(0)
            stream.truncate(0)
        return result


root = run / 'stores'
root.mkdir(mode=0o700)
coordinator = Coordinator(base=root/'coordinator', model=Mock(side_effect=AssertionError('No model in preparation')))
coordinator.store.configure_queue(False)
receive = Mock(wraps=coordinator.command)


class InProcessDelivery(ordinary.OutcomeDelivery):
    def __init__(self, repository, sink):
        sink.ingest_immutable.side_effect = lambda record: receive({
            'action': 'ingest-scrape-outcome-delivery-v1', 'consumer': owner_fixture.CONSUMER, 'record': record,
        })['receipt']
        super().__init__(repository, sink)


out = Output()
with pytest.MonkeyPatch.context() as patch, redirect_stdout(out.out), redirect_stderr(out.err):
    patch.setattr(ordinary, 'OutcomeDelivery', InProcessDelivery)
    patch.setattr(ordinary, 'UpdatePanelPage', CapturedPage)
    ordinary.test_named_amphenol_pagination_settlement_is_exact_and_never_publishes(root, patch, out, 'owned')
receive.assert_called_once()
[held] = coordinator.store.held_repair_intake()
record = held['outcome']
identity = record['identity']
from contextlib import closing
from job_search_helper.company_events import _json_digest, read_verified_ordinary_event_admission
from job_search_helper.engine import State
from job_search_helper.sqlite_repository import SQLiteRepository
with (closing(State(str(root/'state.db'), readonly=True)) as state,
      closing(SQLiteRepository(root/'jobs.sqlite3', 'sheet', readonly=True)) as jobs):
    admission = read_verified_ordinary_event_admission(jobs, state, identity['cycle_id'])
request = admission['request']
selection = {**{k: identity[k] for k in ('cycle_id', 'request_id', 'company_event_id', 'source_revision')},
             'request_sha256': _json_digest(request), 'outcome_id': record['outcome_id']}
current = owner_fixture._verified_readbacks(root, coordinator.store, selection)
assert current is not None
assert prepare_choice_input(**current) is None
prepared = prepare_choice_input(**current, enabled=True)
assert prepared and json.loads(prepared['messages'][1]['content'])['W1'] == witness
assert (prepared['mode'],prepared['phase'],prepared['max_calls']) == ('review','inspect',1)
assert coordinator.store.all() == [] and coordinator.scheduler_thread is None
coordinator.model.assert_not_called()
prepared['test_provenance'] = 'owned_disposable_stores_from_captured_public_pages_no_live_provider_or_workbook'
encoded = json.dumps(prepared, sort_keys=True, indent=2) + '\n'
(run/'prepared-choice.json').write_text(encoded)
print('prepared proof', selection['outcome_id'], sha256(encoded.encode()).hexdigest())
