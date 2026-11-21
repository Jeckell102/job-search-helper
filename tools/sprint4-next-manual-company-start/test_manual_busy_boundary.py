"""Boundary proof: an event arriving during a prior cycle waits for next start."""

from contextlib import closing
import sys

import pytest

from job_search_helper import ats, cli, scrape_first_pass
from job_search_helper.company_events import BRIDGE_CONSUMER, _json_digest
from job_search_helper.engine import Engine, State
from job_search_helper.repository import GoogleRepository
from job_search_helper.sheet_profile import COMPACT_SCHEMAS
from sheets_fixture import RangeSheets

from test_manual_company_start import add_company, manual


def _close_fixture_cycle(repository, database, cycle_id):
    """Make only the separately-created fixture cycle terminal."""
    with closing(State(database)) as state:
        engine = Engine(repository, state)
        cycle = state.cycle(cycle_id)
        assert cycle is not None and cycle['status'] == 'In Progress'
        for item in cycle['companies'].values():
            item['stage'] = 'complete'
        engine._sync_cycle(cycle)
        assert state.cycle(cycle_id)['status'] == 'Complete'


def test_event_arriving_during_busy_cycle_waits_then_settles_on_one_next_manual_start(
        manual, monkeypatch, capsys):
    root, repository, launch = manual

    # This is an ordinary prior cycle, not a surrogate event cycle.  Its outbox
    # event is deliberately acknowledged so only the later Company is pending.
    old_event = add_company(repository, 1)
    repository.acknowledge_company_event(
        old_event['event_id'], BRIDGE_CONSUMER,
        source_revision=old_event['source_revision'],
    )
    with closing(State(root / 'state.db')) as state:
        old_cycle = Engine(repository, state).start_cycle(
            company_ids=[old_event['company_id']])

    event = add_company(repository, 2)
    original_event = dict(event)
    assert repository.pending_latest_company_events(BRIDGE_CONSUMER) == [original_event]
    assert not (root / 'next-scan.json').exists()

    # A normal manual start must neither enter the broad factory nor consume
    # the new event while the unrelated earlier cycle remains active.
    monkeypatch.setattr(scrape_first_pass, 'main', lambda *args: pytest.fail('entered broad scan'))
    assert launch() == 1
    held = capsys.readouterr().out
    assert 'HELD_MANUAL_EVENT_BRIDGE' in held
    assert 'WAITING_FOR_UNFINISHED_CYCLE' in held
    assert repository.pending_latest_company_events(BRIDGE_CONSUMER) == [original_event]
    assert not (root / 'next-scan.json').exists()
    with closing(State(root / 'state.db', readonly=True)) as state:
        assert state.cycle(old_cycle)['status'] == 'In Progress'
        assert len(state.cycles()) == 1

    _close_fixture_cycle(repository, root / 'state.db', old_cycle)

    sheet = RangeSheets({'Companies': repository.read('Companies')}, schemas=COMPACT_SCHEMAS)
    remote = GoogleRepository(sheet, repository.spreadsheet_id, schemas=COMPACT_SCHEMAS,
                              min_request_interval=0)
    fetches = []

    def provider(ats_name, board, company_id, _name):
        fetches.append(company_id)
        assert ats_name == 'Greenhouse'
        assert board == 'https://boards.greenhouse.io/manual-fixture'
        assert company_id == event['company_id']
        return ats.Inventory(
            'complete',
            source_url='https://boards-api.greenhouse.io/v1/boards/manual-fixture/jobs',
            ats='Greenhouse',
            verified_zero='greenhouse_explicit_total_zero',
        )

    monkeypatch.setattr(ats, 'fetch_inventory', provider)
    monkeypatch.setattr(cli, 'get_remote_repository', lambda *, write, **kwargs: (
        remote if write is False else pytest.fail('opened a writable workbook')))

    # The next single manual start consumes precisely the retained event and
    # reaches real ordinary verified-zero publication without a broad scan.
    assert launch() == 0
    assert 'VERIFIED_ZERO' in capsys.readouterr().out
    assert fetches == [event['company_id']]
    assert sheet.batches == []
    assert not (root / 'next-scan.json').exists()
    assert repository.pending_latest_company_events(BRIDGE_CONSUMER) == []
    [outcome] = repository.scrape_outcomes(company_id=event['company_id'])
    assert outcome['outcome'] == 'COMPLETE'
    assert outcome['action'] == 'save_without_repair'
    assert outcome['identity']['request_id'] == 'company-event:' + event['event_id']
    with closing(State(root / 'state.db', readonly=True)) as state:
        cycles = state.cycles()
        assert [cycle['id'] for cycle in cycles[:1]] == [old_cycle]
        assert cycles[0]['status'] == 'Complete'
        assert len(cycles) == 2
        assert cycles[1]['company_event']['event_id'] == event['event_id']
        assert set(cycles[1]['companies']) == {event['company_id']}
