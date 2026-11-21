import json

import pytest

from job_search_helper import ordinary_raw_capture as raw
from job_search_helper.repository import RepositoryError
from test_s5_ordinary_verifier_handoff import (
    attempt, enrolled, fixture_verifier_result, local_worker, measured_scope,
    record_private, stage,
)


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_missing_owner_slot_does_not_replenish_prior_attempt(enrolled):
    channel, root, _, args, _, _ = enrolled
    work = stage(enrolled, request_limit=32)
    fixture_verifier_result(enrolled, work, result='TIMEOUT')
    assert channel.read_result(*args)['receipt']['result'] == 'TIMEOUT'
    anchor = root / (work.slot.name + '.json')
    original_anchor = anchor.read_bytes()

    work.slot.rename(root / 'detached-before-retry')
    with pytest.raises(RepositoryError, match='missing and cannot be replaced'):
        stage(enrolled, duration_seconds=119, request_limit=64)
    assert not work.slot.exists()
    assert anchor.read_bytes() == original_anchor


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_missing_receipt_keeps_the_same_staged_job(enrolled):
    channel, _, _, args, _, _ = enrolled
    work = stage(enrolled, request_limit=32)
    fixture_verifier_result(enrolled, work, result='TIMEOUT')
    (work.slot / 'receipt.json').unlink()
    original = (work.slot / 'job.json').read_bytes()

    assert channel.read_result(*args) is None
    assert stage(enrolled, request_limit=32) == work
    assert (work.slot / 'job.json').read_bytes() == original
    with pytest.raises(RepositoryError, match='original.*budget'):
        stage(enrolled, request_limit=64)


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_visible_receipt_without_owned_reservation_is_held(enrolled):
    channel, _, _, args, _, _ = enrolled
    work = stage(enrolled)
    fixture_verifier_result(enrolled, work)
    (work.slot / 'reservation.json').unlink()

    with pytest.raises(RepositoryError, match='no owned reservation'):
        channel.read_result(*args)


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_unverified_checksum_replacement_is_held(enrolled):
    channel, _, _, args, _, _ = enrolled
    work = stage(enrolled)
    fixture_verifier_result(enrolled, work)
    result = json.loads((work.slot / 'receipt.json').read_bytes())
    result['receipt_sha256'] = '0' * 64
    record_private(work.slot, 'receipt.json', result)

    with pytest.raises(RepositoryError, match='checksum differs'):
        channel.read_result(*args)


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_interrupted_before_sibling_pin_attaches_only_same_unstarted_slot(enrolled, monkeypatch):
    channel, root, _, args, _, _ = enrolled
    publish = raw._publish_directory

    def cut(owner_fd, candidate, target):
        if target.endswith('.json'):
            raise RuntimeError('cut before owner record publishes')
        publish(owner_fd, candidate, target)

    with monkeypatch.context() as interruption:
        interruption.setattr(raw, '_publish_directory', cut)
        with pytest.raises(RuntimeError, match='cut before owner record publishes'):
            stage(enrolled, request_limit=32)
    (slot,) = tuple(root.iterdir())
    identity = (slot.stat().st_dev, slot.stat().st_ino)
    original_job = (slot / 'job.json').read_bytes()
    anchor = root / (slot.name + '.json')
    assert not anchor.exists()
    with pytest.raises(RepositoryError, match='owner record differs'):
        channel.read_result(*args)

    work = stage(enrolled, request_limit=32)
    assert work.slot == slot and (slot.stat().st_dev, slot.stat().st_ino) == identity
    assert (slot / 'job.json').read_bytes() == original_job
    assert json.loads(anchor.read_bytes())['slot_identity'] == list(identity)
    assert channel.read_result(*args) is None
    assert stage(enrolled, request_limit=32) == work


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_missing_sibling_pin_cannot_adopt_interrupted_supervisor_without_receipt(enrolled):
    channel, root, _, args, _, _ = enrolled
    work = stage(enrolled, request_limit=32)
    fixture_verifier_result(enrolled, work, result='TIMEOUT')
    (work.slot / 'receipt.json').unlink()
    anchor = root / (work.slot.name + '.json')
    anchor.unlink()

    with pytest.raises(RepositoryError, match='unanchored.*prior supervisor'):
        stage(enrolled, request_limit=32)
    with pytest.raises(RepositoryError, match='owner record differs'):
        channel.read_result(*args)
    assert not anchor.exists()
