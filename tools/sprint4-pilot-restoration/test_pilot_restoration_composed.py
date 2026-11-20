"""Join real disposable retained application and receiver evidence to exchange recovery."""
from contextlib import closing, contextmanager

from coordinator_store import OUTCOME_DELIVERY_CONSUMER, Store
from job_search_helper import cli
from job_search_helper.retained_pilot_terminal import verify_retained_pilot_terminal
from job_search_helper.scrape_outcome_delivery import OutcomeDelivery
from pilot_restoration import SCHEMA, exchange_identity
from retained_pilot_receiver import verify_pilot_delivery
from test_host_exchange import fixture as exchange_fixture, states
from test_pilot_restoration import JointTerminal, run
from test_retained_pilot_terminal import pilot


def test_exact_signed_pilot_and_matching_receiver_proof_allow_one_restoration(pilot, exchange_fixture, tmp_path):
    application, result, selected = pilot
    exchange, _ = exchange_fixture
    exchange.prepare()
    closure = exchange.close()
    receiver = Store(tmp_path / "receiver")

    class DirectFixtureSink:
        def ingest_immutable(self, record):
            return receiver.ingest_scrape_outcome_delivery_v1(OUTCOME_DELIVERY_CONSUMER, record)

    with closing(application.local(write=True)) as writer:
        events = OutcomeDelivery(writer, DirectFixtureSink()).drain(outcome_id=result["outcome_id"])
    assert events == [{"outcome_id": result["outcome_id"], "disposition": "ACCEPTED"}]

    class LockedJointTerminal(JointTerminal):
        @contextmanager
        def restoration_terminal(self):
            with (cli.writer_lock(application.root / "scraper.lock"),
                  cli.writer_lock(application.root / "writer.lock"),
                  super().restoration_terminal() as release):
                yield release

    joint = LockedJointTerminal()

    def read_existing_pilot():
        assert joint.held
        with closing(application.local()) as reader:
            return verify_pilot_delivery(verify_retained_pilot_terminal(reader, **selected), receiver.path)

    protected = ("state.db", "inventories.sqlite3", "jobs.sqlite3", "retained-sessions.sqlite3")
    before = {name: (application.root / name).read_bytes() for name in protected}
    with joint.restoration_terminal() as release:
        approval = {"schema": SCHEMA, "release": release, "exchange": exchange_identity(closure),
                    "pilot": read_existing_pilot()}
    restored = run(joint, exchange, approval, read_existing_pilot)
    assert restored.phase == "restored"
    assert states(exchange) == [True, True, True]
    assert run(joint, exchange, approval, read_existing_pilot) == restored
    assert {name: (application.root / name).read_bytes() for name in protected} == before
    application.assert_historical_records_unchanged()
