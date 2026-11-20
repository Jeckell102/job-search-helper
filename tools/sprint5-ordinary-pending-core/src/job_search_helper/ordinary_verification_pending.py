"""State-first handoff for one enrolled ordinary company-only verification."""

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

from .ats import validate_outcome_failure
from .company_events import canonical_company_fact
from .repository import RepositoryError, _url
from .runtime_mapping_facts import _open_store, _store_identity
from .source_configuration_snapshot import _duplicate_free_json, validate_installed_source_configuration


MARKER = "ordinary_verification_pending"
SCHEMA = "ordinary-rippling-verification-pending-v1"
_DIGEST = re.compile(r"[a-f0-9]{64}")
_OWNER_FIELDS = {
    "cycle_id", "cycle_started_at", "request_id", "request_fingerprint",
    "company_id", "source_revision", "company_source_sha256",
    "store_binding_sha256", "observation_generation",
}
_ADMISSION_FIELDS = {
    "authority_url", "configured_url", "capability_id", "capability_digest",
    "mapping_digest", "configuration_digest", "matrix_digest", "runtime_binding_sha256",
}
_OBSERVATION_FIELDS = {
    "schema", "configured_url", "expected_slug", "observed_slug", "response_sha256",
}
_OTHER_ROUTES = (
    "company_event", "operator_request", "repair_retry", "temporary_retry",
    "recovery_pause", "selected_retry_reservation_sha256",
)


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class VerificationStores:
    state: object
    jobs: object
    inbox: object


@contextmanager
def open_verification_stores(state_path, jobs_path, inbox_path, workbook_id):
    """Open the existing local stores under the caller's measured owner leases."""
    from .engine import State
    from .inbox import InventoryInbox
    from .sqlite_repository import SQLiteRepository

    state_path, jobs_path, inbox_path = (
        Path(path).absolute() for path in (state_path, jobs_path, inbox_path)
    )
    if len({state_path, jobs_path, inbox_path}) != 3 or len({
        state_path.parent, jobs_path.parent, inbox_path.parent,
    }) != 1:
        raise RepositoryError("Verification requires co-located, distinct State, Jobs and Inbox.")
    with ExitStack() as stack:
        stores = VerificationStores(
            state=_open_store(stack, state_path, State, "connection"),
            jobs=_open_store(stack, jobs_path,
                             lambda path: SQLiteRepository(path, workbook_id, readonly=True), "db"),
            inbox=_open_store(stack, inbox_path,
                              lambda path: InventoryInbox(path, workbook_id), "connection"),
        )
        store_binding(stores)
        yield stores


def store_binding(stores):
    """Remeasure the descriptor-bound physical stores and their workbook."""
    identities = {}
    for name, store, connection in (
        ("state", stores.state, stores.state.connection),
        ("jobs", stores.jobs, stores.jobs.db),
        ("inbox", stores.inbox, stores.inbox.connection),
    ):
        if connection.in_transaction:
            raise RepositoryError("Ordinary verification requires idle SQLite connections.")
        try:
            busy = connection.execute("SELECT count(*) FROM main.sqlite_stmt WHERE busy").fetchone()
            path, identity = _store_identity(store, connection)
        except (OSError, ValueError, sqlite3.Error) as exc:
            raise RepositoryError("Ordinary verification store custody changed or is unavailable.") from exc
        if busy != (1,):
            raise RepositoryError("Ordinary verification requires idle SQLite statements.")
        identities[name] = {"path": str(path), "identity": identity}
    workbook = stores.jobs.spreadsheet_id
    if (stores.jobs.db.execute(
        "SELECT value FROM main.meta WHERE key='spreadsheet_id'"
    ).fetchall() != [(workbook,)] or stores.inbox.connection.execute(
        "SELECT id FROM main.destination"
    ).fetchall() != [(workbook,)]):
        raise RepositoryError("Ordinary verification stores do not have the same workbook destination.")
    return digest({"stores": identities, "workbook_sha256": sha256(workbook.encode("utf-8")).hexdigest()})


def _check_stores(stores, owner):
    if store_binding(stores) != owner["store_binding_sha256"]:
        raise RepositoryError("The current stores differ from the original ordinary verification enrollment.")


_COMPANY_ROW_FIELDS = ("Company ID", "Company", "Company Status",
                       "Official Careers URL", "ATS / Source")


def _company_row(stores, company_id):
    repository = stores.jobs
    if repository.db.execute(
        "SELECT 1 FROM temp.sqlite_master WHERE name COLLATE NOCASE IN ('records','lookups') LIMIT 1"
    ).fetchone() is not None:
        raise RepositoryError("The Jobs Company authority is shadowed.")
    definitions = repository.db.execute(
        "SELECT name,type FROM main.sqlite_master WHERE name COLLATE NOCASE IN ('records','lookups')"
    ).fetchall()
    if set(definitions) != {("records", "table"), ("lookups", "table")}:
        raise RepositoryError("The main Jobs Company relations are unavailable.")
    match = repository.matches("Companies", {"Company ID": company_id})
    if len(match) != 1:
        raise RepositoryError("The owned Jobs store must contain one enrolled Company.")
    row = match[0][1]
    projection = {key: row.get(key) for key in _COMPANY_ROW_FIELDS}
    if (projection["Company ID"] != company_id or projection["Company Status"] != "Active"
            or projection["ATS / Source"] != "Rippling"
            or any(not isinstance(value, str) or not value or value != value.strip()
                   for value in projection.values())):
        raise RepositoryError("The current Jobs Company row is outside the exact reviewed projection.")
    return projection


def company_source_sha256(stores, company_id):
    """Hash the literal reviewed Company projection used by the offline verifier."""
    store_binding(stores)
    return digest(_company_row(stores, company_id))


def _check_company(stores, cycle, owner):
    company_id = owner["company_id"]
    row = _company_row(stores, company_id)
    item = _item(cycle, company_id)
    if (digest(row) != owner["company_source_sha256"] or row["Company"] != item.get("company")
            or canonical_company_fact(row) != item.get("outcome_source_fact")):
        raise RepositoryError("The current Jobs Company row differs from its exact enrolled source.")


def _is_digest(value):
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _item(cycle, company_id):
    companies = cycle.get("companies")
    if not isinstance(companies, dict) or not isinstance(companies.get(company_id), dict):
        raise RepositoryError("The ordinary verification Company is absent from the saved cycle.")
    return companies[company_id]


def _scope(cycle, company_id, owner, admission):
    item = _item(cycle, company_id)
    if (not isinstance(owner, dict) or set(owner) != _OWNER_FIELDS
            or not isinstance(admission, dict) or set(admission) != _ADMISSION_FIELDS):
        raise RepositoryError("Malformed ordinary verification enrollment.")
    if (cycle.get("all") is not False or len(cycle["companies"]) != 1
            or any(cycle.get(key) is not None for key in _OTHER_ROUTES)
            or any(not isinstance(owner[key], str) or not owner[key].strip()
                   for key in ("cycle_id", "cycle_started_at", "request_id", "company_id"))
            or type(owner["observation_generation"]) is not int
            or owner["observation_generation"] < 1
            or not all(_is_digest(owner[key]) for key in (
                "request_fingerprint", "source_revision", "company_source_sha256", "store_binding_sha256"))):
        raise RepositoryError("Ordinary verification requires one exact enrolled attempt.")
    fact = item.get("outcome_source_fact")
    source = validate_installed_source_configuration(item.get("installed_source_configuration"))
    runtime = cycle.get("runtime_binding")
    if (owner["cycle_id"] != cycle.get("id") or owner["cycle_started_at"] != cycle.get("started_at")
            or owner["request_id"] != cycle.get("start_request_id")
            or owner["request_fingerprint"] != cycle.get("request_fingerprint")
            or owner["company_id"] != company_id
            or owner["source_revision"] != item.get("outcome_source_revision")
            or not isinstance(fact, dict) or not fact.get("eligible")
            or owner["source_revision"] != digest(fact)
            or source is None or source["company_id"] != company_id
            or source["source_revision"] != owner["source_revision"]
            or source["company"] != item.get("company")
            or source["official_careers_url"] != fact.get("official_careers_url")
            or source["ats_source"] != fact.get("ats_source")
            or not all(admission[key] == source[key] for key in (
                "configured_url", "capability_id", "capability_digest",
                "mapping_digest", "configuration_digest"))
            or admission["authority_url"] != source["official_careers_url"]
            or not _is_digest(admission["matrix_digest"])
            or not isinstance(runtime, dict) or not runtime
            or admission["runtime_binding_sha256"] != digest(runtime)):
        raise RepositoryError("The ordinary verification attempt no longer matches its frozen scope.")


def _validate_observation(observation, admission):
    if observation is None:
        return
    if (not isinstance(observation, dict) or set(observation) != _OBSERVATION_FIELDS
            or observation["schema"] != "rippling-tenant-mismatch-v1"
            or observation["configured_url"] != admission["configured_url"]
            or not _is_digest(observation["response_sha256"])
            or any(not isinstance(observation[key], str)
                   or not re.fullmatch(r"[a-z0-9-]{1,128}", observation[key])
                   for key in ("expected_slug", "observed_slug"))
            or observation["expected_slug"] == observation["observed_slug"]
            or admission["configured_url"].split("/")[-2] != observation["expected_slug"]):
        raise RepositoryError("Malformed typed Rippling observation for the enrolled attempt.")


def read_marker(cycle, company_id):
    """Return the closed marker or raise if the checkpoint is malformed."""
    item = _item(cycle, company_id)
    if MARKER not in item:
        return None
    record = item[MARKER]
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise RepositoryError("Malformed ordinary verification marker.")
    fields = {"schema", "state", "owner", "admission"}
    if record.get("state") == "PREPARED":
        fields |= {"dispatch_sha256", "inventory_sha256", "observation", "failure"}
    elif record.get("state") != "ARMED":
        raise RepositoryError("Unknown ordinary verification marker state.")
    if set(record) != fields:
        raise RepositoryError("Unexpected ordinary verification marker fields.")
    _scope(cycle, company_id, record["owner"], record["admission"])
    if record["state"] == "PREPARED":
        _validate_observation(record["observation"], record["admission"])
        if (record["dispatch_sha256"] != _dispatch_sha256(record)
                or not _is_digest(record["inventory_sha256"])
                or (record["failure"] is not None
                    and validate_outcome_failure(record["failure"]) != record["failure"])
                or (record["failure"] is not None and record["observation"] is not None)):
            raise RepositoryError("Malformed ordinary verification inventory handoff.")
    return record


def _dispatch_sha256(marker):
    return digest({"schema": SCHEMA, "state": "ARMED", "owner": marker["owner"],
                   "admission": marker["admission"]})


def _read_cycle(state, cycle_id):
    row = state.connection.execute("SELECT data FROM main.cycles WHERE id=?", (cycle_id,)).fetchone()
    if row is None:
        raise RepositoryError("The ordinary verification cycle is missing.")
    cycle = _duplicate_free_json(row[0].encode("utf-8"))
    if not isinstance(cycle, dict) or cycle.get("id") != cycle_id:
        raise RepositoryError("The ordinary verification cycle identity changed.")
    return cycle, row[0]


def _replace_marker(state, cycle, original, company_id, marker):
    if state.readonly or state.connection.in_transaction:
        raise RepositoryError("Ordinary verification requires an idle writable State checkpoint.")
    _item(cycle, company_id)[MARKER] = marker
    encoded = json.dumps(cycle, ensure_ascii=False, allow_nan=False)
    with state.connection:
        updated = state.connection.execute(
            "UPDATE main.cycles SET data=? WHERE id=? AND data=?",
            (encoded, cycle["id"], original),
        )
        if updated.rowcount != 1:
            raise RepositoryError("The owning cycle changed before its verification checkpoint.")
    fresh, _ = _read_cycle(state, cycle["id"])
    if read_marker(fresh, company_id) != marker:
        raise RepositoryError("The owning verification checkpoint did not read back exactly.")
    return fresh


def arm(stores, owner, admission):
    """Freeze the separately approved single owner before assigning its fetch."""
    _check_stores(stores, owner)
    state, inbox = stores.state, stores.inbox
    cycle_id, company_id = owner["cycle_id"], owner["company_id"]
    cycle, original = _read_cycle(state, cycle_id)
    _scope(cycle, company_id, owner, admission)
    _check_company(stores, cycle, owner)
    marker = {"schema": SCHEMA, "state": "ARMED", "owner": owner, "admission": admission}
    existing = read_marker(cycle, company_id)
    if (_item(cycle, company_id).get("stage") != "queued" or cycle.get("status") != "In Progress"
            or inbox.get(cycle_id, company_id) is not None
            or inbox.plan(cycle_id, company_id) is not None):
        raise RepositoryError("Ordinary verification enrollment cannot adopt existing inventory or plan work.")
    if existing is not None:
        if existing != marker or _read_cycle(state, cycle_id)[1] != original:
            raise RepositoryError("Ordinary verification enrollment already owns saved work.")
        return cycle
    return _replace_marker(state, cycle, original, company_id, marker)


def dispatch_sha256(cycle, company_id):
    """Carry the exact armed ownership into the queued fetch assignment."""
    marker = read_marker(cycle, company_id)
    if marker is None or marker["state"] != "ARMED":
        raise RepositoryError("The fetch assignment is missing exact ordinary verification enrollment.")
    return _dispatch_sha256(marker)


def _matches_inventory(marker, stored):
    if stored is None or digest(stored[0]) != marker["inventory_sha256"]:
        raise RepositoryError("The saved ordinary inventory does not match its prepared handoff.")
    return stored


def read_prepared_inventory(stores, cycle_id, company_id):
    """Read the only inventory this enrolled attempt may resume."""
    state, inbox = stores.state, stores.inbox
    cycle, _ = _read_cycle(state, cycle_id)
    marker = read_marker(cycle, company_id)
    if marker is None or marker["state"] != "PREPARED":
        raise RepositoryError("There is no prepared ordinary inventory handoff to resume.")
    _check_stores(stores, marker["owner"])
    _check_company(stores, cycle, marker["owner"])
    stored = _matches_inventory(marker, inbox.get(cycle_id, company_id))
    current, _ = _read_cycle(state, cycle_id)
    if read_marker(current, company_id) != marker:
        raise RepositoryError("The prepared ordinary inventory handoff changed during readback.")
    _check_stores(stores, marker["owner"])
    _check_company(stores, current, marker["owner"])
    return current, stored


def prepare_inventory(stores, cycle_id, company_id, payload, *,
                      dispatch_digest, observation, failure):
    """Record the final payload hash before saving the unchanged inventory once."""
    state, inbox = stores.state, stores.inbox
    cycle, original = _read_cycle(state, cycle_id)
    marker = read_marker(cycle, company_id)
    if marker is None or dispatch_digest != _dispatch_sha256(marker):
        raise RepositoryError("Ordinary verification inventory does not belong to the frozen dispatch.")
    _check_stores(stores, marker["owner"])
    _check_company(stores, cycle, marker["owner"])
    _validate_observation(observation, marker["admission"])
    if (not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list)
            or (failure is not None and validate_outcome_failure(failure) != failure)):
        raise RepositoryError("Malformed final ordinary inventory handoff.")
    try:
        requested = _url(payload.get("requested_url", ""))
    except (TypeError, ValueError) as exc:
        raise RepositoryError("Ordinary verification inventory has a malformed requested source.") from exc
    if requested != marker["admission"]["authority_url"]:
        raise RepositoryError("Ordinary verification inventory belongs to a different requested source.")
    if observation is not None and (
        failure is not None or payload["jobs"] or payload.get("inventory_status") != "partial"
        or payload.get("ats") != "Rippling" or payload.get("browser_pending_urls")
        or payload.get("browser_discovery_incomplete")
    ):
        raise RepositoryError("Typed Rippling mismatch conflicts with final inventory precedence.")
    prepared = {**marker, "state": "PREPARED", "dispatch_sha256": dispatch_digest,
                "inventory_sha256": digest(payload), "observation": observation, "failure": failure}
    if marker["state"] == "PREPARED":
        if marker != prepared:
            raise RepositoryError("Ordinary verification inventory handoff changed.")
    else:
        if inbox.get(cycle_id, company_id) is not None or inbox.plan(cycle_id, company_id) is not None:
            raise RepositoryError("Unbound inventory or plan exists beside the armed verification marker.")
        _replace_marker(state, cycle, original, company_id, prepared)
        inbox.save(cycle_id, company_id, payload)
    current, _ = read_prepared_inventory(stores, cycle_id, company_id)
    if read_marker(current, company_id) != prepared:
        raise RepositoryError("The final ordinary inventory no longer matches the original dispatch.")
    return current


def verifier_payload(stores, cycle_id, company_id):
    """Extract the exact verifier input only after the enrolled inventory was saved."""
    cycle, (_, blocked) = read_prepared_inventory(stores, cycle_id, company_id)
    if blocked:
        raise RepositoryError("Blocked ordinary inventory cannot be exported for verification.")
    marker = read_marker(cycle, company_id)
    if marker["observation"] is None:
        raise RepositoryError("There is no typed enrolled Rippling mismatch to verify.")
    return {key: marker[key] for key in ("schema", "owner", "admission", "observation")}
