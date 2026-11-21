import json

import pytest

from controller import UNITS, ensure_file
from test_operator_quiet_window import prepared


def assert_held(window, fixture):
    assert json.loads(window.journal.read_text())['phase']=='RESTORING'
    assert window.units.sentinel.is_file(), 'restart guard was removed after unverified restoration'
    assert not any(fixture.active.values()), 'an unverified wrapper remained active'
    for name in UNITS:
        assert window.units.path(name).read_bytes()==window.units.data


def test_failed_restored_verification_keeps_physical_fence(prepared):
    window,fixture,_=prepared
    window.verify_restored=lambda _:False
    with pytest.raises(ValueError,match='restored operator host'):
        with window.hold():
            assert not any(fixture.active.values())
    assert_held(window,fixture)


def test_start_applies_then_raises_keeps_physical_fence(prepared):
    window,fixture,_=prepared
    with pytest.raises(RuntimeError,match='interruption during start'):
        with window.hold():
            fixture.fail='start'
    assert_held(window,fixture)


@pytest.mark.parametrize('field,value',[('JOB_STORAGE_BACKEND','sheets'),('JOB_DB_FILE','foreign-jobs.sqlite3')])
def test_noncanonical_application_backend_or_jobs_does_not_close_units(prepared,monkeypatch,field,value):
    window,fixture,proofs=prepared
    monkeypatch.setenv('JOB_STORAGE_BACKEND','sqlite')
    monkeypatch.setenv('JOB_DB_FILE',str(window.application_state/'jobs.sqlite3'))
    monkeypatch.setenv(field,value)
    entered=[]
    try:
        with window.hold():
            entered.append(True)
    except ValueError:
        pass
    assert not entered
    assert not window.journal.exists() and fixture.commands==[] and not proofs


def test_saved_closing_with_partial_fence_restores_without_reentering_worker(prepared):
    window,fixture,proofs=prepared
    prior=window.units.snapshot()
    window._save({'binding':window._binding(),'prior':prior},'CLOSING')
    ensure_file(window.units.sentinel,b'')
    path=window.units.path(UNITS[0])
    path.parent.mkdir()
    ensure_file(path,window.units.data,0o644)
    assert window.restore()['state']=='OPERATOR_MAINTENANCE_RESTORED'
    assert json.loads(window.journal.read_text())['phase']=='RESTORED'
    assert fixture.active=={UNITS[0]:True,UNITS[1]:False}
    assert 'closed' not in proofs and not window.units.sentinel.exists()
    assert all(not window.units.path(name).exists() for name in UNITS)
