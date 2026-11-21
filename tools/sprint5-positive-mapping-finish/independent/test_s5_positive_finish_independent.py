"""Independent disposable probes for the positive finisher's application boundary."""

import json

import pytest

from job_search_helper import ordinary_verification_finisher as finish
from job_search_helper import runtime_mapping_facts as facts
from job_search_helper.repository import RepositoryError
from job_search_helper.scrape_outcome_producer import normal_cycle_outcome_facts

from test_s5_live_mapping_finisher import (
    CYCLE_ID, COMPANY_ID, approved, attempt, close, fact_row, local_worker,
    measured_scope, published,
)


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_unapproved_byte_change_does_not_create_evidence(published, tmp_path):
    stores, _, _, verdict = published
    before = stores.state.cycle(CYCLE_ID)
    with approved(tmp_path, verdict) as (owner, receipt):
        changed = json.loads(receipt.read_bytes())
        changed['candidate_validation_sha256'] = 'f' * 64
        receipt.write_bytes(json.dumps(changed, sort_keys=True, separators=(',', ':')).encode())
        with pytest.raises(RepositoryError, match='approved live verdict changed'):
            close(published, owner)
    assert stores.state.cycle(CYCLE_ID) == before
    assert fact_row(stores) is None and stores.jobs.scrape_outcomes() == []


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_caller_result_dict_has_no_positive_authority(published):
    stores, _, _, verdict = published
    before = stores.state.cycle(CYCLE_ID)
    with pytest.raises(RepositoryError, match='configured live verdict'):
        close(published, verdict)
    assert stores.state.cycle(CYCLE_ID) == before
    assert fact_row(stores) is None and stores.jobs.scrape_outcomes() == []


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
@pytest.mark.parametrize('changed_store', ['state', 'publication', 'fact', 'company_claim'])
def test_changed_evidence_at_actual_insert_refuses_outcome(published, tmp_path, monkeypatch, changed_store):
    stores, _, _, verdict = published
    writer = stores.jobs._record_scrape_outcome_in_transaction

    def changed(*args, **kwargs):
        if changed_store == 'state':
            cycle = stores.state.cycle(CYCLE_ID)
            cycle['unrelated_checkpoint'] = 'newer progress'
            stores.state.save_cycle(cycle)
        elif changed_store == 'publication':
            with stores.inbox.connection:
                stores.inbox.connection.execute(
                    'UPDATE main.ordinary_verification_publications SET proof_sha256=? WHERE cycle=?',
                    ('0' * 64, CYCLE_ID),
                )
        elif changed_store == 'fact':
            with stores.state.connection:
                stores.state.connection.execute(
                    'UPDATE main.runtime_source_mapping_facts SET record_sha256=? WHERE cycle=?',
                    ('0' * 64, CYCLE_ID),
                )
        else:
            row_id, raw = next((row_id, raw) for row_id, raw in stores.jobs.db.execute(
                "SELECT row_id,data FROM main.records WHERE tab='Companies'",
            ).fetchall() if json.loads(raw).get('Company ID') == COMPANY_ID)
            company = json.loads(raw)
            company['Claimed By'] = 'another worker'
            stores.jobs.db.execute(
                "UPDATE main.records SET data=? WHERE tab='Companies' AND row_id=?",
                (json.dumps(company), row_id),
            )
        return writer(*args, **kwargs)

    with approved(tmp_path, verdict) as (owner, _):
        monkeypatch.setattr(stores.jobs, '_record_scrape_outcome_in_transaction', changed)
        with pytest.raises(RepositoryError):
            close(published, owner)
    assert stores.jobs.scrape_outcomes() == []
    assert finish._ACTIVE_WRITE.get() is None
    assert fact_row(stores) is not None


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_competing_state_checkpoint_rolls_back_fact_and_preserves_competitor(published, tmp_path, monkeypatch):
    stores, _, _, verdict = published
    persist = facts._persist_runtime_mapping_fact

    def before_transaction(*args, **kwargs):
        cycle = stores.state.cycle(CYCLE_ID)
        cycle['unrelated_checkpoint'] = 'newer progress'
        stores.state.save_cycle(cycle)
        return persist(*args, **kwargs)

    with approved(tmp_path, verdict) as (owner, _):
        monkeypatch.setattr(facts, '_persist_runtime_mapping_fact', before_transaction)
        with pytest.raises(ValueError, match='before the exact State seal'):
            close(published, owner)
    cycle = stores.state.cycle(CYCLE_ID)
    assert cycle['unrelated_checkpoint'] == 'newer progress'
    assert 'source_configuration_mapping_fact' not in cycle['companies'][COMPANY_ID]
    assert fact_row(stores) is None and stores.jobs.scrape_outcomes() == []


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_post_insert_failure_rolls_back_jobs_and_does_not_leak_permit(published, tmp_path, monkeypatch):
    stores, _, _, verdict = published
    writer = stores.jobs._record_scrape_outcome_in_transaction

    def after_insert(*args, **kwargs):
        writer(*args, **kwargs)
        raise RuntimeError('after insert before Jobs commit')

    with approved(tmp_path, verdict) as (owner, _):
        with monkeypatch.context() as cut:
            cut.setattr(stores.jobs, '_record_scrape_outcome_in_transaction', after_insert)
            with pytest.raises(RuntimeError, match='after insert'):
                close(published, owner)
        row = fact_row(stores)
        assert row is not None and stores.jobs.scrape_outcomes() == []
        assert finish._ACTIVE_WRITE.get() is None
        cycle = stores.state.cycle(CYCLE_ID)
        company = finish._current_company(stores.jobs, COMPANY_ID)
        generic = normal_cycle_outcome_facts(cycle, company, cycle['companies'][COMPANY_ID], storage_confirmed=True)
        with pytest.raises(RepositoryError, match='exact verification finisher'):
            stores.jobs.record_scrape_outcome(generic)
        with pytest.raises(RepositoryError, match='exact verification finisher'):
            stores.jobs.record_sealed_source_configuration_outcome(CYCLE_ID, COMPANY_ID, storage_confirmed=True)
        assert close(published, owner)['state'] == 'OUTCOME_STORED'
        assert fact_row(stores) == row and len(stores.jobs.scrape_outcomes()) == 1
