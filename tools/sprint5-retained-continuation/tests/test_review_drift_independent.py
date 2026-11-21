"""Disposable protected review snapshot and apply-boundary checks."""
import json

import pytest

from job_search_helper.exact_control_before_prefix_recovery import (
    preview_control_before_prefix_source_transition,
)
from job_search_helper.exact_cycle_planner import _digest
from job_search_helper.exact_local_plan import commit_exact_local_plan
from job_search_helper.sqlite_repository import REVIEW_FIELDS
from test_late_control_continuation_journal import IDENTITY, saved


@pytest.mark.parametrize("drift", ["manual-choice-timestamp", "visible-fit-level"])
def test_parent_binds_review_drift_that_effective_delta_does_not_check(saved, drift):
    inbox, repository, scope, key, new_source, claims, sign, freeze = saved
    plan_raw, original_cursor = inbox.execute(
        "SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?", IDENTITY,
    ).fetchone()
    inventory_raw = inbox.execute(
        "SELECT payload FROM inventories WHERE cycle=? AND company=?", IDENTITY,
    ).fetchone()[0]
    preview_inputs = {
        "cycle_id": IDENTITY[0], "company_id": IDENTITY[1],
        "legacy_plan": json.loads(plan_raw), "cursor": original_cursor,
        "payload": json.loads(inventory_raw), "controls": scope["controls"],
    }
    preview = preview_control_before_prefix_source_transition(repository, **preview_inputs)
    parent = preview["plan"]["binding"]
    source_index = parent["transition"]["history_index"]
    successor_operation = preview["plan"]["operations"][source_index]
    assert REVIEW_FIELDS.issubset(successor_operation["expected"])
    signed = sign(claims())
    assert signed["payload"]["parent_hold_digest"] == _digest(parent)
    freeze(signed)
    archived = json.loads(inbox.execute(
        "SELECT archive FROM late_control_continuations WHERE cycle=? AND company=?", IDENTITY,
    ).fetchone()[0])
    assert archived["parent"] == parent

    plan = archived["plan"]
    history_delta, = (op for op in plan["local_operations"] if op["tab"] == "Job History")
    assert not REVIEW_FIELDS.intersection(history_delta["expected"])
    assert not REVIEW_FIELDS.intersection(history_delta["values"])

    row_id, original_history = repository.matches("Job History", {"Job Key": key})[0]
    with repository.transaction():
        if drift == "manual-choice-timestamp":
            repository.db.execute(
                "UPDATE manual_choices SET at='fixture-owner-reasserted' WHERE tab='Job History' AND row_id=?",
                (row_id,),
            )
        else:
            repository.db.execute(
                "UPDATE records SET data=json_set(data, '$.\"Fit Level\"', 'fixture-updated') "
                "WHERE tab='Job History' AND row_id=?", (row_id,),
            )
    current = preview_control_before_prefix_source_transition(repository, **preview_inputs)
    current_parent = current["plan"]["binding"]
    if drift == "manual-choice-timestamp":
        assert current_parent["transition"]["manual_choice_snapshot_digest"] != parent[
            "transition"
        ]["manual_choice_snapshot_digest"]
    else:
        assert current_parent["successor_operations_digest"] != parent["successor_operations_digest"]
    with pytest.raises(ValueError, match="late_control_pending_disposition_invalid"):
        freeze(signed)

    # The low-level primitive accepts its effective operations in a private copy.
    # A future dedicated owner must recheck the separately frozen review guard.
    applied = commit_exact_local_plan(repository, *IDENTITY, plan, max_operations=1)
    assert applied["state"] == "VERIFIED"
    result_history = repository.matches("Job History", {"Job Key": key})[0][1]
    assert result_history["Source Hash"] == new_source
    assert result_history["Decision"] == original_history["Decision"] == "Keep"
    if drift == "manual-choice-timestamp":
        assert repository.db.execute(
            "SELECT value,at FROM manual_choices WHERE tab='Job History' AND row_id=?", (row_id,),
        ).fetchone() == ("Keep", "fixture-owner-reasserted")
    else:
        assert result_history["Fit Level"] == "fixture-updated"
