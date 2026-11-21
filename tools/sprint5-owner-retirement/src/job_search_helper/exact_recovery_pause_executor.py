"""Activation-grade, exact-row application of a frozen recovery pause.

This module deliberately does not use :class:`Engine` synchronization.  It
owns the normal local scraper lock, applies only the Companies named by an
accepted pause journal, and finalizes only the matching Scan Cycles row.
Every mutation is preceded by a durable intent.  An intent found on entry is
readback-only: it is never replayed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import stat
from pathlib import Path

from .cli import scraper_lock_name, writer_lock
from .exact_recovery_pause import revalidate_pause_journal
from .exact_recovery_pause_apply import COMPLETE, CONFIRMED, RUN_VERSION, _digest


MAX_CHUNK_COMPANIES = 50
MAX_CHUNK_BYTES = 500_000
FINISHED = {"Complete", "Complete with exceptions"}
COMPANY_HEADERS = (
    "Company ID", "Company Status", "Active Cycle ID", "Claimed By",
    "Claim Token", "Scan State", "Automatic Retry?", "Blocked Reason",
    "Next Action", "Record Updated",
)
SCAN_HEADERS = (
    "Cycle ID", "Started At", "Completed At", "Cycle Status", "Started By",
    "Companies in Scope", "Companies Complete", "Companies Partial",
    "Companies Blocked", "Companies Remaining", "Last Company ID",
    "Last Company", "Last Checkpoint At", "Notes",
)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _ack(kind, value):
    return "%s-readback:%s" % (
        kind,
        hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest(),
    )


def _selected_row(remote, tab, identity_header, identity, headers):
    numbered = remote.read_columns(tab, [identity_header])
    matches = [row_number for row_number, row in numbered
               if str(row.get(identity_header, "")).strip() == identity]
    if len(matches) != 1:
        raise ValueError("%s_missing_or_ambiguous" % tab.lower().replace(" ", "_"))
    row_number = matches[0]
    row = remote.read_rows(tab, [row_number]).get(row_number)
    if not isinstance(row, dict):
        raise ValueError("%s_selected_row_missing" % tab.lower().replace(" ", "_"))
    return row_number, {header: row.get(header, "") for header in headers}


def _pre_scan_state(stage):
    return {"queued": "Queued", "inventory": "In Progress"}[stage]


def _hold_values(journal):
    return {
        "Scan State": "Blocked / Manual Review",
        "Automatic Retry?": "No",
        "Blocked Reason": "Interrupted cycle paused for recovery: " + journal["reason"],
        "Next Action": "Cycle preserved for explicit recovery; do not retry automatically.",
        "Record Updated": journal["timestamp"],
    }


def _company_operation(remote, journal, company_id):
    _row_number, row = _selected_row(
        remote, "Companies", "Company ID", company_id, COMPANY_HEADERS,
    )
    if str(row["Company Status"]).strip().casefold() != "active":
        raise ValueError("pause_company_not_active")
    if str(row["Claimed By"]).strip() or str(row["Claim Token"]).strip():
        raise ValueError("pause_company_claimed")
    if str(row["Active Cycle ID"]).strip() != journal["cycle_id"]:
        raise ValueError("pause_company_cycle_changed")
    expected_scan = _pre_scan_state(journal["candidate_pre_stages"][company_id])
    if str(row["Scan State"]).strip() != expected_scan:
        raise ValueError("pause_company_scan_state_changed")
    values = _hold_values(journal)
    expected = {
        "Company Status": row["Company Status"],
        "Active Cycle ID": journal["cycle_id"],
        "Claimed By": "",
        "Claim Token": "",
        "Scan State": expected_scan,
        "Automatic Retry?": row["Automatic Retry?"],
        "Blocked Reason": row["Blocked Reason"],
        "Next Action": row["Next Action"],
        "Record Updated": row["Record Updated"],
    }
    operation = {
        "tab": "Companies", "identity": {"Company ID": company_id},
        "values": values, "expected": expected,
    }
    readback = dict(row)
    readback.update(values)
    return operation, readback


def _chunks(entries):
    chunk = []
    for entry in entries:
        if len(_canonical({"companies": [entry]}).encode("utf-8")) > MAX_CHUNK_BYTES:
            raise ValueError("pause_company_operation_exceeds_chunk_limit")
        candidate = {"companies": chunk + [entry]}
        size = len(_canonical(candidate).encode("utf-8"))
        if chunk and (len(chunk) >= MAX_CHUNK_COMPANIES or size > MAX_CHUNK_BYTES):
            yield {"companies": chunk}
            chunk = [entry]
        else:
            chunk.append(entry)
    if chunk:
        yield {"companies": chunk}


def _final_cycle(current, journal):
    cycle = copy.deepcopy(current)
    if not isinstance(cycle, dict) or cycle.get("id") != journal["cycle_id"]:
        raise ValueError("pause_state_cycle_missing")
    recovery = {
        "reason": journal["reason"],
        "paused_company_ids": sorted(journal["candidate_ids"]),
        "previous_stages": {
            company_id: journal["candidate_pre_stages"][company_id]
            for company_id in sorted(journal["candidate_ids"])
        },
        "paused_at": journal["timestamp"],
    }
    for company_id in journal["candidate_ids"]:
        item = cycle.get("companies", {}).get(company_id)
        if not isinstance(item, dict):
            raise ValueError("pause_state_candidate_missing")
        original = journal["candidate_pre_stages"][company_id]
        if item.get("stage") == original:
            item["recovery_previous_stage"] = original
            item["stage"] = "paused"
        elif not (item.get("stage") == "paused"
                  and item.get("recovery_previous_stage") == original):
            raise ValueError("pause_state_candidate_changed")
    if cycle.get("recovery_pause") not in (None, recovery):
        raise ValueError("pause_state_recovery_control_changed")
    cycle["recovery_pause"] = recovery
    stages = [item.get("stage") for item in cycle.get("companies", {}).values()]
    allowed = {"complete", "partial", "awaiting_review", "blocked",
               "unsupported", "failed", "paused"}
    if any(stage not in allowed for stage in stages):
        raise ValueError("pause_state_unclassified_stage")
    if any(stage in {"queued", "inventory"} for stage in stages):
        raise ValueError("pause_state_remaining_candidates")
    blocked = sum(stage in {"blocked", "unsupported", "failed", "paused"}
                  for stage in stages)
    partial = sum(stage in {"partial", "awaiting_review"} for stage in stages)
    cycle["status"] = "Complete with exceptions" if blocked or partial else "Complete"
    cycle["completed_at"] = journal["timestamp"]
    return cycle


def _scan_values(cycle, journal):
    stages = [item.get("stage") for item in cycle["companies"].values()]
    complete = stages.count("complete")
    partial = sum(stage in {"partial", "awaiting_review"} for stage in stages)
    blocked = sum(stage in {"blocked", "unsupported", "failed", "paused"}
                  for stage in stages)
    remaining = sum(stage in {"queued", "inventory"} for stage in stages)
    if remaining:
        raise ValueError("pause_scan_cycle_remaining_not_zero")
    control = {
        "all": bool(cycle.get("all", False)),
        "company_ids": list(cycle["companies"]),
        "helper_version": 1,
        "mode": "single writer; no model calls",
        "recovery_pause": cycle["recovery_pause"],
    }
    for key in ("start_request_id", "supersedes", "start_last",
                "comparison_baseline_id", "request_fingerprint",
                "company_event", "repair_retry"):
        if key in cycle:
            control[key] = cycle[key]
    return {
        "Completed At": journal["timestamp"],
        "Cycle Status": cycle["status"],
        "Companies in Scope": len(stages),
        "Companies Complete": complete,
        "Companies Partial": partial,
        "Companies Blocked": blocked,
        "Companies Remaining": 0,
        "Last Checkpoint At": journal["timestamp"],
        # The apply ledger canonicalizes its payload.  Sort the nested control
        # envelope too so a restart after State serialization reconstructs the
        # identical frozen Scan Cycles operation.
        "Notes": json.dumps(control, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")),
    }


def _scan_payload(remote, cycle, journal):
    row_number, row = _selected_row(
        remote, "Scan Cycles", "Cycle ID", journal["cycle_id"], SCAN_HEADERS,
    )
    if row["Cycle Status"] in FINISHED:
        raise ValueError("pause_scan_cycle_already_finished_without_intent")
    # The local journal binds the complete Company membership.  Require the
    # remote control envelope to name exactly the same membership before the
    # final row can be frozen.
    try:
        control = json.loads(row["Notes"] or "{}")
    except (TypeError, ValueError) as exc:
        raise ValueError("pause_scan_cycle_notes_invalid") from exc
    if (not isinstance(control, dict)
            or list(control.get("company_ids", [])) != list(cycle["companies"])):
        raise ValueError("pause_scan_cycle_scope_changed")
    values = _scan_values(cycle, journal)
    expected = {header: row[header] for header in SCAN_HEADERS
                if header not in {"Cycle ID"}}
    operation = {
        "tab": "Scan Cycles", "identity": {"Cycle ID": journal["cycle_id"]},
        "values": values, "expected": expected,
    }
    readback = dict(row)
    readback.update(values)
    return {"operation": operation, "readback": readback, "row_number": row_number,
            "paused_company_ids": list(journal["candidate_ids"])}


def _read_company_chunk(remote, payload):
    observed = {}
    for entry in payload["companies"]:
        company_id = entry["company_id"]
        _number, row = _selected_row(
            remote, "Companies", "Company ID", company_id, COMPANY_HEADERS,
        )
        observed[company_id] = row
    return observed


def _expected_company_chunk(payload):
    return {entry["company_id"]: entry["readback"] for entry in payload["companies"]}


def _read_scan(remote, payload, cycle_id):
    _number, row = _selected_row(
        remote, "Scan Cycles", "Cycle ID", cycle_id, SCAN_HEADERS,
    )
    return row


def _normal_scraper_lock_path(state):
    """Derive the non-injectable normal scraper lock from file-backed State."""
    raw = getattr(state, "path", None)
    if not isinstance(raw, str) or not raw or raw == ":memory:":
        raise ValueError("pause_file_backed_state_required")
    state_path = Path(raw)
    try:
        mode = state_path.stat().st_mode
    except (OSError, ValueError) as exc:
        raise ValueError("pause_file_backed_state_required") from exc
    if not stat.S_ISREG(mode):
        raise ValueError("pause_file_backed_state_required")
    return state_path.parent / scraper_lock_name()


def execute_exact_recovery_pause(state, inbox, journal_store, apply_store,
                                 remote, cycle_id, manifests, *,
                                 manifest_revalidator, next_scan_path=None):
    """Apply one accepted pause journal while owning the real writer lock.

    The caller supplies already accepted terminal manifests and their fresh
    revalidator.  No request/inbox mutation occurs here.
    """
    lock_path = _normal_scraper_lock_path(state)
    with writer_lock(lock_path):
        from .retained_cycle_retirement_control import assert_cycle_not_retired
        assert_cycle_not_retired(state, cycle_id)
        run = apply_store.run(cycle_id)
        state_intent = apply_store.intent(cycle_id, "STATE_FINALIZATION", 0)
        scan_intent = apply_store.intent(cycle_id, "SCAN_CYCLE_FINALIZATION", 0)
        if (state_intent is not None or scan_intent is not None) and run is None:
            raise ValueError("pause_intent_without_frozen_run")
        if (state_intent is not None
                and state_intent["digest"] != run["payload"]["state_finalization_digest"]):
            raise ValueError("pause_state_intent_not_frozen")
        if (scan_intent is not None
                and scan_intent["digest"] != run["payload"]["scan_cycle_finalization_digest"]):
            raise ValueError("pause_scan_intent_not_frozen")

        # A discovered intent is never replayed.  Settle it only from exact
        # readback, even if the prior process died before issuing its request.
        if scan_intent is not None:
            observed = _read_scan(remote, scan_intent["payload"], cycle_id)
            if observed != scan_intent["payload"]["readback"]:
                raise ValueError("pause_pending_scan_intent_readback_mismatch")
            if scan_intent["state"] != CONFIRMED:
                apply_store.confirm(cycle_id, "SCAN_CYCLE_FINALIZATION", 0,
                                    scan_intent["digest"], _ack("scan", observed))
            return {"cycle_id": cycle_id, "status": COMPLETE,
                    "paused_company_ids": list(scan_intent["payload"]["paused_company_ids"])}

        if state_intent is not None:
            observed = state.cycle(cycle_id)
            if observed != state_intent["payload"]["cycle"]:
                raise ValueError("pause_pending_state_intent_readback_mismatch")
            if state_intent["state"] != CONFIRMED:
                state_intent = apply_store.confirm(
                    cycle_id, "STATE_FINALIZATION", 0, state_intent["digest"],
                    _ack("state", observed),
                )

        # Before any first intent (and throughout the Company phase), require
        # the independently accepted phase-A facts to remain current.
        if state_intent is None:
            journal = revalidate_pause_journal(
                state, inbox, journal_store, cycle_id, manifests,
                manifest_revalidator=manifest_revalidator,
                next_scan_path=next_scan_path,
            )
        else:
            journal = journal_store.read(cycle_id)
            if journal is None:
                raise ValueError("exact_pause_journal_missing")
            if journal["journal_digest"] != run["payload"]["journal_digest"]:
                raise ValueError("pause_apply_journal_binding_changed")

        current_cycle = state.cycle(cycle_id)
        final_cycle = (copy.deepcopy(state_intent["payload"]["cycle"])
                       if state_intent is not None else _final_cycle(current_cycle, journal))

        if state_intent is None:
            if run is None:
                entries = []
                for company_id in journal["candidate_ids"]:
                    operation, readback = _company_operation(remote, journal, company_id)
                    entries.append({"company_id": company_id, "operation": operation,
                                    "readback": readback})
                chunk_payloads = list(_chunks(entries))
            else:
                # Reconstruct only chunks that have never acquired an intent.
                # Applied/pending chunks use their durable payload and are
                # readback-only, so their now-held rows need not pass the old
                # queued/inventory precondition again.
                chunk_payloads = []
                offset = 0
                for frozen in run["payload"]["chunks"]:
                    existing = apply_store.intent(cycle_id, "CHUNK", frozen["start"])
                    if existing is not None:
                        payload = existing["payload"]
                    else:
                        entries = []
                        selected = journal["candidate_ids"][offset:offset + frozen["count"]]
                        for company_id in selected:
                            operation, readback = _company_operation(remote, journal, company_id)
                            entries.append({"company_id": company_id, "operation": operation,
                                            "readback": readback})
                        payload = {"companies": entries}
                    if (len(payload.get("companies", [])) != frozen["count"]
                            or _digest(payload) != frozen["digest"]):
                        raise ValueError("pause_frozen_chunk_payload_changed")
                    chunk_payloads.append(payload)
                    offset += frozen["count"]
                if offset != len(journal["candidate_ids"]):
                    raise ValueError("pause_frozen_chunk_scope_changed")
            scan_payload = _scan_payload(remote, final_cycle, journal)
            state_payload = {"cycle_id": cycle_id, "cycle": final_cycle}
            run_payload = {
                "version": RUN_VERSION,
                "cycle_id": cycle_id,
                "journal_digest": journal["journal_digest"],
                "chunks": [
                    {"start": start, "count": len(payload["companies"]),
                     "digest": _digest(payload)}
                    for start, payload in enumerate(chunk_payloads)
                ],
                "state_finalization_digest": _digest(state_payload),
                "scan_cycle_finalization_digest": _digest(scan_payload),
            }
            run = apply_store.freeze_run(cycle_id, run_payload)
        else:
            chunk_payloads = []
            scan_payload = None
            state_payload = state_intent["payload"]

        if run is None:
            raise RuntimeError("pause_apply_run_not_frozen")

        # Company intents are processed in frozen order.  Existing intents are
        # readback-only; only a newly inserted intent may issue one commit.
        if state_intent is None:
            for frozen, generated in zip(run["payload"]["chunks"], chunk_payloads):
                intent = apply_store.intent(cycle_id, "CHUNK", frozen["start"])
                payload = intent["payload"] if intent is not None else generated
                observed = _read_company_chunk(remote, payload)
                expected = _expected_company_chunk(payload)
                if intent is not None:
                    if observed != expected:
                        raise ValueError("pause_pending_chunk_intent_readback_mismatch")
                else:
                    intent = apply_store.begin(
                        cycle_id, "CHUNK", frozen["start"], payload,
                    )
                    remote.commit([entry["operation"] for entry in payload["companies"]])
                    observed = _read_company_chunk(remote, payload)
                    if observed != expected:
                        raise ValueError("pause_chunk_readback_mismatch")
                if intent["state"] != CONFIRMED:
                    apply_store.confirm(
                        cycle_id, "CHUNK", frozen["start"], intent["digest"],
                        _ack("companies", observed),
                    )

            state_intent = apply_store.begin(
                cycle_id, "STATE_FINALIZATION", 0, state_payload,
            )
            state.save_cycle(final_cycle)
            observed_state = state.cycle(cycle_id)
            if observed_state != final_cycle:
                raise ValueError("pause_state_finalization_readback_mismatch")
            state_intent = apply_store.confirm(
                cycle_id, "STATE_FINALIZATION", 0, state_intent["digest"],
                _ack("state", observed_state),
            )

        if state_intent["state"] != CONFIRMED:
            raise ValueError("pause_state_finalization_unconfirmed")
        if scan_payload is None:
            scan_payload = _scan_payload(remote, final_cycle, journal)
        scan_intent = apply_store.begin(
            cycle_id, "SCAN_CYCLE_FINALIZATION", 0, scan_payload,
        )
        remote.commit([scan_payload["operation"]])
        observed_scan = _read_scan(remote, scan_payload, cycle_id)
        if observed_scan != scan_payload["readback"]:
            raise ValueError("pause_scan_finalization_readback_mismatch")
        apply_store.confirm(
            cycle_id, "SCAN_CYCLE_FINALIZATION", 0, scan_intent["digest"],
            _ack("scan", observed_scan),
        )
        return {"cycle_id": cycle_id, "status": COMPLETE,
                "paused_company_ids": list(journal["candidate_ids"])}
