import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


MODULE = Path(__file__).parents[1] / "confirm_recipe_candidate.py"
SPEC = importlib.util.spec_from_file_location("confirmation_observer", MODULE)
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)


class Response:
    def __init__(self, status, headers):
        self.status, self.headers = status, headers


class Request:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []
    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.response


class Client:
    def __init__(self, request):
        self.request = request


def test_observer_forwards_one_unchanged_request_and_sanitizes_status_delay():
    request = Request(Response(503, {"Retry-After": "2"}))
    client, observations = Client(request), []
    original = request.get
    def body(target, url):
        response = target.request.get(url, max_redirects=0, timeout=30_000)
        assert response is request.response
        return "unchanged body"
    assert observer.observe_detail_response(client, "https://example.test/detail", body, observations) == "unchanged body"
    assert request.calls == [(("https://example.test/detail",), {"max_redirects": 0, "timeout": 30_000})]
    assert observations == [{"status": 503, "retry_after_seconds": 2.0}]
    assert client.request.get.__self__ is original.__self__ and client.request.get.__func__ is original.__func__


@pytest.mark.parametrize("value", (None, "not-a-delay", "-1", "nan", "inf"))
def test_unparseable_negative_or_nonfinite_retry_after_is_not_reported(value):
    assert observer.retry_after_observation({"Retry-After": value}) == {}


def test_records_provider_cooldown_up_to_one_day_and_marks_longer_without_raw_value():
    assert observer.retry_after_observation({"Retry-After": "3600"}) == {"retry_after_seconds": 3600.0}
    assert observer.retry_after_observation({"Retry-After": "86401"}) == {"retry_after_exceeds_observation_bound": True}


def test_http_date_retry_after_uses_same_standard_date_grammar_as_adapter():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    value = (now + timedelta(seconds=120)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert observer.retry_after_observation({"retry-after": value}, now=now) == {"retry_after_seconds": 120.0}


@pytest.mark.parametrize("status", ("429", 99, 600, True, None))
def test_non_http_status_is_not_logged(status):
    request = Request(Response(status, {"Retry-After": "120"}))
    observations = []
    observer.observe_detail_response(Client(request), "https://example.test/detail",
                                     lambda target, url: target.request.get(url), observations)
    assert observations == []


def test_failure_keeps_request_behavior_and_restores_getter():
    request = Request(error=TimeoutError("fixture timeout"))
    client, observations = Client(request), []
    original = request.get
    with pytest.raises(TimeoutError, match="fixture timeout"):
        observer.observe_detail_response(client, "https://example.test/detail",
                                         lambda target, url: target.request.get(url), observations)
    assert len(request.calls) == 1 and observations == []
    assert client.request.get.__self__ is original.__self__ and client.request.get.__func__ is original.__func__


def test_first_429_exits_actual_adapter_retries_before_body_or_second_get():
    from job_search_helper.acquiretm import _DetailClient

    class LimitedResponse(Response):
        def body(self):
            pytest.fail("the first 429 body must not be read")

    request = Request(LimitedResponse(429, {"Retry-After": "3600", "X-Private": "omit"}))
    original_get = request.get
    client = _DetailClient(request, sleep=lambda _: None)
    observations = []
    url = "https://example.test/detail"

    with pytest.raises(observer.DetailRateLimitHold) as exc:
        observer.observe_detail_response(client, url, _DetailClient.get_body, observations)

    assert request.calls == [((url,), {"max_redirects": 0, "timeout": 30_000})]
    assert observations == [exc.value.evidence]
    evidence = observations[0]
    assert set(evidence) == {"status", "observed_at_utc", "retry_after_seconds", "retry_not_before_utc"}
    assert evidence["status"] == 429 and evidence["retry_after_seconds"] == 3600
    observed = datetime.fromisoformat(evidence["observed_at_utc"])
    assert datetime.fromisoformat(evidence["retry_not_before_utc"]) == observed + timedelta(hours=1)
    assert request.get == original_get


@pytest.mark.parametrize("headers,special", [
    ({"Retry-After": "invalid"}, {}),
    ({"Retry-After": "86401"}, {"retry_after_exceeds_observation_bound": True}),
])
def test_429_without_bounded_deadline_still_holds(headers, special):
    request = Request(Response(429, headers))
    with pytest.raises(observer.DetailRateLimitHold) as exc:
        observer.observe_detail_response(Client(request), "https://example.test/detail",
                                         lambda target, url: target.request.get(url), [])
    assert len(request.calls) == 1
    evidence = exc.value.evidence
    assert {key: value for key, value in evidence.items() if key != "observed_at_utc"} == {
        "status": 429, **special,
    }


def test_429_http_date_records_exact_future_deadline():
    deadline = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=1)
    request = Request(Response(429, {"Retry-After": deadline.strftime("%a, %d %b %Y %H:%M:%S GMT")}))
    with pytest.raises(observer.DetailRateLimitHold) as exc:
        observer.observe_detail_response(Client(request), "https://example.test/detail",
                                         lambda target, url: target.request.get(url), [])
    assert datetime.fromisoformat(exc.value.evidence["retry_not_before_utc"]) == deadline
    assert len(request.calls) == 1


def test_latched_429_refuses_any_later_get_even_if_adapter_suppresses_abort():
    request = Request(Response(429, {}))
    client = Client(request)
    caught = []

    def attempted_retry(target, url):
        for _ in range(2):
            try:
                target.request.get(url)
            except observer.DetailRateLimitHold as hold:
                caught.append(hold)
        return "must not become a result"

    with pytest.raises(observer.DetailRateLimitHold) as exc:
        observer.observe_detail_response(client, "https://example.test/detail", attempted_retry, [])

    assert len(request.calls) == 1
    assert caught == [exc.value, exc.value]


def test_real_adapter_keeps_normal_transport_retry_behavior():
    from job_search_helper.acquiretm import FetchError, _DetailClient

    failure = TimeoutError("fixture timeout")
    request = Request(error=failure)
    observations = []
    url = "https://example.test/detail"
    with pytest.raises(FetchError, match="timed out after bounded retries") as exc:
        observer.observe_detail_response(_DetailClient(request, sleep=lambda _: None), url,
                                         _DetailClient.get_body, observations)
    assert request.calls == [((url,), {"max_redirects": 0, "timeout": 30_000})] * 3
    assert exc.value.__cause__ is failure and observations == []


def test_main_emits_only_held_terminal_outcome_for_429(monkeypatch, capsys):
    import json
    import sys

    from job_search_helper import acquiretm, ats

    candidate = Path("/tmp/jsh-fresh-amphenol-qualification.FdVVPAdT/candidate")
    request = Request(Response(429, {"Retry-After": "3600"}))
    fetched = []

    def offline_dispatch(*args):
        fetched.append(args)
        return acquiretm._DetailClient(request, sleep=lambda _: None).get_body("https://example.test/detail")

    monkeypatch.setattr(sys, "argv", [str(MODULE), str(candidate)])
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(ats, "fetch_inventory", offline_dispatch)
    for owner, name in ((acquiretm, "parse_listing"), (acquiretm, "inventory"),
                        (acquiretm._DetailClient, "get_body")):
        monkeypatch.setattr(owner, name, getattr(owner, name))

    assert observer.main() == 1
    assert fetched == [("AcquireTM", acquiretm.SOURCE, "COMP-0490", "Amphenol Aerospace")]
    assert len(request.calls) == 1
    log = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [entry["stage"] for entry in log] == [
        "started", "detail_request_spacing", "held_provider_rate_limit",
    ]
    assert log[0]["detail_gap_seconds"] == 12
    assert log[-1]["status"] == 429 and log[-1]["retry_after_seconds"] == 3600
    assert "retry_not_before_utc" in log[-1]


def test_real_non_429_retry_preserves_delegation_and_validated_body_cache():
    from job_search_helper.acquiretm import _DetailClient

    content = b"<!doctype html><html><body>Fixture posting detail</body></html>"

    class BodyResponse(Response):
        def body(self):
            return content

    class SequenceRequest:
        def __init__(self):
            self.responses = iter((
                BodyResponse(503, {"Retry-After": "2"}),
                BodyResponse(200, {"Content-Type": "text/html; charset=utf-8"}),
            ))
            self.calls = []

        def get(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return next(self.responses)

    request = SequenceRequest()
    client = _DetailClient(request, sleep=lambda _: None)
    observations = []
    url = "https://example.test/detail"
    assert observer.observe_detail_response(client, url, _DetailClient.get_body, observations) == content.decode()
    assert observer.observe_detail_response(client, url, _DetailClient.get_body, observations) == content.decode()
    assert request.calls == [((url,), {"max_redirects": 0, "timeout": 30_000})] * 2
    assert observations == [{"status": 503, "retry_after_seconds": 2.0}, {"status": 200}]


def test_pacer_waits_after_finished_responses_and_errors(monkeypatch):
    class Clock:
        now = 100.0

        def advance(self, seconds):
            self.now += seconds

    clock = Clock()
    log = []
    monkeypatch.setattr(observer, "emit", log.append)
    pacer = observer.DetailPacer(clock=lambda: clock.now, sleep=clock.advance)
    started = []

    def get(*, fail=False):
        started.append(clock.now)
        clock.advance(2)
        if fail:
            raise TimeoutError("synthetic network timeout")
        return Response(200, {})

    assert pacer.request(get).status == 200
    with pytest.raises(TimeoutError):
        pacer.request(get, fail=True)
    assert pacer.request(get).status == 200
    assert started == [100, 114, 128]
    assert [row["seconds_since_previous_response"] for row in log] == [None, 12, 12]
    assert pacer.wait() == 12
    assert clock.now == 142


@pytest.mark.parametrize("status", (429, 503))
def test_pacing_log_cannot_mask_a_received_provider_hold(monkeypatch, status):
    from job_search_helper.acquiretm import _DetailClient

    request = Request(Response(status, {"Retry-After": "3600"}))

    def output(_):
        if request.calls:
            raise OSError("fixture output failed after provider response")

    monkeypatch.setattr(observer, "emit", output)
    client = _DetailClient(request, sleep=lambda _: None)
    pacer = observer.DetailPacer()
    with pytest.raises(observer.DetailRateLimitHold) as held:
        observer.observe_detail_response(client, "https://example.test/detail",
                                         _DetailClient.get_body, [], pacer=pacer)
    assert len(request.calls) == 1
    assert held.value.evidence["status"] == status
    assert held.value.evidence["retry_after_seconds"] == 3600
