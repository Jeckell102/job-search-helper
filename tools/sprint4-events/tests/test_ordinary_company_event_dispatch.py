"""Offline dispatcher composition with the real guarded command and stores."""
from contextlib import closing
import json

import pytest

from job_search_helper import ats, cli
from job_search_helper import ordinary_company_event_command as command
from job_search_helper.company_events import _json_digest, read_verified_queued_event
from job_search_helper.company_intake_dispatcher import CompanyIntakeDispatcher
from job_search_helper.scan_request import request_fingerprint
from job_search_helper.sqlite_repository import SQLiteRepository
from test_ordinary_company_event_command import execute, queued
from test_ordinary_company_event_fetch import OBSERVED


def test_enabled_dispatch_admits_once_and_hands_off_exact_publish(queued):
    paths, request, digest, provider, factory, remote, _ = queued
    root = paths[0].parent
    calls = []

    def child(arguments):
        calls.append(arguments)
        # A second supervisor entering during the first callback sees the
        # committed claim before the provider or process can run.
        interim = CompanyIntakeDispatcher(local, root, child_runner=never_child).run_once()
        assert interim['state'] == 'HELD_ORDINARY_ADMIT_FETCH'
        assert arguments[1:] == ('ordinary-company-event', 'admit-fetch', '--request-sha256', digest)
        assert execute(queued)['state'] == 'INVENTORY_FROZEN'
        return 0

    def never_child(arguments):
        pytest.fail(f'duplicate or broad launch: {arguments!r}')

    with closing(SQLiteRepository(paths[1], 'sheet', readonly=True)) as local:
        dispatcher = CompanyIntakeDispatcher(local, root, child_runner=child)
        # A watch tick passes writable Jobs to the existing bridge. Scope this
        # fixture's backlog to its already materialized verified request.
        assert dispatcher.run_once()['state'] == 'DISABLED'
        assert dispatcher.reconcile_ordinary()['state'] == 'DISABLED'
    with closing(SQLiteRepository(paths[1], 'sheet')) as local:
        dispatcher = CompanyIntakeDispatcher(local, root, child_runner=child)
        dispatcher.set_enabled(True)
        assert not dispatcher.retained_enabled() and not dispatcher.temporary_retry_enabled()
        with cli.writer_lock(root / 'scraper.lock'):
            assert dispatcher.run_once()['state'] == 'HELD_BRIDGE_BOUNDARY'
        assert calls == []
        assert dispatcher.run_once()['state'] == 'ORDINARY_CHILD_RETURNED'
        supervisor = CompanyIntakeDispatcher(local, root, child_runner=never_child)
        pending = supervisor.run_once()
        assert pending['state'] == 'HELD_ORDINARY_PUBLICATION'
        cycle_id = pending['cycle_id']
        assert pending['continuation'][1:] == (
            'ordinary-company-event', 'publish', '--request-sha256', digest, '--cycle-id', cycle_id,
        )
        assert supervisor.status()['dispatches'] == {'ORDINARY_ADMITTED': 1}
        assert supervisor.status()['ordinary_handoff']['cycle_id'] == cycle_id
        with closing(SQLiteRepository(paths[1], 'sheet', readonly=True)) as reader:
            observer = CompanyIntakeDispatcher(reader, root, child_runner=never_child)
            assert observer.reconcile_ordinary() == pending
        assert len(calls) == 1 and not remote.service.batches
        # A different request or mutable last pointer cannot become the
        # continuation, and readback never consumes that different pointer.
        next_scan = root / 'next-scan.json'
        foreign = b'{"mode":"full","request_id":"separately-owned"}\n'
        next_scan.write_bytes(foreign)
        (root / 'last-scan-request.json').write_text('{}')
        assert supervisor.run_once() == pending
        assert next_scan.read_bytes() == foreign
        settled = execute(queued, 'publish', cycle_id=cycle_id)
        assert settled['state'] == 'SYNC_CONFIRMED'
        assert supervisor.run_once() == {
            'state': 'ORDINARY_SETTLED', 'request_id': request['request_id'],
            'request_sha256': digest, 'cycle_id': cycle_id,
        }
        assert supervisor.run_once()['state'] == 'HELD_FOREIGN_REQUEST'
        assert next_scan.read_bytes() == foreign
        assert supervisor.status()['dispatches'] == {'ORDINARY_SETTLED': 1}
        assert supervisor.reconcile_ordinary() is None
    provider.assert_called_once()
    assert [call.kwargs['write'] for call in factory.call_args_list] == [False, True]


def test_moved_pointer_after_return_is_not_settlement(queued):
    paths, _, _, provider, factory, _, _ = queued
    root = paths[0].parent

    def move_pointer(arguments):
        (root / 'next-scan.json').unlink()
        return 0

    with closing(SQLiteRepository(paths[1], 'sheet')) as local:
        dispatcher = CompanyIntakeDispatcher(local, root, child_runner=move_pointer)
        dispatcher.set_enabled(True)
        assert dispatcher.run_once()['state'] == 'ORDINARY_CHILD_RETURNED'
        assert dispatcher.run_once()['state'] == 'HELD_ORDINARY_EVIDENCE'
        assert dispatcher.status()['dispatches'] == {'ORDINARY_CLAIMED': 1}
    provider.assert_not_called()
    factory.assert_not_called()


def test_enabled_tick_bridges_latest_outbox_to_the_exact_public_launch(queued):
    paths, _, _, provider, factory, _, _ = queued
    root = paths[0].parent
    (root / 'next-scan.json').unlink()
    launches = []

    def child(arguments):
        _, saved = read_verified_queued_event(local, root)
        assert saved['company_ids'] == ['COMP-2']
        assert saved['company_event']['event_id'] == event['event_id']
        assert arguments[1:] == ('ordinary-company-event', 'admit-fetch', '--request-sha256', _json_digest(saved))
        launches.append(arguments)
        return 0

    with closing(SQLiteRepository(paths[1], 'sheet')) as local:
        event = local.mutate_company_with_event({
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-2'},
            'values': {'Official Careers URL': 'https://jobs.eu.lever.co/other'},
        })['company_event']
        dispatcher = CompanyIntakeDispatcher(local, root, child_runner=child)
        dispatcher.set_enabled(True)
        result = dispatcher.run_once()
        assert result['state'] == 'ORDINARY_CHILD_RETURNED'
        assert len(launches) == 1
        assert dispatcher.run_once()['state'] == 'HELD_ORDINARY_ADMIT_FETCH'
    provider.assert_not_called()
    factory.assert_not_called()


def test_receipted_queue_tampering_holds_before_child_or_claim(queued):
    paths, request, _, provider, factory, _, _ = queued
    root = paths[0].parent
    (root / 'next-scan.json').write_text(json.dumps({**request, 'enqueued_at': '2099-01-01T00:00:00Z'}))
    with closing(SQLiteRepository(paths[1], 'sheet')) as local:
        dispatcher = CompanyIntakeDispatcher(local, root, child_runner=lambda args: pytest.fail('spawned'))
        dispatcher.set_enabled(True)
        assert dispatcher.run_once()['state'] == 'HELD_ORDINARY_QUEUE_EVIDENCE'
        assert not dispatcher.status()['dispatches']
    provider.assert_not_called()
    factory.assert_not_called()


def test_provider_claim_without_inventory_never_emits_publish_or_relaunch(queued):
    paths, _, _, provider, factory, _, _ = queued
    root = paths[0].parent
    provider.side_effect = RuntimeError('fixture cut after fetch claim')

    def interrupted(arguments):
        return execute(queued)

    with closing(SQLiteRepository(paths[1], 'sheet')) as local:
        dispatcher = CompanyIntakeDispatcher(local, root, child_runner=interrupted)
        dispatcher.set_enabled(True)
        assert dispatcher.run_once()['state'] == 'HELD_ORDINARY_LAUNCH_UNCONFIRMED'
        held = dispatcher.run_once()
        assert held['state'] == 'HELD_ORDINARY_FETCH_UNCERTAIN'
        assert 'cycle_id' in held and 'continuation' not in held
        assert dispatcher.run_once() == held
    provider.assert_called_once()
    factory.assert_called_once()


def test_prearchive_restart_handoff_pins_exact_saved_cycle_without_refetch(queued, monkeypatch):
    paths, request, digest, provider, factory, _, _ = queued
    root = paths[0].parent
    selected = []

    def before_archive(engine, state, database):
        event_request = {**request, 'request_fingerprint': request_fingerprint(request, ['COMP-1'])}
        selected.append(engine.start_cycle(company_ids=['COMP-1'], new_scan_request=event_request))
        raise RuntimeError('fixture cut before the immutable admission archive')

    def child(arguments):
        with monkeypatch.context() as restart:
            restart.setattr(command, 'requested_scan', before_archive)
            return execute(queued)

    with closing(SQLiteRepository(paths[1], 'sheet')) as local:
        dispatcher = CompanyIntakeDispatcher(local, root, child_runner=child)
        dispatcher.set_enabled(True)
        assert dispatcher.run_once()['state'] == 'HELD_ORDINARY_LAUNCH_UNCONFIRMED'
        held = dispatcher.run_once()
        assert held['state'] == 'HELD_ORDINARY_ADMIT_FETCH'
        assert held['continuation'][1:] == (
            'ordinary-company-event', 'admit-fetch', '--request-sha256', digest, '--cycle-id', selected[0],
        )
        assert dispatcher.run_once() == held
        assert dispatcher.status()['ordinary_handoff']['cycle_id'] == selected[0]
        provider.assert_not_called()
        factory.assert_not_called()
        assert execute(queued, cycle_id=selected[0])['state'] == 'INVENTORY_FROZEN'
        assert dispatcher.run_once()['state'] == 'HELD_ORDINARY_PUBLICATION'
    provider.assert_called_once()


def test_typed_no_write_terminal_requires_immutable_outcome_readback(queued):
    paths, _, _, provider, factory, remote, _ = queued
    root = paths[0].parent
    provider.return_value = ats.Inventory('failed', source_url=OBSERVED, ats='Lever',
                                          outcome_failure=ats.outcome_failure('temporary_transport', 'retryable_http_status'))

    def child(arguments):
        assert execute(queued)['state'] == 'INVENTORY_FROZEN'
        return 0

    with closing(SQLiteRepository(paths[1], 'sheet')) as local:
        dispatcher = CompanyIntakeDispatcher(local, root, child_runner=child)
        dispatcher.set_enabled(True)
        dispatcher.run_once()
        pending = dispatcher.run_once()
        assert pending['state'] == 'HELD_ORDINARY_PUBLICATION'
        settled = execute(queued, 'publish', cycle_id=pending['cycle_id'])
        assert settled['state'] == 'FETCH_TEMPORARY'
        with local.db:
            original = local.db.execute('SELECT payload FROM scrape_outcomes').fetchone()[0]
            local.db.execute("UPDATE scrape_outcomes SET payload='{}'")
        assert dispatcher.run_once()['state'] == 'HELD_ORDINARY_EVIDENCE'
        with local.db:
            local.db.execute('UPDATE scrape_outcomes SET payload=?', (original,))
        assert dispatcher.run_once()['state'] == 'ORDINARY_SETTLED'
    assert [call.kwargs['write'] for call in factory.call_args_list] == [False, False]
    assert not remote.service.batches


@pytest.mark.parametrize('kind', ['operator', 'manual-retained'])
def test_unrelated_queue_is_left_byte_for_byte_without_provider_or_children(queued, kind):
    paths, request, _, provider, factory, _, _ = queued
    root = paths[0].parent
    path = root / 'next-scan.json'
    unrelated = ({'mode': 'full', 'request_id': 'operator-owned'} if kind == 'operator'
                 else {**request, 'manual_retained': {}})
    path.write_text(json.dumps(unrelated))
    raw = path.read_bytes()
    with closing(SQLiteRepository(paths[1], 'sheet')) as local:
        dispatcher = CompanyIntakeDispatcher(local, root, child_runner=lambda args: pytest.fail('spawned'))
        dispatcher.set_enabled(True)
        status = dispatcher.run_once()['state']
        expected = 'HELD_FOREIGN_REQUEST' if kind == 'operator' else 'HELD_MANUAL_RETAINED_EVENT'
        assert status == expected
        assert not dispatcher.status()['dispatches']
    assert path.read_bytes() == raw
    provider.assert_not_called()
    factory.assert_not_called()


def test_watch_reports_guarded_handoff_without_opening_broad_sync(queued, monkeypatch):
    from unittest.mock import Mock
    from job_search_helper import sync_cli

    paths, _, digest, provider, command_reader, _, _ = queued
    root = paths[0].parent

    def child(arguments):
        assert arguments[1:] == ('ordinary-company-event', 'admit-fetch', '--request-sha256', digest)
        assert execute(queued)['state'] == 'INVENTORY_FROZEN'
        return 0

    with closing(SQLiteRepository(paths[1], 'sheet')) as local:
        dispatcher = CompanyIntakeDispatcher(local, root, child_runner=child)
        dispatcher.set_enabled(True)
        assert dispatcher.run_once()['state'] == 'ORDINARY_CHILD_RETURNED'

    status = []
    broad_remote = Mock(side_effect=AssertionError('watch opened a broad workbook factory'))
    broad_cycle = Mock(side_effect=AssertionError('watch started broad sync'))
    monkeypatch.setattr(sync_cli, '_load_environment', lambda: None)
    monkeypatch.setattr(sync_cli, 'print_status', status.append)
    monkeypatch.setattr(sync_cli, 'get_remote_repository', broad_remote)
    monkeypatch.setattr(sync_cli, 'cycle', broad_cycle)
    monkeypatch.setattr(sync_cli.time, 'sleep', Mock(side_effect=KeyboardInterrupt))
    assert sync_cli.main(['watch', '--interval', '5']) == 130
    handoffs = [row['company_intake'] for row in status if 'company_intake' in row]
    assert len(handoffs) == 1
    assert handoffs[0]['state'] == 'HELD_ORDINARY_PUBLICATION'
    assert handoffs[0]['continuation'][1:] == (
        'ordinary-company-event', 'publish', '--request-sha256', digest, '--cycle-id', handoffs[0]['cycle_id'],
    )
    provider.assert_called_once()
    command_reader.assert_called_once()
    broad_remote.assert_not_called()
    broad_cycle.assert_not_called()


@pytest.mark.parametrize('changed', ['source', 'ambiguous empty'])
def test_supervisor_offers_no_publication_for_stale_or_ambiguous_observation(queued, changed):
    paths, _, digest, provider, factory, _, _ = queued
    root = paths[0].parent
    if changed == 'ambiguous empty':
        provider.return_value = ats.Inventory('complete', source_url=OBSERVED, ats='Lever')

    def child(arguments):
        assert arguments[-1] == digest
        assert execute(queued)['state'] == 'INVENTORY_FROZEN'
        return 0

    with closing(SQLiteRepository(paths[1], 'sheet')) as local:
        dispatcher = CompanyIntakeDispatcher(local, root, child_runner=child)
        dispatcher.set_enabled(True)
        assert dispatcher.run_once()['state'] == 'ORDINARY_CHILD_RETURNED'
        if changed == 'source':
            local.mutate_company_with_event({
                'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
                'values': {'Official Careers URL': 'https://jobs.eu.lever.co/acme?location=Boston'},
            })
        result = dispatcher.run_once()
        assert result['state'] == ('HELD_ORDINARY_EVIDENCE' if changed == 'source'
                                   else 'HELD_ORDINARY_NO_PUBLICATION_SCOPE')
        assert 'continuation' not in result
    factory.assert_called_once()
    provider.assert_called_once()
