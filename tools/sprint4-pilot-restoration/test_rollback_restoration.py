from contextlib import contextmanager
import fcntl
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from host_exchange import Hold, encode
from pilot_restore_command import read_protected_rollback
from pilot_restoration import ROLLBACK_SCHEMA, exchange_identity, restore_after_rollback
from test_host_exchange import fixture, states
import test_protected_state as state_fixtures


@pytest.fixture
def protected_site(tmp_path, fixture):
    exchange, _ = fixture
    exchange.prepare()
    closure = exchange.close()
    protected = state_fixtures.ProtectedWitnessTests()
    protected.setUp()
    project = protected.root
    selection = {
        "exchange_policy": str(exchange.policy_path),
        "exchange_policy_sha256": exchange.approved_sha256,
        "receiver_database": str(protected.dbpaths["coordinator"]),
    }
    policy = {"schema": "sprint-4-site-policy-v1",
              "site": {"project": str(project), "maintenance_id": "fixture",
                       "exchange_fence": {"policy_file": selection["exchange_policy"],
                                          "policy_sha256": selection["exchange_policy_sha256"]}},
              "protected_pin_file": str(protected.pin), "protected_pin_sha256": protected.digest}
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("approved_site_policy.json", json.dumps(policy))
        archive.write(Path(state_fixtures.witness.__file__), "protected_state.py")
    checker = tmp_path / "host-check"
    checker.write_bytes(buffer.getvalue())
    release = {"source": "ROLLED_BACK", "maintenance_id": "fixture"}
    marker = project / ".state/integration-release-journal.json"
    scraper_lock = marker.with_name("scraper.lock")
    scraper_lock.touch(mode=0o600)

    @contextmanager
    def verified_release():
        with scraper_lock.open("rb") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            yield release

    controller = SimpleNamespace(project=project, marker=marker, hold_id="fixture", checker=checker,
                                 binding={"files": {str(checker): [sha256(checker.read_bytes()).hexdigest()]}},
                                 restoration_terminal=verified_release)

    def read():
        return read_protected_rollback(controller, checker, checker.read_bytes(), selection, "a" * 64)

    try:
        with controller.restoration_terminal():
            approval = encode({"schema": ROLLBACK_SCHEMA, "release": release,
                               "exchange": exchange_identity(closure), "rollback": read()})
        yield protected, controller, exchange, approval, read
    finally:
        protected.doCleanups()


def test_rollback_uses_exact_stored_baseline_under_lease(protected_site):
    _, controller, exchange, approval, read = protected_site
    with pytest.raises(RuntimeError, match="closure unverified"):
        read()
    restored = restore_after_rollback(controller, exchange, approval,
                                      approved_sha256=sha256(approval).hexdigest(), read_protected_rollback=read)
    assert restored.phase == "restored"
    assert states(exchange) == [True, True, True]


def test_rollback_refuses_new_outbox_event(protected_site):
    protected, controller, exchange, approval, read = protected_site
    protected.sql("jobs", "INSERT INTO company_event_outbox VALUES ('new-event')")
    with pytest.raises(RuntimeError, match="differs from private pin"):
        restore_after_rollback(controller, exchange, approval,
                               approved_sha256=sha256(approval).hexdigest(), read_protected_rollback=read)
    assert states(exchange) == [False, False, False]


def test_rollback_refuses_new_retained_first_pass_output(protected_site):
    protected, controller, exchange, approval, read = protected_site
    folder = protected.root / ".state/retained-first-pass/synthetic"
    folder.mkdir(parents=True)
    (folder / "release.json").write_text("synthetic queue release")
    with pytest.raises(RuntimeError, match="differs from private pin"):
        restore_after_rollback(controller, exchange, approval,
                               approved_sha256=sha256(approval).hexdigest(), read_protected_rollback=read)
    assert states(exchange) == [False, False, False]


def test_rollback_refuses_checker_not_bound_by_joint_release(protected_site):
    _, controller, exchange, approval, read = protected_site
    controller.binding["files"][str(controller.checker)][-1] = "f" * 64
    with controller.restoration_terminal(), pytest.raises(ValueError, match="original controller binding"):
        read()
    with pytest.raises(Hold, match="evidence unavailable"):
        restore_after_rollback(controller, exchange, approval,
                               approved_sha256=sha256(approval).hexdigest(), read_protected_rollback=read)
    assert states(exchange) == [False, False, False]


def test_installed_target_does_not_qualify_for_pre_pilot_rollback(protected_site):
    _, controller, exchange, approval, read = protected_site

    @contextmanager
    def wrong_release():
        yield {"source": "INSTALLED", "maintenance_id": "fixture"}

    controller.restoration_terminal = wrong_release
    with pytest.raises(Hold, match="approved target"):
        restore_after_rollback(controller, exchange, approval,
                               approved_sha256=sha256(approval).hexdigest(), read_protected_rollback=read)
    assert states(exchange) == [False, False, False]
