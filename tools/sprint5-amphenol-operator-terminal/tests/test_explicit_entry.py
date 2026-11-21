from contextlib import contextmanager
from threading import Event, Lock
from types import SimpleNamespace

import pytest

import amphenol_retry_completion as completion
from host_server import AmphenolRecipeEnrollment, OperatorAmphenolRecipeEnrollment


REQUEST_ID = 'operator-amphenol-fixture'
REVISION = '1' * 64
OUTCOME = 'OUT-' + '2' * 24
RELEASE = 'REL-' + '3' * 24


@pytest.fixture
def explicit(tmp_path, monkeypatch):
    coordinator = SimpleNamespace(stop=Event(), workspace_lock=Lock(), control_lock=Lock())
    approval = completion.RetryReleaseApproval(RELEASE, str(tmp_path), 1, 2, '4'*64)
    owner_calls = []

    @contextmanager
    def enrolled_owner(_):
        assert coordinator.workspace_lock.locked()
        assert not coordinator.control_lock.locked()
        owner_calls.append(True)
        yield tmp_path, tmp_path / 'jobs.sqlite3', 'fixture-sheet'

    monkeypatch.setattr(OperatorAmphenolRecipeEnrollment, 'owner_scope', enrolled_owner)
    return coordinator, approval, owner_calls


def test_noncanonical_operator_request_pin_holds_before_shared_receipt_path(explicit, monkeypatch):
    coordinator, approval, calls = explicit
    operator = OperatorAmphenolRecipeEnrollment(REQUEST_ID, REVISION, request_sha256=None)
    shared = []
    monkeypatch.setattr(completion, '_deliver_qualified_retry',
                        lambda *a, **kw: shared.append(kw) or {'state': 'TEST_SHARED_DELIVERY'})
    assert completion.deliver_qualified_operator_retry(
        operator, coordinator, original_outcome=OUTCOME, approval=approval,
    ) == {'state': completion._HELD}
    assert not shared and not calls
    assert not coordinator.workspace_lock.locked()


def test_explicit_operator_requires_operator_provenance_and_approval_type(explicit, monkeypatch):
    coordinator, approval, calls = explicit
    event = AmphenolRecipeEnrollment('company-event:CEV-' + '5'*32, REVISION, 'CEV-' + '5'*32)
    operator = OperatorAmphenolRecipeEnrollment(REQUEST_ID, REVISION, request_sha256='6'*64)
    monkeypatch.setattr(completion, '_deliver_qualified_retry',
                        lambda *a, **k: pytest.fail("wrong owner crossed the gate"))
    assert completion.deliver_qualified_operator_retry(
        event, coordinator, original_outcome=OUTCOME, approval=approval,
    ) == {'state': completion._HELD}
    assert completion.deliver_qualified_operator_retry(
        operator, coordinator, original_outcome=OUTCOME, approval=object(),
    ) == {'state': completion._HELD}
    assert not calls


def test_active_release_mismatch_holds_before_origin_or_transport(explicit, monkeypatch):
    coordinator, approval, calls = explicit
    operator = OperatorAmphenolRecipeEnrollment(REQUEST_ID, REVISION, request_sha256='6'*64)
    monkeypatch.setattr(completion, 'assert_release_settled',
                        lambda _: {'state': 'COMPLETE', 'release_id': 'REL-' + 'a'*24})
    monkeypatch.setattr(completion, '_historical_operator_origin_matches',
                        lambda *a: pytest.fail("wrong release crossed the gate"))
    assert completion.deliver_qualified_operator_retry(
        operator, coordinator, original_outcome=OUTCOME, approval=approval,
    ) == {'state': completion._HELD}
    assert calls == [True]
    assert not coordinator.workspace_lock.locked() and not coordinator.control_lock.locked()


def test_operator_delegate_enters_both_locks_with_exact_scope(explicit, monkeypatch):
    coordinator, approval, calls = explicit
    operator = OperatorAmphenolRecipeEnrollment(REQUEST_ID, REVISION, request_sha256='6'*64)

    def shared(enrollment, current, root, jobs, destination, **scope):
        assert enrollment is operator and current is coordinator
        assert coordinator.workspace_lock.locked() and coordinator.control_lock.locked()
        assert scope == {'original_outcome': OUTCOME, 'approval': approval, 'operator_request_sha256': '6'*64}
        return {'state': completion._HELD}

    monkeypatch.setattr(completion, '_deliver_qualified_retry', shared)
    assert completion.deliver_qualified_operator_retry(
        operator, coordinator, original_outcome=OUTCOME, approval=approval,
    ) == {'state': completion._HELD}
    assert calls == [True]
    assert not coordinator.workspace_lock.locked() and not coordinator.control_lock.locked()


def test_matching_release_with_wrong_qualification_directory_inode_holds(explicit, monkeypatch, tmp_path):
    from dataclasses import replace

    from job_search_helper.repair_retry import RELEASE_BINDING_SCHEMA

    coordinator, approval, calls = explicit
    operator = OperatorAmphenolRecipeEnrollment(REQUEST_ID, REVISION, request_sha256='6'*64)
    qualification = tmp_path / 'qualification'
    qualification.mkdir(mode=0o700)
    attrs = qualification.stat()
    wrong = replace(approval, directory=str(qualification), device=attrs.st_dev, inode=attrs.st_ino + 1)
    release_receipt = {'failed_request_id': REQUEST_ID, 'company_id': 'COMP-0490',
                       'source_revision': REVISION, 'activated_at': '2026-01-01T00:00:00Z',
                       'release': {'schema': RELEASE_BINDING_SCHEMA, 'release_id': RELEASE,
                                   'source_manifest_sha256': '7'*64,
                                   'dependency_manifest_sha256': '8'*64, 'config_sha256': '9'*64}}
    monkeypatch.setattr(completion, 'assert_release_settled',
                        lambda _: {'state': 'COMPLETE', 'release_id': RELEASE, 'record': str(tmp_path)})
    monkeypatch.setattr(completion, '_read_json', lambda _: release_receipt)
    monkeypatch.setattr(completion, '_require_qualified_retry',
                        lambda *a: pytest.fail("wrong qualification owner crossed the gate"))
    expected = completion.canonical_retry_binding(completion._retry_binding(release_receipt))
    attempt = expected['attempt_id']
    actual_open = completion.open_release_qualification_owner
    opens = []

    @contextmanager
    def audited_open(*args, **kwargs):
        opens.append(kwargs['expected_owner_identity'])
        with actual_open(*args, **kwargs) as owner:
            yield owner

    monkeypatch.setattr(completion, 'open_release_qualification_owner', audited_open)
    intent = tmp_path / 'repair-retry' / 'intents' / (attempt + '.json')
    intent.parent.mkdir(parents=True)
    intent.touch()
    assert completion.deliver_qualified_operator_retry(
        operator, coordinator, original_outcome=OUTCOME, approval=wrong,
    ) == {'state': completion._HELD}
    assert calls == [True]
    assert not coordinator.workspace_lock.locked() and not coordinator.control_lock.locked()
    assert opens == [(attrs.st_dev, attrs.st_ino + 1)]
