"""Real disposable exchanges; native terminal and data observers are substituted."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
import host_exchange
from test_host_exchange import fixture as existing_fixture, states
import retirement_restoration as adapter


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(host_exchange, 'FIXTURE_BASE', tmp_path / 'exchanges')
    original = existing_fixture.__wrapped__()
    exchange, _ = next(original)
    exchange.prepare()
    exchange.close()
    release = {'source': 'INSTALLED', 'maintenance_id': adapter.MAINTENANCE_ID,
               'project': adapter.PROJECT, 'source_manifest_sha256': adapter.MANIFEST_SHA256,
               'controller_journal_sha256': 'c' * 64, 'installer_receipt_sha256': 'd' * 64}
    held = []
    @contextmanager
    def terminal():
        held.append(True)
        try:
            yield release
        finally:
            held.pop()
    controller = SimpleNamespace(manifest=SimpleNamespace(schema=adapter.MANIFEST_SCHEMA,
        sha256=adapter.MANIFEST_SHA256, paths=tuple(range(44))), restoration_terminal=terminal)
    retirement = {'cycle_id': adapter.CYCLE_ID, 'state': 'RETIRED_UNPUBLISHED', 'published': False,
                  'archive_root': str(tmp_path / 'approved-archive'), 'archive_scope_sha256': 'a' * 64,
                  'retirement_record_sha256': 'b' * 64}
    protected = {'protected_pin_sha256': 'e' * 64, 'witness_sha256': 'f' * 64}
    def retired():
        assert held
        return deepcopy(retirement)
    def unchanged():
        assert held
        return deepcopy(protected)
    callbacks = {'read_verified_retirement': retired, 'read_protected_state': unchanged}
    plan = adapter.observe_after_retirement(controller, exchange, **callbacks)
    try:
        yield SimpleNamespace(controller=controller, exchange=exchange, release=release,
            retirement=retirement, protected=protected, callbacks=callbacks, plan=plan, held=held)
    finally:
        original.close()


def restore(case, plan=None):
    raw = host_exchange.encode(case.plan if plan is None else plan)
    return adapter.restore_after_retirement(case.controller, case.exchange, raw,
        approved_sha256=sha256(raw).hexdigest(), **case.callbacks)


def test_retirement_terminal_restores_without_any_pilot_and_replays(case, monkeypatch):
    swap = host_exchange._exchange
    def guarded(*args):
        assert case.held
        return swap(*args)
    monkeypatch.setattr(host_exchange, '_exchange', guarded)
    result = restore(case)
    assert states(case.exchange) == [True] * 3
    assert result == restore(case) == case.exchange.witness('restored')
    assert result.terminal_proof_sha256 == sha256(host_exchange.encode(case.plan)).hexdigest()
    assert not case.held and 'pilot' not in case.plan


@pytest.mark.parametrize('field', ['release', 'exchange', 'retirement', 'protected'])
def test_mismatched_approved_evidence_keeps_every_route_closed(case, field):
    changed = deepcopy(case.plan)
    changed[field]['foreign'] = True
    with pytest.raises(host_exchange.Hold):
        restore(case, changed)
    assert states(case.exchange) == [False] * 3
    assert case.exchange.witness().phase == 'closed'


@pytest.mark.parametrize('change', ['archive', 'published', 'protected', 'rollback'])
def test_fresh_readback_drift_or_rollback_target_holds(case, change):
    if change == 'archive':
        case.retirement['archive_scope_sha256'] = '1' * 64
    elif change == 'published':
        case.retirement['published'] = True
    elif change == 'protected':
        case.protected['witness_sha256'] = '2' * 64
    else:
        case.release['source'] = 'ROLLED_BACK'
    with pytest.raises(host_exchange.Hold):
        restore(case)
    assert states(case.exchange) == [False] * 3


def test_wrong_manifest_or_independent_approval_pin_holds(case):
    raw = host_exchange.encode(case.plan)
    with pytest.raises(host_exchange.Hold, match='trusted pin'):
        adapter.restore_after_retirement(case.controller, case.exchange, raw,
            approved_sha256='0' * 64, **case.callbacks)
    case.controller.manifest.sha256 = '0' * 64
    with pytest.raises(host_exchange.Hold, match='Exact installed'):
        restore(case)
    assert states(case.exchange) == [False] * 3


def test_partial_restoration_resumes_only_same_approved_retirement(case, monkeypatch):
    swap = host_exchange._exchange
    def interrupted(*args):
        swap(*args)
        raise OSError('fixture interruption after first placement')
    with monkeypatch.context() as patch:
        patch.setattr(host_exchange, '_exchange', interrupted)
        with pytest.raises(host_exchange.Hold):
            restore(case)
    assert states(case.exchange) == [True, False, False]
    changed = deepcopy(case.plan)
    changed['retirement']['retirement_record_sha256'] = '3' * 64
    with pytest.raises(host_exchange.Hold, match='terminal proof changed'):
        restore(case, changed)
    assert states(case.exchange) == [True, False, False]
    assert restore(case).phase == 'restored'
    assert states(case.exchange) == [True] * 3
