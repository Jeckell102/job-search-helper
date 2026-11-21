from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from job_search_helper import ordinary_verifier_handoff as handoff
from job_search_helper.repository import RepositoryError
from test_s5_ordinary_verifier_handoff import (
    attempt, enrolled, fixture_verifier_result, local_worker, measured_scope, stage,
)


OLD_ROOT = Path('/tmp/jsh-s5-bound-verifier-qa-final-pin.yVFvzyA1')
OLD_TOOLS = Path('/tmp/jsh-m5-live-authority-repair.jMbESo7E/dev/pre_release_validation')
OLD_VERIFIER_PIN = 'f218ed98eb0991e72c78b7ddaaf67dcde41f48b6a3d472e171cc5e26b2de1164'
OLD_VECTOR = '1715233f4e8988c08d69cf9c00674d29add135efe22b5e232eb3fff2f842b866'
NEW_VERIFIER_PIN = 'ae39cb34ab229eee22b66f34dbe2d1486d2f08f0e1de0acc43970a8d15bbff14'
NEW_VECTOR = '86723e7fdc0e4e8acdae2dbdc9516c93f0e4557c60ef3b75d17f20869bd3eac0'


def load_verifier(root):
    spec = spec_from_file_location('qa_current_vector_supervisor', root / 'dev/ordinary_rippling_verifier.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def supervisor_args(work):
    return SimpleNamespace(slot=work.slot, evidence=work.slot, pending_sha256=work.pending_sha256,
                           job_sha256=work.job_sha256, owner_slot=work.owner_slot)


def forbid_child(monkeypatch, verifier):
    for name in verifier.LEASE_ENV:
        monkeypatch.delenv(name, raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail('a mismatched or completed job must not invoke a child')

    monkeypatch.setattr(verifier, 'run_child', forbidden)


def test_exact_source_and_tool_vector_matches_owner_constants():
    new = load_verifier(Path.cwd())
    old = load_verifier(OLD_ROOT)
    for verifier, source, vector, tools in (
        (new, NEW_VERIFIER_PIN, NEW_VECTOR, Path.cwd() / 'dev/pre_release_validation'),
        (old, OLD_VERIFIER_PIN, OLD_VECTOR, OLD_TOOLS),
    ):
        assert sha256(Path(verifier.__file__).read_bytes()).hexdigest() == source
        actual = {name: sha256((tools / name).read_bytes()).hexdigest() for name in verifier.TOOLS}
        assert actual == verifier.TOOLS
        canonical = json.dumps(actual, sort_keys=True, separators=(',', ':')).encode()
        assert sha256(canonical).hexdigest() == vector
    changed = {name for name in new.TOOLS if new.TOOLS[name] != old.TOOLS[name]}
    assert changed == {'validate_candidate.py'}
    assert (handoff._VERIFIER, handoff._TOOLS) == (NEW_VERIFIER_PIN, NEW_VECTOR)


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
@pytest.mark.parametrize('owner_is_old', [False, True])
def test_mixed_assigned_owner_exact_verifier_refuses_before_mutex(enrolled, monkeypatch, owner_is_old):
    if owner_is_old:
        monkeypatch.setattr(handoff, '_VERIFIER', OLD_VERIFIER_PIN)
        monkeypatch.setattr(handoff, '_TOOLS', OLD_VECTOR)
    work = stage(enrolled)
    verifier = load_verifier(Path.cwd() if owner_is_old else OLD_ROOT)
    forbid_child(monkeypatch, verifier)
    with pytest.raises(verifier.Stop, match='assigned_offline_slot_changed'):
        verifier.supervise(supervisor_args(work))
    for name in ('verifier.lock', 'reservation.json', 'receipt.json'):
        assert not (work.slot / name).exists()


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_old_exact_receipt_is_historical_and_cannot_be_read_as_new_vector(enrolled, monkeypatch):
    channel, _, _, args, _, _ = enrolled
    with monkeypatch.context() as historical:
        historical.setattr(handoff, '_VERIFIER', OLD_VERIFIER_PIN)
        historical.setattr(handoff, '_TOOLS', OLD_VECTOR)
        work = stage(enrolled)
        original = fixture_verifier_result(enrolled, work)
        assert channel.read_result(*args)['application_authority'] is False

    receipt_file = work.slot / 'receipt.json'
    expected_bytes = receipt_file.read_bytes()
    with pytest.raises(RepositoryError, match='enrolled input'):
        channel.read_result(*args)
    with pytest.raises(RepositoryError, match='enrolled input'):
        stage(enrolled)
    assert receipt_file.read_bytes() == expected_bytes
    old = load_verifier(OLD_ROOT)
    forbid_child(monkeypatch, old)
    result = old.supervise(supervisor_args(work))
    assert result['delivery'] == 'REUSED' and result['receipt'] == original
    assert receipt_file.read_bytes() == expected_bytes


@pytest.mark.parametrize('replace_name', ['validate_candidate.py', 'rippling_capture.py'])
def test_replaced_reviewed_tool_stops_before_evidence_read_or_charge(tmp_path, replace_name):
    verifier = load_verifier(Path.cwd())
    tools = tmp_path / 'reviewed-tools'
    scratch = tmp_path / 'scratch'
    tools.mkdir()
    scratch.mkdir()
    for name in verifier.TOOLS:
        data = (Path.cwd() / 'dev/pre_release_validation' / name).read_bytes()
        if name == replace_name:
            data = ((OLD_TOOLS / name).read_bytes() if name == 'validate_candidate.py'
                    else data + b'\n# offline substitution fixture\n')
        (tools / name).write_bytes(data)

    def charge():
        pytest.fail('mismatched tools must refuse before using the evidence allowance')

    budget = SimpleNamespace(charge=charge)
    args = SimpleNamespace(reviewed_tools=tools)
    with pytest.raises(verifier.Stop, match='reviewed_verifier_source_changed') as held:
        verifier.replay_public(args, {}, {}, budget, scratch)
    assert held.value.result == 'CHANGED_INPUT'
