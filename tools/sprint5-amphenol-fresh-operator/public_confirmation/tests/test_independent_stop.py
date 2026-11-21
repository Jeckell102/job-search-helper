import sys, json
from types import SimpleNamespace
from datetime import datetime, timedelta
import pytest
from test_confirmation_observer import observer, Response, Request, Client, MODULE

def test_real_client_bad_headers_still_stops_before_body_and_retry():
    from job_search_helper.acquiretm import _DetailClient
    class BadHeaders:
        status = 429
        @property
        def headers(self): raise RuntimeError("private header diagnostic must not escape")
        def body(self): pytest.fail("body access after 429")
    request=Request(BadHeaders()); original=request.get; observations=[]
    with pytest.raises(observer.DetailRateLimitHold) as error:
        observer.observe_detail_response(_DetailClient(request,sleep=lambda _:None), "https://example.test/one", _DetailClient.get_body, observations)
    assert len(request.calls)==1 and request.get==original
    assert set(error.value.evidence)=={"status","observed_at_utc"}
    assert observations==[error.value.evidence]

def test_suppressed_hold_then_real_cached_body_cannot_escape():
    from job_search_helper.acquiretm import _DetailClient
    request=Request(Response(429,{})); client=_DetailClient(request,sleep=lambda _:None)
    client.bodies["https://example.test/cached"]="validated cached body"
    def body(target,url):
        try: _DetailClient.get_body(target,url)
        except BaseException: pass
        try: target.request.get("https://example.test/different")
        except BaseException: pass
        return _DetailClient.get_body(target,"https://example.test/cached")
    with pytest.raises(observer.DetailRateLimitHold):
        observer.observe_detail_response(client,"https://example.test/limited",body,[])
    assert len(request.calls)==1

@pytest.mark.parametrize("delay",[0,86400])
def test_supported_delay_bound_is_exact_not_runtime_capped(delay):
    request=Request(Response(429,{"Retry-After":str(delay)}))
    with pytest.raises(observer.DetailRateLimitHold) as error:
        observer.observe_detail_response(Client(request),"https://example.test/detail",lambda c,u:c.request.get(u),[])
    e=error.value.evidence
    assert datetime.fromisoformat(e["retry_not_before_utc"])-datetime.fromisoformat(e["observed_at_utc"])==timedelta(seconds=delay)
    assert len(request.calls)==1

def test_actual_dispatch_adapter_closes_fixture_context_and_holds(monkeypatch,capsys):
    from job_search_helper import ats,acquiretm
    import playwright.sync_api
    request=Request(Response(429,{"Retry-After":"3600"})); calls=[]
    class Browser:
        def new_context(self):return SimpleNamespace(request=request,new_page=lambda:object())
        def close(self):calls.append("browser_closed")
    class PlaywrightContext:
        def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw:Browser()))
        def __exit__(self,*args):calls.append("context_exited")
    monkeypatch.setattr(playwright.sync_api,"sync_playwright",PlaywrightContext)
    monkeypatch.setattr(acquiretm,"inventory",lambda *a,**kw:{"fixture":{"url":"https://example.test/detail"}})
    monkeypatch.setattr(acquiretm._DetailClient,"get_body",acquiretm._DetailClient.get_body)
    monkeypatch.setattr(acquiretm,"parse_listing",acquiretm.parse_listing)
    monkeypatch.setattr(sys,"argv",[str(MODULE),"/tmp/jsh-amphenol-current-validation.fehq8g9f/candidate"])
    monkeypatch.setattr(sys,"path",list(sys.path))
    assert observer.main()==1
    assert len(request.calls)==1 and calls==["browser_closed","context_exited"]
    records=[json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["stage"] for r in records]==["started","listing_observed","held_provider_rate_limit"]
    assert records[-1]["status"]==429
