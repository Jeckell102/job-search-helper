"""Read the exact, already published Forterra dispatch for an issuance enrollment."""

from hashlib import sha256
import sqlite3

from . import ordinary_live_issuance_slot as slots
from . import ordinary_raw_capture as private
from . import ordinary_verification_pending as pending
from . import ordinary_verification_worker as worker
from .company_events import source_revision
from .ordinary_verification_outcome import existing_outcome
from .ordinary_verification_publication import _require_owned_leases
from .ordinary_verification_publisher import read_captured_ordinary_response
from .ordinary_verification_terminal import TERMINAL, _published_marker
from .ordinary_verifier_handoff import _binding
from .repository import RepositoryError
from .scan_request import superseded_cycle_ids


_SCHEMA = 'ordinary-live-issuance-enrollment-v1'
_TARGET = 'COMP-0066'
_CONTROL = 'COMP-0178'
_COMPANIES = {
    _TARGET: (('Forterra',), 'https://www.forterra.com/careers'),
    _CONTROL: (('PDW', 'Performance Drone Works (PDW)'), 'https://www.pdw.ai/careers'),
}
_TOOL_DIGESTS = {
    'reviewed_tools_sha256', 'collector_policy_sha256', 'worker_source_sha256', 'measurement_tool_sha256',
}
_COMPANY_DIGESTS = {
    'company_projection_sha256', 'company_source_revision',
    'control_projection_sha256', 'control_source_revision',
}
_SCOPE_DIGESTS = _COMPANY_DIGESTS | {
    'dispatch_sha256', 'publication_sha256', 'raw_capture_manifest_sha256',
    'runtime_binding_sha256', 'store_binding_sha256',
}


def _require(condition, reason):
    if not condition:
        raise RepositoryError(reason)


def _fresh(deadline):
    _require(0 < deadline - slots._now_ms() <= slots._MAX_DURATION_MS,
             'The approved live issuance deadline is expired or outside the short window.')


def _approval(raw, expected_sha256):
    _require(type(raw) is bytes and 0 < len(raw) <= 4096 and private._is_digest(expected_sha256)
             and sha256(raw).hexdigest() == expected_sha256,
             'An independent exact live issuance approval is required.')
    value = private._decode(raw)
    _require(set(value) == _TOOL_DIGESTS | slots._LIMITS.keys()
             | {'schema', 'scope', 'candidate', 'deadline_unix_ms'} and value['schema'] == _SCHEMA,
             'The live issuance approval has the wrong schema.')
    scope, candidate = value['scope'], value['candidate']
    _require(type(scope) is dict and set(scope) == _SCOPE_DIGESTS | {'cycle_id', 'request_id'}
             and all(type(scope[key]) is str and 0 < len(scope[key]) <= 256 and scope[key] == scope[key].strip()
                     for key in ('cycle_id', 'request_id'))
             and all(private._is_digest(scope[key]) for key in _SCOPE_DIGESTS)
             and type(candidate) is dict and set(candidate) == slots._CANDIDATE_DIGESTS
             and all(private._is_digest(pin) for pin in candidate.values())
             and all(private._is_digest(value[key]) for key in _TOOL_DIGESTS)
             and type(value['deadline_unix_ms']) is int and 0 < value['deadline_unix_ms'] < 2**63
             and all(type(value[key]) is int and 0 < value[key] <= maximum
                     for key, maximum in slots._LIMITS.items()),
             'The approved issuance scope, reference candidate, tools, or limits are malformed.')
    _fresh(value['deadline_unix_ms'])
    return value


def _company_pins(stores, company_id, *, own_cycle=None):
    projection = pending._company_row(stores, company_id)
    current = worker.OrdinaryVerificationHandoff._current_company(stores, company_id)
    names, authority = _COMPANIES[company_id]
    _require(projection['Company'] in names and projection['Official Careers URL'] == authority
             and all(current.get(key) == value for key, value in projection.items())
             and current.get('Active Cycle ID') in (None, '', own_cycle),
             'The current Forterra or PDW Company is held or outside the approved projection.')
    return pending.digest(projection), source_revision(projection)


def _live_scope(stores, cycle, marker):
    _require(cycle['id'] not in superseded_cycle_ids(stores.state.cycles()),
             'The selected ordinary verification cycle was superseded.')
    target, source = _company_pins(stores, _TARGET, own_cycle=cycle['id'])
    control, control_source = _company_pins(stores, _CONTROL)
    item = cycle['companies'][_TARGET]
    _require(TERMINAL not in item, 'The selected dispatch already has terminal outcome evidence.')
    snapshot = item.get('installed_source_configuration')
    current = worker._resolve_authoritative_installed_source_configuration(stores.jobs, _TARGET)
    qualification = worker.qualification_for_snapshot(current)
    _require(current is not None and current == snapshot and qualification is not None
             and qualification['matrix_digest'] == marker['admission']['matrix_digest'],
             'The installed Forterra source or its qualification changed.')
    return {
        'company_projection_sha256': target, 'company_source_revision': source,
        'control_projection_sha256': control, 'control_source_revision': control_source,
    }


def snapshot_live_issuance_binding(state_path, jobs_path, inbox_path, workbook_id, *,
                                  runtime, capture, approval_bytes, approved_sha256):
    """Return the slot binding using existing stores opened in SQLite read-only mode.

    The application owner supplies a freshly measured runtime, its enrolled capture
    custody, and the independent approval digest from trusted configuration. The
    caller holds the ordinary scraper and writer leases for the complete call.
    Candidate and tool digests are approved inputs for later independent measurement.
    This readback does not grant a reservation, enroll a row, or approve a verdict.
    """
    try:
        approval = _approval(approval_bytes, approved_sha256)
        scope = approval['scope']
        _require(type(runtime) is dict and pending.digest(runtime) == scope['runtime_binding_sha256']
                 and type(capture) is private.CaptureCustody,
                 'The admitted runtime or configured raw capture custody differs from approval.')
        cycle_id = scope['cycle_id']
        with pending.open_verification_stores(state_path, jobs_path, inbox_path, workbook_id, readonly=True) as stores:
            selected, captured, publication_sha256 = _binding(stores, runtime, cycle_id, _TARGET, capture)
            cycle, original, marker, publication = _published_marker(stores, cycle_id, _TARGET)
            owner = marker['owner']
            _require({key: marker[key] for key in selected} == selected
                     and pending.digest(publication) == publication_sha256
                     and marker['dispatch_sha256'] == captured.dispatch_sha256
                     and marker['inventory_sha256'] == captured.inventory_sha256
                     and marker['admission']['capability_id'] == 'rippling-shared-v1',
                     'The selected archived publication or terminal capture changed.')
            company_pins = _live_scope(stores, cycle, marker)
            observed = {
                'cycle_id': cycle_id, 'request_id': owner['request_id'],
                'dispatch_sha256': captured.dispatch_sha256, 'publication_sha256': publication_sha256,
                'raw_capture_manifest_sha256': captured.manifest_sha256,
                'runtime_binding_sha256': pending.digest(runtime),
                'store_binding_sha256': owner['store_binding_sha256'], **company_pins,
            }
            _require(observed == scope, 'The actual dispatch, evidence, or Company projections differ from approval.')
            _require(_published_marker(stores, cycle_id, _TARGET)[1:] == (original, marker, publication)
                     and _live_scope(stores, cycle, marker) == company_pins
                     and read_captured_ordinary_response(stores, cycle_id, _TARGET, capture) == captured,
                     'The exact application issuance inputs changed during readback.')
            _require(existing_outcome(stores.jobs, owner) is None,
                     'The enrolled scrape already has its immutable outcome.')
            _require_owned_leases(stores)
        _fresh(approval['deadline_unix_ms'])
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise RepositoryError('The exact live issuance enrollment could not be verified.') from exc

    return {
        **{key: observed[key] for key in _SCOPE_DIGESTS & slots._BINDING_DIGESTS},
        'verifier_input_sha256': pending.digest(selected),
        'raw_response_sha256': captured.response_sha256,
        'inventory_sha256': captured.inventory_sha256,
        **{key: approval[key] for key in _TOOL_DIGESTS | slots._LIMITS.keys()
           | {'candidate', 'deadline_unix_ms'}},
    }
