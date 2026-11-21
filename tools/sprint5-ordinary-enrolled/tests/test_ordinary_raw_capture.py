"""Synthetic custody fixtures. No application stores or provider calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from threading import Barrier

import pytest

import job_search_helper

# Resolve only this new module from the isolated source overlay.
job_search_helper.__path__.insert(0, str(Path(__file__).resolve().parents[1] / 'src/job_search_helper'))
from job_search_helper import ordinary_raw_capture as capture
from job_search_helper.ats import Inventory, RipplingTenantMismatch
from job_search_helper.ordinary_verification_pending import SCHEMA, digest


CONFIGURED = 'https://ats.rippling.com/retired-forterra/jobs'
AUTHORITY = 'https://www.forterra.com/careers'
BODY = b'<!doctype html>\r\nprivate synthetic response, no network\r\n'
SOURCE = '1' * 64
POLICY = '2' * 64
PINS = {'source_manifest_sha256': SOURCE, 'capture_policy_sha256': POLICY}


@pytest.fixture
def case(tmp_path):
    root = tmp_path / 'private-captures'
    root.mkdir(mode=0o700)
    armed = {'schema': SCHEMA, 'state': 'ARMED', 'owner': {
        'cycle_id': 'CYC-000000000001', 'cycle_started_at': '2026-11-20T18:13:00+00:00',
        'request_id': 'SCAN-001', 'request_fingerprint': '3' * 64, 'company_id': 'COMP-0066',
        'source_revision': '4' * 64, 'company_source_sha256': '5' * 64,
        'store_binding_sha256': '6' * 64, 'observation_generation': 1,
    }, 'admission': {
        'authority_url': AUTHORITY, 'configured_url': CONFIGURED, 'capability_id': 'rippling-shared-v1',
        'capability_digest': '7' * 64, 'mapping_digest': '8' * 64, 'configuration_digest': '9' * 64,
        'matrix_digest': 'a' * 64, 'runtime_binding_sha256': 'b' * 64,
    }}
    observation = RipplingTenantMismatch(CONFIGURED, 'retired-forterra', 'unrelated-tenant', sha256(BODY).hexdigest())
    inventory = Inventory('partial', reason='Synthetic Rippling mismatch.', source_url=CONFIGURED, ats='Rippling',
                          rippling_tenant_mismatch=observation)
    payload = {'jobs': [], 'inventory_status': 'partial', 'reason': inventory.reason, 'source_url': CONFIGURED,
               'ats': 'Rippling', 'browser_pending_urls': [], 'browser_discovery_incomplete': False,
               'fetched_at': '2026-11-20T18:20:01+00:00', 'requested_url': AUTHORITY}
    prepared = {**deepcopy(armed), 'state': 'PREPARED', 'dispatch_sha256': digest(armed),
                'inventory_sha256': digest(payload), 'observation': observation.to_record(), 'failure': None}
    return root, armed, observation, inventory, payload, prepared


@contextmanager
def owned(root):
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with capture.open_custody(root, descriptor) as custody:
            yield custody
            assert os.fstat(descriptor).st_ino == root.stat().st_ino
    finally:
        os.close(descriptor)


def offer(ticket, observation, **changes):
    fields = {'request_url': CONFIGURED, 'response_url': CONFIGURED, 'status': 200, 'body': BODY}
    fields.update(changes)
    return ticket.offer(observation, **fields)


def seal(case):
    root, armed, observation, inventory, payload, _ = case
    with owned(root) as custody, custody.reserve(armed, digest(armed), **PINS) as ticket:
        assert offer(ticket, observation)
        return ticket.seal(inventory, payload)


def read(case, **changes):
    root, _, _, _, payload, prepared = case
    args = {'blocked': False, **PINS}
    args.update(changes)
    with owned(root) as custody:
        return custody.read_prepared(prepared, payload, **args)


def test_exact_selection_seal_and_restart_reuse(case):
    root, armed, observation, inventory, payload, prepared = case
    slot = root / digest(armed)
    before = deepcopy(payload)
    with owned(root) as custody:
        with custody.reserve(armed, digest(armed), **PINS) as ticket:
            assert {p.name for p in slot.iterdir()} == {'reservation.json'}
            assert offer(ticket, observation)
            assert {p.name for p in slot.iterdir()} == {'reservation.json'}
            manifest_sha = ticket.seal(inventory, payload)
            with pytest.raises(capture.CaptureError, match='already_consumed'):
                ticket.seal(inventory, payload)
        assert payload == before
    recovered = read(case)
    assert recovered.body == BODY and BODY.decode().strip() not in repr(recovered)
    assert recovered.inventory_sha256 == prepared['inventory_sha256']
    assert recovered.response_sha256 == observation.response_sha256
    assert manifest_sha == recovered.manifest_sha256
    assert read(case) == recovered
    for entry in ('manifest.json', 'configured-response.html'):
        assert (slot / 'capture' / entry).stat().st_mode & 0o777 == 0o600
    manifest = json.loads((slot / 'capture/manifest.json').read_bytes())
    assert 'body' not in manifest and manifest['body_bytes'] == len(BODY)
    assert set((slot / 'capture').iterdir()) == {slot / 'capture' / f for f in ('manifest.json', 'configured-response.html')}
    with owned(root) as custody, pytest.raises(capture.CaptureError, match='already_reserved'):
        with custody.reserve(armed, digest(armed), **PINS):
            pytest.fail('A restart must not expose a second ticket')


@pytest.mark.parametrize('changes', [
    {'body': b'x' * (capture.MAX_CAPTURE_BYTES + 1)}, {'body': b'same length or different content'},
    {'body': bytearray(BODY)}, {'body': b''}, {'status': True}, {'status': 302},
    {'request_url': AUTHORITY}, {'response_url': 'https://ats.rippling.com/redirected/jobs'},
])
def test_invalid_offers_never_retain_or_seal(case, changes):
    root, armed, observation, inventory, payload, _ = case
    with owned(root) as custody, custody.reserve(armed, digest(armed), **PINS) as ticket:
        assert not offer(ticket, observation, **changes)
        assert not offer(ticket, observation)
        with pytest.raises(capture.CaptureError, match='observation_not_owned'):
            ticket.seal(inventory, payload)
    assert not (root / digest(armed) / 'capture').exists()


def test_oversize_even_with_its_own_correct_digest_is_declined(case):
    root, armed, _, _, _, _ = case
    body = b'x' * (capture.MAX_CAPTURE_BYTES + 1)
    oversized = RipplingTenantMismatch(CONFIGURED, 'retired-forterra', 'unrelated-tenant', sha256(body).hexdigest())
    with owned(root) as custody, custody.reserve(armed, digest(armed), **PINS) as ticket:
        assert not offer(ticket, oversized, body=body)


@pytest.mark.parametrize('status', ['complete', 'blocked', 'unsupported', 'partial'])
def test_unselected_final_clears_memory_without_saving_raw(case, status):
    root, armed, observation, _, payload, _ = case
    with owned(root) as custody, custody.reserve(armed, digest(armed), **PINS) as ticket:
        assert offer(ticket, observation)
        assert ticket.seal(Inventory(status, ats='Rippling'), payload) is None
        assert ticket._candidate is None
    assert not (root / digest(armed) / 'capture').exists()


@pytest.mark.parametrize('changes', [
    {'status': 'blocked'}, {'status': 'complete'}, {'jobs': [{'posting_id': 'other'}]},
    {'verified_zero': 'verified'}, {'outcome_failure': {'kind': 'access'}},
    {'browser_discovery_incomplete': True}, {'browser_pending_urls': [CONFIGURED]},
    {'source_url': AUTHORITY},
])
def test_typed_claim_with_conflicting_final_precedence_holds(case, changes):
    root, armed, observation, inventory, payload, _ = case
    with owned(root) as custody, custody.reserve(armed, digest(armed), **PINS) as ticket:
        assert offer(ticket, observation)
        for key, value in changes.items():
            setattr(inventory, key, value)
        with pytest.raises(capture.CaptureError, match='final_outcome_conflict'):
            ticket.seal(inventory, payload)
    assert not (root / digest(armed) / 'capture').exists()


def test_concurrent_offers_leave_no_selectable_capture(case):
    root, armed, observation, inventory, payload, _ = case
    rendezvous = Barrier(2)
    with owned(root) as custody, custody.reserve(armed, digest(armed), **PINS) as ticket:
        def attempt():
            rendezvous.wait(timeout=5)
            return offer(ticket, observation)

        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(attempt) for _ in range(2)]
            assert sorted(result.result(timeout=5) for result in futures) == [False, True]
        with pytest.raises(capture.CaptureError, match='observation_not_owned'):
            ticket.seal(inventory, payload)


@pytest.mark.parametrize('alteration', ['generation', 'runtime', 'configured', 'inventory', 'response', 'blocked', 'source', 'policy'])
def test_prepared_readback_requires_exact_scope_and_saved_inventory(case, alteration):
    _, armed, _, _, payload, prepared = case
    seal(case)
    pins = PINS.copy()
    blocked = alteration == 'blocked'
    if alteration in ('generation', 'runtime', 'configured'):
        if alteration == 'generation':
            prepared['owner']['observation_generation'] += 1
        elif alteration == 'runtime':
            prepared['admission']['runtime_binding_sha256'] = 'c' * 64
        else:
            prepared['admission']['configured_url'] = 'https://ats.rippling.com/another-stale/jobs'
        prepared['dispatch_sha256'] = digest({**armed, 'owner': prepared['owner'], 'admission': prepared['admission']})
    elif alteration == 'inventory':
        payload['fetched_at'] = '2026-11-20T18:20:02+00:00'
    elif alteration == 'response':
        prepared['observation']['response_sha256'] = 'd' * 64
    elif alteration == 'source':
        pins['source_manifest_sha256'] = 'e' * 64
    elif alteration == 'policy':
        pins['capture_policy_sha256'] = 'f' * 64
    with pytest.raises(capture.CaptureError):
        read(case, blocked=blocked, **pins)


def test_armed_handoff_without_exact_f6_and_observation_never_opens_raw(case):
    root, armed, _, _, payload, _ = case
    seal(case)
    with owned(root) as custody, pytest.raises(capture.CaptureError, match='exact_marker'):
        custody.read_prepared(armed, payload, blocked=False, **PINS)


def test_caller_mutation_after_reserve_does_not_repoint_ticket(case, monkeypatch):
    root, armed, observation, inventory, payload, _ = case
    original = capture.os.fsync
    original_key = digest(armed)

    def mutate(fd):
        original(fd)
        armed['admission']['configured_url'] = 'https://ats.rippling.com/repinned/jobs'

    monkeypatch.setattr(capture.os, 'fsync', mutate)
    with owned(root) as custody, custody.reserve(armed, original_key, **PINS) as ticket:
        switched = RipplingTenantMismatch(armed['admission']['configured_url'], 'repinned', 'unrelated-tenant',
                                          observation.response_sha256)
        assert not offer(ticket, switched, request_url=switched.configured_url, response_url=switched.configured_url)
        with pytest.raises(capture.CaptureError, match='observation_not_owned'):
            ticket.seal(inventory, payload)
    assert not (root / original_key / 'capture').exists()


@pytest.mark.parametrize('when', ['before', 'after'])
def test_process_exit_around_atomic_publication(case, monkeypatch, when):
    root, armed, observation, inventory, payload, prepared = case
    original = capture._publish_directory

    def interrupt(descriptor, staged, target='capture'):
        if target != 'capture':
            return original(descriptor, staged, target)
        if when == 'after':
            original(descriptor, staged, target)
        os._exit(72)

    monkeypatch.setattr(capture, '_publish_directory', interrupt)
    child = os.fork()
    if child == 0:
        try:
            with owned(root) as custody, custody.reserve(armed, digest(armed), **PINS) as ticket:
                if not offer(ticket, observation):
                    os._exit(70)
                ticket.seal(inventory, payload)
        finally:
            os._exit(71)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 72
    with owned(root) as custody:
        with pytest.raises(capture.CaptureError, match='already_reserved'):
            with custody.reserve(armed, digest(armed), **PINS):
                pytest.fail('An interrupted dispatch cannot take a second response')
        with pytest.raises(capture.CaptureError, match='exact_marker'):
            custody.read_prepared(armed, payload, blocked=False, **PINS)
        if when == 'before':
            with pytest.raises(capture.CaptureError):
                custody.read_prepared(prepared, payload, blocked=False, **PINS)
        else:
            # Only the caller's separately proved PREPARED/Inbox pair can read.
            assert custody.read_prepared(prepared, payload, blocked=False, **PINS).body == BODY


def test_no_replace_refuses_even_an_empty_existing_capture_directory(case):
    root, armed, observation, inventory, payload, _ = case
    with owned(root) as custody, custody.reserve(armed, digest(armed), **PINS) as ticket:
        target = root / digest(armed) / 'capture'
        target.mkdir(mode=0o700)
        inode = target.stat().st_ino
        assert offer(ticket, observation)
        with pytest.raises(capture.CaptureError, match='already_sealed'):
            ticket.seal(inventory, payload)
        assert target.stat().st_ino == inode and not list(target.iterdir())


@pytest.mark.parametrize('name', ['reservation.json', 'capture/manifest.json', 'capture/configured-response.html'])
@pytest.mark.parametrize('mutation', ['symlink', 'hardlink', 'identical-replacement', 'missing'])
def test_private_file_alias_or_replacement_refuses(case, name, mutation):
    root, armed, _, _, _, _ = case
    seal(case)
    path = root / digest(armed) / name
    older = root / 'old-file'
    if mutation == 'hardlink':
        os.link(path, older)
    else:
        path.rename(older)
        if mutation == 'symlink':
            path.symlink_to(older)
        elif mutation == 'identical-replacement':
            shutil.copy2(older, path)
    with pytest.raises(capture.CaptureError):
        read(case)


def test_same_inode_body_tamper_and_restoration_refuse(case):
    root, armed, _, _, _, _ = case
    seal(case)
    body = root / digest(armed) / 'capture/configured-response.html'
    inode = body.stat().st_ino
    body.write_bytes(b'different')
    body.write_bytes(BODY)
    assert inode == body.stat().st_ino
    with pytest.raises(capture.CaptureError):
        read(case)


@pytest.mark.parametrize('name', ['slot', 'capture'])
def test_replaced_private_directory_with_identical_files_refuses(case, name):
    root, armed, _, _, _, _ = case
    seal(case)
    path = root / digest(armed)
    if name == 'capture':
        path /= 'capture'
    replaced = root / 'original-directory'
    path.rename(replaced)
    shutil.copytree(replaced, path)
    with pytest.raises(capture.CaptureError):
        read(case)


def test_named_root_swap_does_not_retarget_held_descriptor(case):
    root, armed, observation, inventory, payload, _ = case
    retained = root.with_name('original-root')
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with capture.open_custody(root, descriptor) as custody, custody.reserve(armed, digest(armed), **PINS) as ticket:
            assert offer(ticket, observation)
            root.rename(retained)
            root.mkdir(mode=0o700)
            with pytest.raises(capture.CaptureError, match='root_replaced'):
                ticket.seal(inventory, payload)
        assert not list(root.iterdir()) and not (retained / digest(armed) / 'capture').exists()
    finally:
        os.close(descriptor)


def test_parent_symlink_alias_refuses_even_with_correct_root_fd(case):
    root, _, _, _, _, _ = case
    alias = root / 'ancestor-alias'
    alias.symlink_to(root.parent, target_is_directory=True)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with pytest.raises(capture.CaptureError):
            with capture.open_custody(alias / root.name, descriptor):
                pytest.fail('An ancestor alias must not bind capture custody')
    finally:
        os.close(descriptor)


def test_racing_reservations_grant_one_ticket_on_exact_dispatch(case, monkeypatch):
    root, armed, _, _, _, _ = case
    barrier = Barrier(2)
    original = capture._publish_directory

    def collide(parent, staged, target='capture'):
        barrier.wait(timeout=5)
        return original(parent, staged, target)

    def reserve():
        with owned(root) as custody:
            try:
                with custody.reserve(armed, digest(armed), **PINS):
                    return 'reserved'
            except capture.CaptureError as error:
                return str(error)

    monkeypatch.setattr(capture, '_publish_directory', collide)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(reserve) for _ in range(2)]
        assert sorted(result.result(timeout=10) for result in futures) == ['capture_dispatch_already_reserved', 'reserved']
    assert (root / digest(armed) / 'reservation.json').is_file()
    assert not (root / digest(armed) / 'capture').exists()
