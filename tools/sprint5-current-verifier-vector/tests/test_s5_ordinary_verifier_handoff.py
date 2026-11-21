"""Preserve exact offline handoff pins with no application result writes."""

from contextlib import ExitStack, contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
import socket

import pytest

from job_search_helper import cli, shared_boards
from job_search_helper import ordinary_raw_capture as raw
from job_search_helper import ordinary_verification_pending as pending
from job_search_helper import ordinary_verification_worker as worker
from job_search_helper import ordinary_verifier_handoff as handoff
from job_search_helper.company_events import canonical_company_fact
from job_search_helper.company_sources import REPAIRS
from job_search_helper.repository import RepositoryError
from job_search_helper.sheet_profile import COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository

from test_exact_cycle_recovery import RecordingRemote
from test_ordinary_verification_pending import CYCLE_ID, attempt
from test_ordinary_verification_pending import COMPANY_ID as ORIGINAL_COMPANY_ID
from test_s5_ordinary_publication_continuation import WORKBOOK, measured_scope
from test_s5_ordinary_worker_handoff import local_worker
from test_s5_typed_rippling_mismatch import html, page_state


COMPANY_ID = 'COMP-0066'
COMPANY = {'Company': 'Forterra', 'Company ID': COMPANY_ID, 'Company Status': 'Active',
           'Official Careers URL': 'https://www.forterra.com/careers', 'ATS / Source': 'Rippling'}
DEFAULT_BOARD = 'https://ats.rippling.com/retired-fixture/jobs'
DEFAULT_RESPONSE = html(page_state('other-tenant', total=1))
CORPUS = b'{"schema":"offline-placeholder-for-handoff-tests"}'


def pack(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def use_forterra_source(measured_scope, monkeypatch, board, body):
    launch, state, jobs, inbox = measured_scope
    company_fact = canonical_company_fact(COMPANY)
    revision = pending.digest(company_fact)
    with pending.open_verification_stores(state, jobs, inbox, WORKBOOK, writable_jobs=True) as stores:
        stores.jobs.import_rows('Companies', [(2, COMPANY)])
        cycle = stores.state.cycle(CYCLE_ID)
        item = cycle['companies'].pop(ORIGINAL_COMPANY_ID)
        cycle['companies'][COMPANY_ID] = item
        snapshot = item['installed_source_configuration']
        snapshot.update(company_id=COMPANY_ID, source_revision=revision,
                        official_careers_url=COMPANY['Official Careers URL'], configured_url=board)
        snapshot.pop('configuration_digest')
        snapshot['configuration_digest'] = pending.digest(snapshot)
        item.update(outcome_source_fact=company_fact, outcome_source_revision=revision)
        stores.state.save_cycle(cycle)
    monkeypatch.setattr(worker, '_resolve_authoritative_installed_source_configuration',
                        lambda jobs, company_id: snapshot)
    monkeypatch.setitem(REPAIRS, COMPANY_ID, {
        'company': 'Forterra', 'expected_url': COMPANY['Official Careers URL'],
        'ats': 'Rippling', 'url': board, 'evidence': 'offline handoff fixture',
    })
    monkeypatch.delenv('SSL_CERT_FILE', raising=False)
    monkeypatch.delenv('SSL_CERT_DIR', raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail('the handoff fixture cannot use an external socket')

    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)

    class Response:
        status, headers, url = 200, {}, board

        def read(self, limit):
            return body[:limit]

    class Opener:
        @contextmanager
        def open(self, request, *, timeout):
            assert request.full_url == board
            yield Response()

    monkeypatch.setattr(shared_boards, 'build_opener', lambda *handlers: Opener())
    remote = RecordingRemote([COMPANY], schemas=COMPACT_SCHEMAS)
    remote.spreadsheet_id = WORKBOOK
    monkeypatch.setattr(cli, 'get_remote_repository', lambda **kwargs: remote)
    assert launch(resume=True, resume_cycle_id=CYCLE_ID, capture_ordinary_verification=True,
                  fetch_workers=1, browser_fallback=False) == 0
    assert launch(sync_only=True, sync_cycle_id=CYCLE_ID, sync_company_ids=[COMPANY_ID],
                  publish_ordinary_verification=True) == 0
    assert len(remote.commits) == 1
    return revision


@pytest.fixture
def enrolled(measured_scope, monkeypatch, tmp_path):
    revision = use_forterra_source(measured_scope, monkeypatch, DEFAULT_BOARD, DEFAULT_RESPONSE)
    _, state, jobs, inbox = measured_scope
    root = tmp_path / 'verifier-owner'
    root.mkdir(mode=0o700)
    info = root.stat()
    vector = {'source_manifest_sha256': 'a' * 64, 'config_sha256': 'b' * 64,
              'dependency_manifest_sha256': 'c' * 64}
    pin = pack({'schema': 'company-candidate-validation-pin-v1', 'candidate': vector,
                'measurement_tool_sha256': 'e' * 64, 'capture_sha256': digest(CORPUS),
                'scope': [
                    {'role': 'target', 'company_id': COMPANY_ID, 'authority_url': COMPANY['Official Careers URL'],
                     'source_revision': revision, 'company_row_sha256': pending.digest(COMPANY)},
                    {'role': 'regression', 'board_url': 'https://ats.rippling.com/pdwcareers/jobs'},
                ]})
    with ExitStack() as stack:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, root_fd)
        capture_path = tmp_path / 'private-capture'
        capture_fd = os.open(capture_path, os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, capture_fd)
        capture = stack.enter_context(raw.open_custody(capture_path, capture_fd))
        channel = stack.enter_context(handoff.open_offline_channel(
            root, root_fd, expected_owner_identity=(info.st_dev, info.st_ino), approved_pin_sha256=digest(pin),
        ))
        stores = stack.enter_context(pending.open_verification_stores(state, jobs, inbox, WORKBOOK, readonly=True))
        runtime = stores.state.cycle(CYCLE_ID)['runtime_binding']
        stack.enter_context(cli.writer_lock(state.parent / 'writer.lock'))
        yield channel, root, stores, (stores, runtime, CYCLE_ID, COMPANY_ID, capture), pin, vector


def stage(enrolled, **options):
    channel, _, _, args, pin, _ = enrolled
    return channel.stage(*args, replay_pin=pin, public_capture=CORPUS, **options)


def record_private(slot, name, value):
    path = slot / name
    path.write_bytes(pack(value))
    path.chmod(0o600)


def fixture_verifier_result(enrolled, work, *, result='VERIFIED_MISMATCH', override=None):
    _, _, _, _, _, vector = enrolled
    manifest = json.loads((work.slot / 'owner.json').read_bytes())
    job = manifest['job']
    descriptor = os.open(work.slot / 'verifier.lock', os.O_CREAT | os.O_RDWR, 0o600)
    os.close(descriptor)
    record_private(work.slot, 'reservation.json', manifest['identity'])
    evidence = None if result != 'VERIFIED_MISMATCH' else {
        'configured_observation_sha256': digest(DEFAULT_RESPONSE), 'authority_extraction_digest': '1' * 64,
        'candidate_inventory_digest': '2' * 64, 'regression_inventory_digest': '3' * 64,
        'candidate_vector': vector, 'replay_capture_sha256': digest(CORPUS), 'replay_receipt_sha256': '4' * 64,
    }
    receipt = {'schema': 'ordinary-rippling-verifier-receipt-v1', 'mode': 'offline_saved_captures',
               'identity': manifest['identity'], 'request_limit': job['request_limit'],
               'deadline_unix_ms': job['deadline_unix_ms'], 'result': result,
               'reason': 'exact_pending_observation_and_public_control_verified' if evidence else 'verification_deadline',
               'evidence': evidence, 'requests_used': 4 if evidence else None}
    if override:
        override(receipt)
    record_private(work.slot, 'receipt.json', {'receipt': receipt, 'receipt_sha256': pending.digest(receipt)})
    return deepcopy(receipt)


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_published_capture_to_owned_offline_result_keeps_all_application_rows(enrolled):
    channel, _, stores, args, _, _ = enrolled
    snapshots = tuple(connection.serialize() for connection in
                      (stores.state.connection, stores.jobs.db, stores.inbox.connection))
    work = stage(enrolled)
    assert stage(enrolled) == work
    with pytest.raises(RepositoryError, match='original.*budget'):
        stage(enrolled, request_limit=113)
    assert channel.read_result(*args) is None
    receipt = fixture_verifier_result(enrolled, work)
    result = channel.read_result(*args)
    assert result['receipt'] == receipt
    assert result['application_authority'] is False and result['mode'] == 'offline_saved_captures'
    assert channel.read_result(*args) == result
    assert work.pending_sha256 == digest((work.slot / 'pending.json').read_bytes())
    assert work.job_sha256 == digest((work.slot / 'job.json').read_bytes())
    assert snapshots == tuple(connection.serialize() for connection in
                              (stores.state.connection, stores.jobs.db, stores.inbox.connection))


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
@pytest.mark.parametrize('field', ['mode', 'identity', 'candidate_vector', 'replay_capture_sha256'])
def test_changed_receipts_are_held_even_if_checksum_is_rebuilt(enrolled, field):
    channel, _, _, args, _, _ = enrolled
    work = stage(enrolled)

    def change(receipt):
        if field in {'mode', 'identity'}:
            receipt[field] = 'changed'
        else:
            receipt['evidence'][field] = '5' * 64

    fixture_verifier_result(enrolled, work, override=change)
    with pytest.raises(RepositoryError, match='frozen job|approved replay'):
        channel.read_result(*args)


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_named_owner_root_replacement_holds_even_with_identical_request(enrolled):
    channel, root, _, args, _, _ = enrolled
    stage(enrolled)
    root.rename(root.with_name('retired-owner'))
    root.mkdir(mode=0o700)
    with pytest.raises(RepositoryError, match='directory was replaced'):
        channel.read_result(*args)


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_cut_after_durable_bundle_resumes_only_the_original_budget(enrolled, monkeypatch):
    channel, root, _, args, _, _ = enrolled
    publish = raw._publish_directory

    def interrupted(*args):
        publish(*args)
        raise RuntimeError('after atomic publication')

    with monkeypatch.context() as cut:
        cut.setattr(raw, '_publish_directory', interrupted)
        with pytest.raises(RuntimeError, match='after atomic publication'):
            stage(enrolled)
    slots = list(root.iterdir())
    assert len(slots) == 1
    original = (slots[0] / 'job.json').read_bytes()
    assert stage(enrolled).job_sha256 == digest(original)
    assert channel.read_result(*args) is None
    assert (slots[0] / 'job.json').read_bytes() == original


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_receipt_is_pending_until_the_supervisor_releases_its_private_lease(enrolled):
    channel, _, _, args, _, _ = enrolled
    work = stage(enrolled)
    expected = fixture_verifier_result(enrolled, work)
    descriptor = os.open(work.slot / 'verifier.lock', os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert channel.read_result(*args) is None
    finally:
        os.close(descriptor)
    assert channel.read_result(*args)['receipt'] == expected


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_lost_slot_cannot_be_recreated_under_the_retained_owner_record(enrolled, tmp_path):
    _, root, _, _, _, _ = enrolled
    work = stage(enrolled)
    fixture_verifier_result(enrolled, work)
    work.slot.rename(tmp_path / 'retired-verifier-work')
    assert (root / (work.slot.name + '.json')).is_file()
    with pytest.raises(RepositoryError, match='missing and cannot be replaced'):
        stage(enrolled)
    assert not work.slot.exists()


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_existing_slot_with_prior_supervisor_cannot_adopt_a_missing_owner_record(enrolled):
    channel, root, _, args, _, _ = enrolled
    work = stage(enrolled)
    fixture_verifier_result(enrolled, work)
    (root / (work.slot.name + '.json')).unlink()
    with pytest.raises(RepositoryError, match='unanchored.*prior supervisor'):
        stage(enrolled)
    with pytest.raises(RepositoryError, match='owner record differs'):
        channel.read_result(*args)


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_new_verifier_vector_cannot_restage_an_old_owned_job(enrolled, monkeypatch):
    channel, root, _, args, _, _ = enrolled
    with monkeypatch.context() as old:
        old.setattr(handoff, '_VERIFIER', 'f218ed98eb0991e72c78b7ddaaf67dcde41f48b6a3d472e171cc5e26b2de1164')
        old.setattr(handoff, '_TOOLS', '1715233f4e8988c08d69cf9c00674d29add135efe22b5e232eb3fff2f842b866')
        original = stage(enrolled)
    manifest = original.slot / 'owner.json'
    owner_anchor = root / (original.slot.name + '.json')
    original_bytes = manifest.read_bytes(), owner_anchor.read_bytes()
    with pytest.raises(RepositoryError, match='saved offline verifier files differ'):
        stage(enrolled)
    with pytest.raises(RepositoryError, match='saved offline verifier files differ'):
        channel.read_result(*args)
    assert original_bytes == (manifest.read_bytes(), owner_anchor.read_bytes())
    assert not (original.slot / 'reservation.json').exists()
