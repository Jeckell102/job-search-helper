import pytest

from job_search_helper.company_events import source_revision

from job_search_helper.ordinary_verification_outcome import existing_outcome
from job_search_helper.ordinary_verification_pending import MARKER, digest
from job_search_helper.repository import RepositoryError
from job_search_helper.scrape_outcome_producer import record_cycle_outcomes
from job_search_helper.sqlite_repository import SQLiteRepository


OWNER = {"cycle_id": "CYC-2F654B5B98D8", "request_id": "ordinary-fixture",
         "company_id": "COMP-4510", "source_revision": "9" * 64}


@pytest.fixture
def jobs(tmp_path):
    repo = SQLiteRepository(tmp_path / "jobs.db", "fixture", initialize=True)
    yield repo
    repo.close()


def record(jobs, *, cycle_id=OWNER["cycle_id"], status="partial", use_cycle=True):
    facts = {key: OWNER[key] for key in ("request_id", "company_id", "source_revision")}
    if use_cycle:
        facts["cycle_id"] = cycle_id
    facts.update(source_current=True, company_status="Active", storage_status="confirmed",
                 inventory_status=status, failure={"category": "unknown"})
    return jobs.record_scrape_outcome(facts)["outcome"]


@pytest.mark.parametrize("inventory_status", ["partial", "complete"])
def test_prior_exact_outcome_wins_regardless_of_classification(jobs, inventory_status):
    row = record(jobs, status=inventory_status)
    assert existing_outcome(jobs, OWNER) == {
        "outcome_id": row["outcome_id"], "payload_sha256": digest(row), "outcome": row,
    }
    assert jobs.db.execute("SELECT count(*) FROM scrape_outcomes").fetchone() == (1,)


def test_other_cycle_remains_untouched(jobs):
    record(jobs, cycle_id="CYC-OTHER")
    assert existing_outcome(jobs, OWNER) is None
    exact = record(jobs)
    assert existing_outcome(jobs, OWNER)["outcome"] == exact
    assert jobs.db.execute("SELECT count(*) FROM scrape_outcomes").fetchone() == (2,)


def test_inconsistent_index_is_not_a_prior_outcome(jobs):
    record(jobs)
    jobs.db.execute("UPDATE scrape_outcomes SET action='different'")
    with pytest.raises(RepositoryError, match="indexed identity"):
        existing_outcome(jobs, OWNER)


def test_duplicated_json_key_cannot_match_canonical_storage(jobs):
    record(jobs)
    original = jobs.db.execute("SELECT payload FROM scrape_outcomes").fetchone()[0]
    duplicate = '{"action":"stale earlier value",' + original[1:]
    jobs.db.execute("UPDATE scrape_outcomes SET payload=?", (duplicate,))
    with pytest.raises(RepositoryError, match="invalid immutable"):
        existing_outcome(jobs, OWNER)


def test_two_prior_exact_records_are_ambiguous(jobs):
    record(jobs, status="partial")
    record(jobs, status="complete")
    with pytest.raises(RepositoryError, match="Multiple immutable"):
        existing_outcome(jobs, OWNER)


def test_legacy_same_key_without_cycle_remains_held(jobs):
    record(jobs, use_cycle=False)
    with pytest.raises(RepositoryError, match="cannot be attributed"):
        existing_outcome(jobs, OWNER)


def test_generic_producer_cannot_write_enrolled_or_malformed_marker(jobs):
    company = {"Company ID": OWNER["company_id"], "Company": "Forterra",
               "Company Status": "Active", "ATS / Source": "Rippling",
               "Official Careers URL": "https://example.test/jobs"}
    item = {"stage": "partial", "inventory_status": "partial",
            "outcome_source_revision": source_revision(company)}
    cycle = {"id": OWNER["cycle_id"], "start_request_id": OWNER["request_id"],
             "companies": {OWNER["company_id"]: item}}
    item[MARKER] = {"state": "ARMED"}
    assert record_cycle_outcomes(jobs, cycle, [company], storage_confirmed=True) == []
    item[MARKER] = None
    assert record_cycle_outcomes(jobs, cycle, [company], storage_confirmed=True) == []
    del item[MARKER]
    assert len(record_cycle_outcomes(jobs, cycle, [company], storage_confirmed=True)) == 1
