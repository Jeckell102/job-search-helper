from job_search_helper.rapiddeploy import COMPANY, COMPANY_ID, SOURCE, fetch_rapiddeploy


def test_source_guard():
    assert fetch_rapiddeploy("https://example.com", COMPANY_ID, COMPANY).status == "unsupported"
    assert fetch_rapiddeploy(SOURCE, "OTHER", COMPANY).status == "unsupported"


def test_result_is_fail_closed_when_workday_is_not_complete(monkeypatch):
    from job_search_helper.ats import Inventory
    monkeypatch.setattr("job_search_helper.rapiddeploy.fetch_workday",
                        lambda *args: Inventory("partial", reason="network failure"))
    result = fetch_rapiddeploy(SOURCE, COMPANY_ID, COMPANY, object())
    assert result.status == "partial"
    assert "network failure" in result.reason


def test_source_is_https_rapiddeploy_query():
    assert SOURCE.startswith("https://motorolasolutions.wd5.myworkdayjobs.com/")
    assert "q=RapidDeploy" in SOURCE


def test_official_careers_repair_selects_guarded_source():
    from job_search_helper.company_sources import repair_source
    ats, url, _ = repair_source(
        "Browser",
        "https://www.motorolasolutions.com/en_us/about/careers.html",
        COMPANY_ID,
        COMPANY,
    )
    assert ats == "Workday (RapidDeploy scoped)"
    assert url == SOURCE
