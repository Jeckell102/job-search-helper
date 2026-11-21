"""Bounded composition proof; accepted source remains otherwise byte-identical."""

import pytest

from test_s5_live_mapping_finisher import approved, close, fact_row, published
from test_s5_ordinary_publication_continuation import measured_scope
from test_s5_ordinary_worker_handoff import local_worker
from test_ordinary_verification_pending import attempt


@pytest.mark.parametrize("measured_scope", [True], indirect=True)
def test_preapproved_forterra_fact_is_default_off_then_exactly_one_typed_outcome(published, tmp_path):
    """The normal prepared route is inert until the approved owned verdict arrives."""
    stores, _, _, verdict = published
    assert close(published) == {"state": "VERIFICATION_PENDING"}
    assert fact_row(stores) is None and stores.jobs.scrape_outcomes() == []

    with approved(tmp_path, verdict) as (owner, _):
        first = close(published, owner)
        replay = close(published, owner)

    assert first["state"] == "OUTCOME_STORED"
    assert replay["state"] == "ALREADY_STORED"
    outcomes = stores.jobs.scrape_outcomes()
    assert len(outcomes) == 1
    assert (outcomes[0]["outcome"], outcomes[0]["action"], outcomes[0]["repair_category"]) == (
        "QUALIFIED_INTEGRATION_REPAIR", "upsert_qualified_repair", "same_provider_source_mapping",
    )
