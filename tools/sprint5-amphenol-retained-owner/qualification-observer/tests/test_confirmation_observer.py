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
    request = Request(Response(429, {"Retry-After": "2"}))
    client, observations = Client(request), []
    original = request.get
    def body(target, url):
        response = target.request.get(url, max_redirects=0, timeout=30_000)
        assert response is request.response
        return "unchanged body"
    assert observer.observe_detail_response(client, "https://example.test/detail", body, observations) == "unchanged body"
    assert request.calls == [(("https://example.test/detail",), {"max_redirects": 0, "timeout": 30_000})]
    assert observations == [{"status": 429, "retry_after_seconds": 2.0}]
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
