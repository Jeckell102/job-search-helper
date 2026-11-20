"""Immutable containment for an unfinished historical cycle.

This component does not settle, archive, block, publish, or advance retained
work.  It only freezes evidence which a separately reviewed Company-only
admission boundary may discount as a scheduler blocker for one disjoint new
Company.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Mapping
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit


VERSION = "retained-work-exception-v1"
ACTION = "activate-retained-work-exception-v1"
ACTIVE = "ACTIVE"
CORE_INVENTORY_TABLES = ("inventories", "sync_plans")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _digest_text(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _name(value):
    return " ".join(str(value or "").split()).casefold()


def _url(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("retained_exception_company_url_invalid")
    path = parsed.path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), path,
                       query, ""))


def _endpoint(value):
    """Canonical source identity that cannot be changed by query decoration."""
    normalized = _url(value)
    if not normalized:
        return ""
    parsed = urlsplit(normalized)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("retained_exception_company_url_invalid") from error
    host = (parsed.hostname or "").casefold()
    if port is not None and not ((parsed.scheme == "https" and port == 443)
                                 or (parsed.scheme == "http" and port == 80)):
        host += ":" + str(port)
    # Percent-encoding and case changes must not create a second provider-board
    # identity.  This deliberately prefers a safe false alias over admission.
    path = quote(unquote(parsed.path).casefold(),
                 safe="/:@!$&'()*+,;=-._~").rstrip("/") or "/"
    return urlunsplit((parsed.scheme, host, path, "", ""))


def _provider_identity(ats, source_url):
    """Derive a provider-board identity from trusted current source evidence."""
    provider = _name(ats)
    endpoint = _endpoint(source_url)
    if not endpoint:
        return ""
    parsed = urlsplit(endpoint)
    host = parsed.netloc
    segments = [part.casefold() for part in parsed.path.split("/") if part]
    board = ""
    if provider == "ashby" or host.endswith("ashbyhq.com"):
        if "job-board" in segments and segments.index("job-board") + 1 < len(segments):
            board = segments[segments.index("job-board") + 1]
        elif segments:
            board = segments[0]
        if board:
            return "ashby:" + board
    if provider == "greenhouse" or host.endswith("greenhouse.io"):
        if "boards" in segments and segments.index("boards") + 1 < len(segments):
            board = segments[segments.index("boards") + 1]
        elif segments:
            board = segments[0]
        if board:
            return "greenhouse:" + board
    if provider == "lever" or host.endswith("lever.co"):
        if "postings" in segments and segments.index("postings") + 1 < len(segments):
            board = segments[segments.index("postings") + 1]
        elif segments:
            board = segments[0]
        if board:
            return "lever:" + board
    return provider + ":" + endpoint


def canonical_admitted_company_identity(current_company):
    """Return the exact normalized identity protected by an admission.

    The caller supplies the Company fields whose source/provider values came
    from the frozen provider inventory.  Keeping this derivation here makes
    reservation and later readback use the same canonical form rather than
    trusting a caller-provided digest.
    """
    required = {"company_id", "company_name", "official_careers_url",
                "source_url", "ats", "source_revision", "company_status",
                "claimed_by", "claim_token"}
    if (not isinstance(current_company, Mapping)
            or set(current_company) != required):
        raise ValueError("retained_exception_current_company_invalid")
    if any(not isinstance(current_company[key], str)
           for key in required):
        raise ValueError("retained_exception_current_company_invalid")
    try:
        official_url = _url(current_company["official_careers_url"])
        source_url = _url(current_company["source_url"])
    except ValueError as error:
        raise ValueError("retained_exception_current_company_invalid") from error
    company_id = current_company["company_id"].strip()
    source_revision = current_company["source_revision"].strip()
    provider = current_company["ats"].strip()
    if (not company_id or not source_revision or not _name(current_company["company_name"])
            or not official_url or not source_url or not provider):
        raise ValueError("retained_exception_current_company_invalid")
    return {
        "company_id": company_id,
        "company_name": _name(current_company["company_name"]),
        "official_careers_url": official_url,
        "source_url": source_url,
        "source_endpoint": _endpoint(source_url),
        "ats": _name(provider),
        "provider_identity": _provider_identity(provider, source_url),
        "source_revision": source_revision,
        "company_status": current_company["company_status"].strip().casefold(),
        "claimed_by": current_company["claimed_by"].strip(),
        "claim_token": current_company["claim_token"].strip(),
    }


def _readonly(path):
    location = Path(path).resolve()
    if not location.is_file():
        raise ValueError("retained_exception_database_missing")
    connection = sqlite3.connect(location.as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _json_value(value):
    if isinstance(value, bytes):
        return {"blob_sha256": hashlib.sha256(value).hexdigest(),
                "blob_length": len(value)}
    return value


def _table_records(connection, table, cycle_id):
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if table not in tables:
        return None
    columns = [row[1] for row in connection.execute(
        'PRAGMA table_info("%s")' % table.replace('"', '""'))]
    if "cycle" not in columns:
        raise ValueError("retained_exception_cycle_column_missing")
    quoted = '"%s"' % table.replace('"', '""')
    index = columns.index("cycle")
    rows = []
    for raw in connection.execute("SELECT * FROM %s WHERE cycle=?" % quoted,
                                  (cycle_id,)).fetchall():
        if raw[index] != cycle_id:
            raise ValueError("retained_exception_cycle_scope_changed")
        normalized = [_json_value(value) for value in raw]
        rows.append({"row_digest": digest(normalized)})
    return {"columns": columns, "row_count": len(rows),
            "rows_digest": digest(sorted(item["row_digest"] for item in rows))}


def _cycle_tables(connection, cycle_id):
    result = {}
    for (table,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        columns = [row[1] for row in connection.execute(
            'PRAGMA table_info("%s")' % table.replace('"', '""'))]
        if "cycle" in columns:
            result[table] = _table_records(connection, table, cycle_id)
    if any(table not in result for table in CORE_INVENTORY_TABLES):
        raise ValueError("retained_exception_core_table_missing")
    if result["inventories"]["row_count"] < 1:
        raise ValueError("retained_exception_inventory_missing")
    if result["sync_plans"]["row_count"] < 1:
        raise ValueError("retained_exception_plan_missing")
    return result


def _receipt_records(connection, cycle_id):
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "publication_receipts" not in tables:
        return {"columns": [], "row_count": 0, "rows_digest": digest([])}
    columns = [row[1] for row in connection.execute(
        "PRAGMA table_info(publication_receipts)")]
    referenced = set()
    if "exact_remote_plans" in tables:
        remote_columns = [row[1] for row in connection.execute(
            "PRAGMA table_info(exact_remote_plans)")]
        if {"cycle", "receipt_id"} <= set(remote_columns):
            referenced.update(str(row[0]) for row in connection.execute(
                "SELECT receipt_id FROM exact_remote_plans WHERE cycle=?",
                (cycle_id,)).fetchall() if str(row[0] or ""))
    rows = []
    binding_index = columns.index("binding")
    for raw in connection.execute("SELECT * FROM publication_receipts").fetchall():
        try:
            binding = json.loads(raw[binding_index])
        except (TypeError, ValueError) as error:
            raise ValueError("retained_exception_receipt_corrupt") from error
        receipt_id = str(raw[columns.index("receipt_id")] or "")
        if ((isinstance(binding, dict) and binding.get("cycle_id") == cycle_id)
                or receipt_id in referenced):
            rows.append(digest([_json_value(value) for value in raw]))
    return {"columns": columns, "row_count": len(rows),
            "rows_digest": digest(sorted(rows))}


def _job_evidence(connection, cycle_id):
    dirty = connection.execute("SELECT count(*) FROM dirty").fetchone()[0]
    if dirty != 0:
        raise ValueError("retained_exception_dirty_cells_present")
    applications = _table_records(connection, "exact_local_applications", cycle_id)
    apply_ids = []
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if applications is not None and "exact_local_applications" in tables:
        apply_ids = [row[0] for row in connection.execute(
            "SELECT apply_id FROM exact_local_applications WHERE cycle=? ORDER BY apply_id",
            (cycle_id,)).fetchall()]
    acknowledgements = []
    chunks = []
    if "exact_local_acknowledgements" in tables and apply_ids:
        placeholders = ",".join("?" for _ in apply_ids)
        columns = [row[1] for row in connection.execute(
            "PRAGMA table_info(exact_local_acknowledgements)")]
        for raw in connection.execute(
                "SELECT * FROM exact_local_acknowledgements WHERE apply_id IN (%s)" % placeholders,
                apply_ids).fetchall():
            acknowledgements.append(digest([_json_value(value) for value in raw]))
        acknowledgement_fact = {"columns": columns,
                                "row_count": len(acknowledgements),
                                "rows_digest": digest(sorted(acknowledgements))}
    else:
        acknowledgement_fact = {"columns": [], "row_count": 0,
                                "rows_digest": digest([])}
    if "exact_local_apply_chunks" in tables and apply_ids:
        placeholders = ",".join("?" for _ in apply_ids)
        columns = [row[1] for row in connection.execute(
            "PRAGMA table_info(exact_local_apply_chunks)")]
        for raw in connection.execute(
                "SELECT * FROM exact_local_apply_chunks WHERE apply_id IN (%s)" % placeholders,
                apply_ids).fetchall():
            chunks.append(digest([_json_value(value) for value in raw]))
        chunk_fact = {"columns": columns, "row_count": len(chunks),
                      "rows_digest": digest(sorted(chunks))}
    else:
        chunk_fact = {"columns": [], "row_count": 0,
                      "rows_digest": digest([])}
    return {"dirty_cell_count": 0,
            "exact_local_applications": applications,
            "exact_local_acknowledgements": acknowledgement_fact,
            "exact_local_apply_chunks": chunk_fact}


def _timestamp(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("retained_exception_timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("retained_exception_timestamp_invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("retained_exception_timestamp_timezone_missing")
    return value.strip()


def build_manifest(cycle, inventory_path, jobs_path, *, reason, created_at):
    """Capture a deterministic, read-only containment manifest."""
    if (not isinstance(cycle, Mapping) or not isinstance(cycle.get("id"), str)
            or not cycle["id"].strip()
            or cycle.get("status") in {"Complete", "Complete with exceptions"}):
        raise ValueError("retained_exception_cycle_not_unfinished")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 256:
        raise ValueError("retained_exception_reason_invalid")
    created_at = _timestamp(created_at)
    cycle_id = cycle["id"].strip()
    companies = cycle.get("companies")
    if not isinstance(companies, Mapping) or not companies:
        raise ValueError("retained_exception_cycle_membership_missing")
    membership = sorted(str(company_id) for company_id in companies)
    if any(not value for value in membership) or len(membership) != len(set(membership)):
        raise ValueError("retained_exception_cycle_membership_invalid")
    identities = []
    for company_id in membership:
        item = companies.get(company_id)
        if not isinstance(item, Mapping):
            raise ValueError("retained_exception_cycle_company_invalid")
        requested_url = _url(item.get("requested_url"))
        source_url = _url(item.get("source_url"))
        ats = _name(item.get("ats"))
        effective_source = source_url or requested_url
        identities.append({"company_id": company_id,
                           "company_name": _name(item.get("company")),
                           "requested_url": requested_url,
                           "requested_endpoint": _endpoint(requested_url),
                           "source_url": source_url,
                           "source_endpoint": _endpoint(effective_source),
                           "ats": ats,
                           "provider_identity": _provider_identity(
                               ats, effective_source)})
    with _readonly(inventory_path) as inbox:
        destination = inbox.execute("SELECT id FROM destination").fetchall()
        if len(destination) != 1 or not str(destination[0][0]).strip():
            raise ValueError("retained_exception_destination_invalid")
        inventory = {"cycle_tables": _cycle_tables(inbox, cycle_id),
                     "publication_receipts": _receipt_records(inbox, cycle_id)}
    with _readonly(jobs_path) as jobs:
        job_evidence = _job_evidence(jobs, cycle_id)
    manifest = {
        "version": VERSION,
        "action": ACTION,
        "cycle_id": cycle_id,
        "cycle_status": cycle.get("status"),
        "cycle_digest": digest(dict(cycle)),
        "cycle_membership": membership,
        "cycle_membership_digest": digest(membership),
        "cycle_company_identities": identities,
        "cycle_company_identities_digest": digest(identities),
        "workbook_id_digest": _digest_text(str(destination[0][0]).strip()),
        "inventory_evidence": inventory,
        "inventory_evidence_digest": digest(inventory),
        "job_evidence": job_evidence,
        "job_evidence_digest": digest(job_evidence),
        "reason": reason.strip(),
        "created_at": created_at,
        "local_only": True,
        "settlement_authorized": False,
        "publication_authorized": False,
    }
    manifest["manifest_digest"] = digest(manifest)
    return manifest


def required_claims(manifest, *, expires_at):
    if (not isinstance(manifest, Mapping) or manifest.get("version") != VERSION
            or manifest.get("action") != ACTION):
        raise ValueError("retained_exception_manifest_invalid")
    if manifest.get("manifest_digest") != digest({
            key: value for key, value in manifest.items()
            if key != "manifest_digest"}):
        raise ValueError("retained_exception_manifest_digest_invalid")
    return {"version": 1, "action": ACTION,
            "cycle_id": manifest["cycle_id"],
            "manifest_digest": manifest["manifest_digest"],
            "workbook_id_digest": manifest["workbook_id_digest"],
            "cycle_digest": manifest["cycle_digest"],
            "inventory_evidence_digest": manifest["inventory_evidence_digest"],
            "job_evidence_digest": manifest["job_evidence_digest"],
            "expires_at": _timestamp(expires_at)}


class RetainedWorkExceptionStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path)
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS retained_work_exceptions (
                cycle TEXT PRIMARY KEY, manifest TEXT NOT NULL,
                envelope TEXT NOT NULL,
                manifest_digest TEXT NOT NULL, authorization_digest TEXT NOT NULL,
                claims_digest TEXT NOT NULL, key_id TEXT NOT NULL,
                authorization_expires_at TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state='ACTIVE'))""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS retained_work_admissions (
                request_id TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
                exception_cycle TEXT NOT NULL, company_id TEXT NOT NULL,
                manifest_digest TEXT NOT NULL, company_identity_digest TEXT NOT NULL,
                payload TEXT NOT NULL, payload_digest TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state='FROZEN'))""")
        self.path.chmod(0o600)

    def close(self):
        self.db.close()

    def read(self, cycle_id):
        row = self.db.execute(
            "SELECT manifest,envelope,manifest_digest,authorization_digest,claims_digest,"
            "key_id,authorization_expires_at,state "
            "FROM retained_work_exceptions WHERE cycle=?", (cycle_id,)).fetchone()
        if row is None:
            return None
        try:
            manifest = json.loads(row[0])
            envelope = json.loads(row[1])
        except (TypeError, ValueError) as error:
            raise ValueError("retained_exception_store_corrupt") from error
        payload = envelope.get("payload") if isinstance(envelope, Mapping) else None
        if (row[7] != ACTIVE or manifest.get("manifest_digest") != row[2]
                or required_claims(manifest, expires_at="2999-01-01T00:00:00+00:00")[
                    "manifest_digest"] != row[2]
                or not isinstance(payload, Mapping)
                or payload.get("expires_at") != row[6]
                or digest(dict(envelope)) != row[3]
                or digest(dict(payload)) != row[4]
                or envelope.get("key_id") != row[5]):
            raise ValueError("retained_exception_store_corrupt")
        return {"manifest": manifest, "envelope": envelope,
                "manifest_digest": row[2], "authorization_digest": row[3],
                "claims_digest": row[4], "key_id": row[5],
                "authorization_expires_at": row[6], "state": row[7]}

    def _freeze(self, manifest, envelope, verified):
        if not isinstance(verified, Mapping):
            raise ValueError("retained_exception_authorization_missing")
        encoded = canonical(manifest)
        cycle_id = manifest["cycle_id"]
        expected = {"manifest": manifest,
                    "envelope": dict(envelope),
                    "manifest_digest": manifest["manifest_digest"],
                    "authorization_digest": verified.get("authorization_digest"),
                    "claims_digest": verified.get("claims_digest"),
                    "key_id": verified.get("key_id"),
                    "authorization_expires_at": verified.get("expires_at"),
                    "state": ACTIVE}
        if any(not isinstance(expected[key], str) or not expected[key]
               for key in ("manifest_digest", "authorization_digest",
                           "claims_digest", "key_id",
                           "authorization_expires_at")):
            raise ValueError("retained_exception_authorization_invalid")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            retained = self.read(cycle_id)
            if retained is None:
                self.db.execute(
                    "INSERT INTO retained_work_exceptions VALUES (?,?,?,?,?,?,?,?,?)",
                    (cycle_id, encoded, canonical(dict(envelope)),
                     expected["manifest_digest"], expected["authorization_digest"],
                     expected["claims_digest"], expected["key_id"],
                     expected["authorization_expires_at"], ACTIVE))
            elif retained != expected:
                raise ValueError("retained_exception_changed")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return self.read(cycle_id)

    def _reserve(self, payload):
        encoded, payload_digest = canonical(payload), digest(payload)
        expected = {"payload": payload, "payload_digest": payload_digest,
                    "state": "FROZEN"}
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                "SELECT payload,payload_digest,state FROM retained_work_admissions "
                "WHERE request_id=?", (payload["request_id"],)).fetchone()
            event = self.db.execute(
                "SELECT request_id FROM retained_work_admissions WHERE event_id=?",
                (payload["event_id"],)).fetchone()
            if row is not None:
                try:
                    retained = {"payload": json.loads(row[0]),
                                "payload_digest": row[1], "state": row[2]}
                except (TypeError, ValueError) as error:
                    raise ValueError("retained_exception_store_corrupt") from error
                if retained != expected:
                    raise ValueError("retained_exception_request_reused")
            elif event is not None:
                raise ValueError("retained_exception_event_reused")
            else:
                self.db.execute(
                    "INSERT INTO retained_work_admissions VALUES (?,?,?,?,?,?,?,?,?)",
                    (payload["request_id"], payload["event_id"],
                     payload["exception_cycle"], payload["company_id"],
                     payload["manifest_digest"], payload["company_identity_digest"],
                     encoded, payload_digest, "FROZEN"))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return expected


def activate_exception(manifest, envelope, verifier, store_path, *, now=None,
                       allow_test_verifier=False):
    """Verify authorization before the writable store is constructed."""
    from job_search_helper.selected_recovery_authorization import verify_authorization
    payload = envelope.get("payload") if isinstance(envelope, Mapping) else None
    expires_at = payload.get("expires_at") if isinstance(payload, Mapping) else None
    claims = required_claims(manifest, expires_at=expires_at)
    verified = verify_authorization(envelope, claims, verifier, now=now,
                                    allow_test_verifier=allow_test_verifier)
    store = RetainedWorkExceptionStore(store_path)
    try:
        return store._freeze(manifest, envelope, verified)
    finally:
        store.close()


def revalidate_manifest(manifest, cycle, inventory_path, jobs_path):
    fresh = build_manifest(cycle, inventory_path, jobs_path,
                           reason=manifest.get("reason"),
                           created_at=manifest.get("created_at"))
    if fresh != dict(manifest):
        raise ValueError("retained_exception_evidence_changed")
    return fresh


def _active_record(store_path, cycle_id, verifier, *, now=None,
                   allow_test_verifier=False):
    location = Path(store_path).resolve()
    if not location.is_file():
        raise ValueError("retained_exception_store_missing")
    uri = location.as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    try:
        columns = [row[1] for row in db.execute(
            "PRAGMA table_info(retained_work_exceptions)")]
        required = {"cycle", "manifest", "envelope", "manifest_digest",
                    "authorization_digest", "claims_digest", "key_id",
                    "authorization_expires_at", "state"}
        if not required <= set(columns):
            raise ValueError("retained_exception_store_corrupt")
        row = db.execute(
            "SELECT manifest,envelope,manifest_digest,authorization_digest,claims_digest,"
            "key_id,authorization_expires_at,state FROM retained_work_exceptions "
            "WHERE cycle=?", (cycle_id,)).fetchone()
    finally:
        db.close()
    if row is None:
        raise ValueError("retained_exception_active_record_required")
    try:
        manifest, envelope = json.loads(row[0]), json.loads(row[1])
    except (TypeError, ValueError) as error:
        raise ValueError("retained_exception_store_corrupt") from error
    if (row[7] != ACTIVE or manifest.get("manifest_digest") != row[2]
            or envelope.get("key_id") != row[5]
            or not isinstance(envelope.get("payload"), Mapping)
            or envelope["payload"].get("expires_at") != row[6]):
        raise ValueError("retained_exception_store_corrupt")
    from job_search_helper.selected_recovery_authorization import verify_authorization
    claims = required_claims(manifest, expires_at=row[6])
    verified = verify_authorization(envelope, claims, verifier, now=now,
                                    allow_test_verifier=allow_test_verifier)
    if (verified.get("authorization_digest") != row[3]
            or verified.get("claims_digest") != row[4]
            or verified.get("key_id") != row[5]
            or verified.get("expires_at") != row[6]):
        raise ValueError("retained_exception_store_corrupt")
    return {"manifest": manifest, "envelope": envelope,
            "manifest_digest": row[2], "authorization_digest": row[3],
            "claims_digest": row[4], "key_id": row[5],
            "authorization_expires_at": row[6], "state": row[7]}


def validate_frozen_admission(store_path, verifier, cycle, inventory_path,
                              jobs_path, expected, *, now=None,
                              allow_test_verifier=False):
    """Read-only proof that one prior admission reservation still exists."""
    location = Path(store_path).resolve()
    if (location.parent != Path(inventory_path).resolve().parent
            or location.parent != Path(jobs_path).resolve().parent
            or location.name != "retained-work-exceptions.sqlite3"):
        raise ValueError("retained_exception_store_path_invalid")
    if not isinstance(expected, Mapping):
        raise ValueError("retained_exception_admission_expected")
    cycle_id = cycle.get("id") if isinstance(cycle, Mapping) else None
    record = _active_record(location, cycle_id, verifier, now=now,
                            allow_test_verifier=allow_test_verifier)
    manifest = record["manifest"]
    revalidate_manifest(manifest, cycle, inventory_path, jobs_path)
    payload = expected.get("reservation_payload")
    if (not isinstance(payload, Mapping)
            or expected.get("discounted_cycle_ids") != [cycle_id]
            or expected.get("company_id") != payload.get("company_id")
            or expected.get("manifest_digest") != manifest["manifest_digest"]
            or expected.get("reservation_digest") != digest(dict(payload))
            or expected.get("settlement_authorized") is not False
            or expected.get("publication_authorized") is not False
            or expected.get("required_next_boundary")
                != "exact-cycle-company-publication"):
        raise ValueError("retained_exception_admission_expected")
    db = sqlite3.connect(location.as_uri() + "?mode=ro", uri=True)
    try:
        columns = [row[1] for row in db.execute(
            "PRAGMA table_info(retained_work_admissions)")]
        required = {"request_id", "event_id", "exception_cycle", "company_id",
                    "manifest_digest", "company_identity_digest", "payload",
                    "payload_digest", "state"}
        if not required <= set(columns):
            raise ValueError("retained_exception_store_corrupt")
        row = db.execute(
            "SELECT request_id,event_id,exception_cycle,company_id,"
            "manifest_digest,company_identity_digest,payload,payload_digest,state "
            "FROM retained_work_admissions WHERE request_id=?",
            (payload.get("request_id"),)).fetchone()
    finally:
        db.close()
    if row is None:
        raise ValueError("retained_exception_admission_missing")
    try:
        stored_payload = json.loads(row[6])
    except (TypeError, ValueError) as error:
        raise ValueError("retained_exception_store_corrupt") from error
    expected_row = (
        payload.get("request_id"), payload.get("event_id"),
        payload.get("exception_cycle"), payload.get("company_id"),
        payload.get("manifest_digest"), payload.get("company_identity_digest"),
        dict(payload), digest(dict(payload)), "FROZEN")
    actual_row = row[:6] + (stored_payload, row[7], row[8])
    if actual_row != expected_row:
        raise ValueError("retained_exception_admission_changed")
    return dict(expected)


def _verified_retained_manifest(store_path, verifier, cycle, inventory_path,
                                jobs_path, *, now, allow_test_verifier):
    if (Path(store_path).resolve().parent != Path(inventory_path).resolve().parent
            or Path(store_path).resolve().parent != Path(jobs_path).resolve().parent
            or Path(store_path).name != "retained-work-exceptions.sqlite3"):
        raise ValueError("retained_exception_store_path_invalid")
    cycle_id = cycle.get("id") if isinstance(cycle, Mapping) else None
    record = _active_record(store_path, cycle_id, verifier, now=now,
                            allow_test_verifier=allow_test_verifier)
    manifest = record["manifest"]
    revalidate_manifest(manifest, cycle, inventory_path, jobs_path)
    return manifest


def _request_provenance(request, event_receipt):
    if not isinstance(request, Mapping) or request.get("mode") != "company-only":
        raise ValueError("retained_exception_request_not_company_only")
    company_ids = request.get("company_ids")
    if (not isinstance(company_ids, list) or len(company_ids) != 1
            or not isinstance(company_ids[0], str) or not company_ids[0].strip()
            or not isinstance(request.get("request_id"), str)
            or not request["request_id"].strip()
            or not isinstance(request.get("source_revision"), str)
            or not request["source_revision"].strip()):
        raise ValueError("retained_exception_request_invalid")
    company_id = company_ids[0].strip()
    event = request.get("company_event")
    operator = request.get("operator_request")
    if isinstance(event, Mapping) and operator is None:
        if (event.get("schema") != "company-event-scan-request-v1"
                or not isinstance(event.get("event_id"), str) or not event["event_id"].strip()
                or event.get("company_id") != company_id
                or event.get("source_revision") != request["source_revision"]
                or type(event.get("revision")) is not int or event["revision"] < 1
                or request["request_id"] != "company-event:" + event["event_id"]):
            raise ValueError("retained_exception_event_binding_invalid")
        if (not isinstance(event_receipt, Mapping)
                or event_receipt.get("schema") != "company-event-scan-request-v1"
                or event_receipt.get("event_id") != event["event_id"]
                or event_receipt.get("company_id") != company_id
                or event_receipt.get("revision") != event["revision"]
                or event_receipt.get("source_revision") != request["source_revision"]
                or event_receipt.get("request_sha256") != digest(dict(request))
                or event_receipt.get("state") not in {
                    "REQUEST_WRITTEN", "REQUEST_CONFIRMED",
                    "REQUEST_SUPERSEDED_OLDER"}):
            raise ValueError("retained_exception_event_receipt_invalid")
        provenance_id = event["event_id"]
    elif isinstance(operator, Mapping) and event is None:
        if (set(operator) != {"schema", "request_id", "company_id", "source_revision"}
                or operator.get("schema") != "operator-company-scan-request-v1"
                or operator.get("request_id") != request["request_id"]
                or operator.get("company_id") != company_id
                or operator.get("source_revision") != request["source_revision"]):
            raise ValueError("retained_exception_operator_binding_invalid")
        if (not isinstance(event_receipt, Mapping)
                or event_receipt.get("schema") != "operator-company-scan-request-v1"
                or event_receipt.get("request_id") != request["request_id"]
                or event_receipt.get("company_id") != company_id
                or event_receipt.get("source_revision") != request["source_revision"]
                or event_receipt.get("request_sha256") != digest(dict(request))
                or event_receipt.get("state") not in {
                    "REQUEST_WRITTEN", "REQUEST_ALREADY_DURABLE"}):
            raise ValueError("retained_exception_operator_receipt_invalid")
        provenance_id = "operator:" + request["request_id"]
    else:
        raise ValueError("retained_exception_request_provenance_invalid")
    return company_id, provenance_id


def _assert_disjoint_identity(manifest, company_id, company_name, official_url, *,
                             source_endpoint="", provider_identity=""):
    if company_id in manifest["cycle_membership"]:
        raise ValueError("retained_exception_company_overlap")
    official_endpoint = _endpoint(official_url)
    for identity in manifest["cycle_company_identities"]:
        if company_name == identity.get("company_name"):
            raise ValueError("retained_exception_company_alias")
        endpoints = {identity.get("requested_endpoint"), identity.get("source_endpoint")}
        if (official_endpoint in endpoints
                or (source_endpoint and source_endpoint in endpoints)):
            raise ValueError("retained_exception_source_alias")
        if provider_identity and provider_identity == identity.get("provider_identity"):
            raise ValueError("retained_exception_provider_alias")


def _assert_blocker_scope(manifest, unfinished_cycle_ids):
    if set(unfinished_cycle_ids) != {manifest["cycle_id"]}:
        raise ValueError("retained_exception_blocker_scope_changed")


def validate_disjoint_company_preflight(store_path, verifier, cycle, inventory_path,
                                        jobs_path, manifest, request, event_receipt,
                                        company, company_fact, unfinished_cycle_ids,
                                        *, now=None, allow_test_verifier=False):
    """Reject conflicts in trusted local evidence without reserving or fetching."""
    verified = _verified_retained_manifest(
        store_path, verifier, cycle, inventory_path, jobs_path,
        now=now, allow_test_verifier=allow_test_verifier)
    if verified != manifest:
        raise ValueError("retained_exception_manifest_binding_changed")
    company_id, _ = _request_provenance(request, event_receipt)
    if company_fact["company_id"] != company_id or company_fact["company_status"] != "active":
        raise ValueError("retained_exception_current_company_invalid")
    from .ats import resolve_board
    from .company_sources import repair_source

    company_name = company["Company"]
    official_url = company_fact["official_careers_url"]
    ats, fetch_url, _ = repair_source(
        str(company.get("ATS / Source", "")), company["Official Careers URL"],
        company_id, company_name)
    # The normal resolver can identify a direct board without I/O. Preserve
    # provider discovery for URLs it cannot resolve from local data.
    provider_identity = ""
    try:
        provider, board, api_root = resolve_board(ats, fetch_url)
    except ValueError:
        pass
    else:
        if provider in {"Ashby", "Greenhouse", "Lever"}:
            provider_identity = _provider_identity(provider, api_root + quote(board, safe=""))
    _assert_disjoint_identity(
        manifest, company_id, _name(company_name), official_url,
        source_endpoint=_endpoint(fetch_url), provider_identity=provider_identity)
    _assert_blocker_scope(manifest, unfinished_cycle_ids)


def admit_disjoint_company_request(store_path, verifier, cycle, inventory_path,
                                   jobs_path, request, event_receipt,
                                   current_company, unfinished_cycle_ids, *,
                                   operation, defer_sync, now=None,
                                   allow_test_verifier=False):
    """Freeze a reservation for the one blocker a reviewed caller may discount."""
    manifest = _verified_retained_manifest(
        store_path, verifier, cycle, inventory_path, jobs_path,
        now=now, allow_test_verifier=allow_test_verifier)
    if operation != "start-company-only":
        raise ValueError("retained_exception_operation_forbidden")
    # The normal run-owned synchronizer is global.  Until a provenance-scoped
    # publisher owns the later delivery phase, this exceptional admission may
    # fetch/apply only with Sheets publication deferred.  The controller must
    # then invoke the separately reviewed exact cycle+Company publisher.
    if defer_sync is not True:
        raise ValueError("retained_exception_deferred_sync_required")
    company_id, provenance_id = _request_provenance(request, event_receipt)
    try:
        company_identity = canonical_admitted_company_identity(current_company)
    except ValueError as error:
        raise ValueError("retained_exception_current_company_invalid") from error
    if (company_identity["company_id"] != company_id
            or company_identity["source_revision"] != request["source_revision"]
            or company_identity["company_status"] != "active"
            or company_identity["claimed_by"]
            or company_identity["claim_token"]):
        raise ValueError("retained_exception_current_company_invalid")
    _assert_disjoint_identity(
        manifest, company_id, company_identity["company_name"],
        company_identity["official_careers_url"],
        source_endpoint=company_identity["source_endpoint"],
        provider_identity=company_identity["provider_identity"])
    _assert_blocker_scope(manifest, unfinished_cycle_ids)
    reservation = {"request_id": request["request_id"],
                   "event_id": provenance_id,
                   "exception_cycle": manifest["cycle_id"],
                   "company_id": company_id,
                   "manifest_digest": manifest["manifest_digest"],
                   "company_identity_digest": digest(company_identity),
                   "request_digest": digest(dict(request)),
                   "event_receipt_digest": digest(dict(event_receipt)),
                   "defer_sync": True}
    store = RetainedWorkExceptionStore(store_path)
    try:
        frozen = store._reserve(reservation)
    finally:
        store.close()
    return {"discounted_cycle_ids": [manifest["cycle_id"]],
            "company_id": company_id,
            "manifest_digest": manifest["manifest_digest"],
            "reservation_digest": frozen["payload_digest"],
            "settlement_authorized": False, "publication_authorized": False,
            "required_next_boundary": "exact-cycle-company-publication",
            "reservation_payload": reservation}
