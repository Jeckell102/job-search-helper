"""Offline regressions for production routing and interrupted adapter scans."""
import json
from unittest.mock import patch

from job_search_helper.ats import FetchError, HTTPResponse, Inventory, _safe_api_url
from job_search_helper import gdit, gd_land_systems as gdls, hii, lockheed
from test_gdit import Transport, board, detail, resp
from test_lockheed import listing as lm_listing, detail as lm_detail


def test_gdls_real_transport_permits_pagination_and_details():
    _safe_api_url(gdls.SOURCE)
    _safe_api_url(gdls._page_url(gdls.SOURCE, 1))
    _safe_api_url('https://www.gd.com/careers/estimating-specialist-18408973-gdls-opportunity')


def test_gdls_real_transport_rejects_unrelated_paths_and_filters():
    for url in ('https://www.gd.com/login', gdls.SOURCE + '&company=other',
                'https://www.gd.com/careers/other-company-opportunity',
                'https://www.gd.com/careers/job-search?state=x&page=-1'):
        try:
            _safe_api_url(url)
        except FetchError:
            continue
        raise AssertionError('unrelated route accepted')


def test_gdit_complete_checkpoint_does_not_freeze_later_membership(tmp_path):
    path = tmp_path / 'gdit.json'
    first = gdit.fetch_gdit(gdit.SOURCE, gdit.COMPANY_ID, gdit.COMPANY,
                            Transport([resp(board()), resp(detail(1)), resp(board())]), path)
    assert first.status == 'complete'
    changed = Transport([resp(board(2)), resp(detail(2)), resp(board(2))])
    second = gdit.fetch_gdit(gdit.SOURCE, gdit.COMPANY_ID, gdit.COMPANY, changed, path)
    assert second.status == 'complete', second.reason
    assert second.jobs[0]['title'] == 'Role 2'


def test_gdit_interrupted_checkpoint_refreshes_membership_and_reuses_matching_details(tmp_path):
    path = tmp_path / 'gdit.json'
    initial = Transport([resp(board()), resp(detail(1)), resp(board())])
    assert gdit.fetch_gdit(gdit.SOURCE, gdit.COMPANY_ID, gdit.COMPANY, initial, path).status == 'complete'
    saved = json.loads(path.read_text()); saved['phase'] = 'details'; path.write_text(json.dumps(saved))
    resumed = Transport([resp(board()), resp(board())])
    result = gdit.fetch_gdit(gdit.SOURCE, gdit.COMPANY_ID, gdit.COMPANY, resumed, path)
    assert result.status == 'complete', result.reason
    assert len(resumed.posts) == 2 and not resumed.gets


class LockheedClient:
    def __init__(self, title):
        self.entry = dict(lm_listing(0), name=title)
        self.detail_calls = 0
    def search(self, start):
        return {'count': 1, 'positions': [self.entry], 'appliedFilters': {}}
    def detail(self, ident):
        self.detail_calls += 1
        return lm_detail(self.entry)


def test_lockheed_refreshes_details_after_completed_scan(tmp_path):
    path = tmp_path / 'lockheed.json'
    assert lockheed.scan(LockheedClient('Old title'), checkpoint_path=path).status == 'complete'
    current = LockheedClient('New title')
    result = lockheed.scan(current, checkpoint_path=path)
    assert result.status == 'complete'
    assert current.detail_calls == 1
    assert result.jobs[0]['title'] == 'New title'


def test_hii_never_completes_a_continuously_changing_inventory(tmp_path):
    def snapshot(_):
        snapshot.calls += 1
        ident = str(1000 + snapshot.calls)
        return 1, {ident: {'id': ident, 'title': 'Engineer', 'url': 'https://jobs.hii-tsd.com/job/Role/' + ident + '/'}}
    snapshot.calls = 0
    def detail_record(_, entry):
        return {'posting_id': entry['id'], 'req_id': entry['id'], 'title': entry['title'],
                'url': entry['url'], 'description': 'A full public body', 'is_closed': False}
    with patch.object(hii, '_snapshot', snapshot), patch.object(hii, '_detail', detail_record):
        result = hii.fetch_hii(hii.SOURCE, hii.COMPANY_ID, hii.COMPANY, object(), tmp_path / 'hii.json')
    assert result.status == 'partial', result.reason


def test_scope_blocker_cannot_be_overridden_by_generic_browser():
    from job_search_helper.browser_scraper import with_browser_fallback
    from job_search_helper.aethercomm import SOURCE, COMPANY_ID, COMPANY
    from job_search_helper.ats import fetch_inventory
    class Page:
        def get(self, url): return HTTPResponse(200, b'Frontgrade Aethercomm')
    def direct(ats, url, cid, company):
        return fetch_inventory(ats, url, cid, company, discovery_transport=Page())
    browser = Inventory('partial', [{'posting_id': 'other-parent-role', 'title': 'Other subsidiary', 'url': SOURCE}], 'unscoped', SOURCE, 'Browser')
    with patch('job_search_helper.browser_scraper.fetch_browser_inventory', return_value=browser) as fetch:
        result = with_browser_fallback(direct)('Frontgrade shared careers', SOURCE, COMPANY_ID, COMPANY)
    assert not fetch.called
    assert not result.jobs


def test_interrupted_checkpoint_requires_matching_metadata_and_never_reuses_closure():
    from job_search_helper.detail_checkpoint import reusable_details
    saved = {'phase': 'details', 'entries': [{'id': '1', 'title': 'Old'}],
             'jobs': [{'posting_id': '1', 'description': 'Old detail'}]}
    kwargs = {'entry_id': lambda e: e['id'], 'job_id': lambda j: j['posting_id']}
    assert reusable_details(saved, [{'id': '1', 'title': 'New'}], **kwargs) == {}
    assert reusable_details(saved, [], **kwargs) == {}
    assert reusable_details(saved, saved['entries'], **kwargs)['1']['description'] == 'Old detail'
    saved['jobs'][0]['is_closed'] = True
    assert reusable_details(saved, saved['entries'], **kwargs) == {}


def test_completed_checkpoint_refreshes_hii_and_gdls_details(tmp_path):
    from test_hii import HiiBoard
    from test_gd_land_systems import Pages
    hii_path, gdls_path = tmp_path / 'hii.json', tmp_path / 'gdls.json'
    for _ in range(2):
        board = HiiBoard()
        with patch.object(hii, '_detail', wraps=hii._detail) as detail_fetch:
            result = hii.fetch_hii(hii.SOURCE, hii.COMPANY_ID, hii.COMPANY, board, hii_path)
            assert result.status == 'complete', result.reason
            assert detail_fetch.call_count == 2
        pages = Pages()
        result = gdls.fetch_gd_land_systems(gdls.SOURCE, 'COMP-0097', 'General Dynamics Land Systems', pages, gdls_path)
        assert result.status == 'complete', result.reason
        assert len([url for url in pages.calls if url != gdls.SOURCE]) == 1


def test_scoped_workday_adapters_do_not_publish_unattributed_partial_jobs():
    from job_search_helper import linquest, rapiddeploy
    for adapter, url, cid, company, fetch, provider in (
        (linquest, 'https://kbr.wd5.myworkdayjobs.com/en-US/KBR_Careers?q=LinQuest', 'COMP-0016', 'LinQuest', linquest.fetch_linquest, 'Workday'),
        (rapiddeploy, rapiddeploy.SOURCE, rapiddeploy.COMPANY_ID, rapiddeploy.COMPANY, rapiddeploy.fetch_rapiddeploy, rapiddeploy.ATS),
    ):
        for status in ('complete', 'partial'):
            unscoped = {'posting_id': 'parent-role', 'title': 'Parent role', 'description': 'KBR or Motorola job', 'url': url}
            with patch.object(adapter, 'fetch_workday', return_value=Inventory(status, [unscoped], 'original failure', url, provider)):
                result = fetch(url, cid, company, object())
            assert result.status != 'complete'
            assert not result.jobs
            assert not result.browser_fallback_allowed


def test_kbr_legacy_completed_ids_cannot_hide_jobs(tmp_path):
    from job_search_helper import kbr
    from test_kbr import Public, Workday
    checkpoint = tmp_path / 'kbr.json'
    checkpoint.write_text(json.dumps({'completed_ids': ['R123']}))
    result = kbr.fetch_kbr(kbr.SOURCE, 'c', 'KBR', Public(), Workday(total=1), checkpoint)
    assert result.status == 'complete', result.reason
    assert len(result.jobs) == 1


def test_kbr_completed_checkpoint_refreshes_details_and_interrupted_scan_can_resume(tmp_path):
    from job_search_helper import kbr
    from test_kbr import Public, Workday
    checkpoint = tmp_path / 'kbr.json'
    for _ in range(2):
        client = Workday(total=1)
        result = kbr.fetch_kbr(kbr.SOURCE, 'c', 'KBR', Public(), client, checkpoint)
        assert result.status == 'complete', result.reason
        assert client.get_calls == 1
    saved = json.loads(checkpoint.read_text()); saved['phase'] = 'details'
    checkpoint.write_text(json.dumps(saved))
    client = Workday(total=1)
    result = kbr.fetch_kbr(kbr.SOURCE, 'c', 'KBR', Public(), client, checkpoint)
    assert result.status == 'complete', result.reason
    assert len(result.jobs) == 1 and client.get_calls == 0


def test_deployable_rereads_every_listing_page():
    from job_search_helper import deployable
    records = [[{'id': str(i), 'status': 'expired'}] for i in (1, 2)]
    calls = []
    def listing(client, page=None):
        calls.append(page)
        return records[0 if page is None else page - 1], 2
    with patch.object(deployable, '_listing', listing):
        result = deployable.fetch_deployable(deployable.SOURCE, deployable.COMPANY_ID, deployable.COMPANY, object())
    assert result.status == 'complete', result.reason
    assert calls == [None, 2, None, 2]


def test_scythe_pagination_cap_cannot_be_reported_complete():
    from job_search_helper import scythe_robotics as scythe
    def read(client, url):
        return url, 'Scythe Robotics no positions available at this time'
    def pages(current, url):
        number = int(url.rsplit('=', 1)[-1]) if '?page=' in url else 0
        return [scythe.SOURCE + '?page=' + str(number + 1)]
    with patch.object(scythe, '_read', read), patch.object(scythe, '_pagination_urls', pages), patch.object(scythe, '_role_urls', return_value=[]):
        result = scythe.fetch_scythe_robotics(scythe.SOURCE, scythe.COMPANY_ID, scythe.COMPANY, object())
    assert result.status == 'partial', result.reason
    assert 'limit' in result.reason.lower()


def test_checkpoint_reuse_is_scoped_to_the_current_scan(tmp_path):
    from job_search_helper.cooperative_fetch import CooperativeFetchWork
    checkpoint = tmp_path / 'gdit-scoped.json'
    with CooperativeFetchWork(scope_id='cycle-1').bind_worker('GDIT'):
        client = Transport([resp(board()), resp(detail(1)), resp(board())])
        assert gdit.fetch_gdit(gdit.SOURCE, gdit.COMPANY_ID, gdit.COMPANY, client, checkpoint).status == 'complete'
    saved = json.loads(checkpoint.read_text()); saved['phase'] = 'details'
    checkpoint.write_text(json.dumps(saved))
    with CooperativeFetchWork(scope_id='cycle-1').bind_worker('GDIT'):
        client = Transport([resp(board()), resp(board())])
        assert gdit.fetch_gdit(gdit.SOURCE, gdit.COMPANY_ID, gdit.COMPANY, client, checkpoint).status == 'complete'
        assert not client.gets
    saved = json.loads(checkpoint.read_text()); saved['phase'] = 'details'
    checkpoint.write_text(json.dumps(saved))
    with CooperativeFetchWork(scope_id='cycle-2').bind_worker('GDIT'):
        client = Transport([resp(board()), resp(detail(1)), resp(board())])
        assert gdit.fetch_gdit(gdit.SOURCE, gdit.COMPANY_ID, gdit.COMPANY, client, checkpoint).status == 'complete'
        assert len(client.gets) == 1


def test_malformed_cached_gdit_url_is_refetched(tmp_path):
    checkpoint = tmp_path / 'bad-gdit.json'
    initial = Transport([resp(board()), resp(detail(1)), resp(board())])
    assert gdit.fetch_gdit(gdit.SOURCE, gdit.COMPANY_ID, gdit.COMPANY, initial, checkpoint).status == 'complete'
    saved = json.loads(checkpoint.read_text()); saved['phase'] = 'details'
    saved['jobs'][0]['url'] = 'https://example.test/jobs/1'
    checkpoint.write_text(json.dumps(saved))
    client = Transport([resp(board()), resp(detail(1)), resp(board())])
    result = gdit.fetch_gdit(gdit.SOURCE, gdit.COMPANY_ID, gdit.COMPANY, client, checkpoint)
    assert result.status == 'complete', result.reason
    assert len(client.gets) == 1


def test_hii_nonobject_checkpoint_is_ignored(tmp_path):
    from test_hii import HiiBoard
    for invalid in ('[]', 'null', '"old-format"'):
        checkpoint = tmp_path / 'hii-invalid.json'
        checkpoint.write_text(invalid)
        result = hii.fetch_hii(hii.SOURCE, hii.COMPANY_ID, hii.COMPANY, HiiBoard(), checkpoint)
        assert result.status == 'complete', result.reason
        assert len(result.jobs) == 2


def _fallback_result(direct_jobs, browser_jobs):
    from job_search_helper.browser_scraper import with_browser_fallback
    direct = lambda *args: Inventory('partial', direct_jobs, 'one detail unavailable', 'https://example.com/careers', 'ADP')
    browser = Inventory('partial', browser_jobs, 'unknown membership', 'https://example.com/careers', 'Browser')
    with patch('job_search_helper.browser_scraper.fetch_browser_inventory', return_value=browser):
        return with_browser_fallback(direct)('ADP', 'https://example.com/careers', 'C-1', 'Acme')


def test_fallback_native_identity_survives_duplicate_delivery_to_engine(tmp_path):
    from job_search_helper.browser_scraper import _posting_id
    from job_search_helper.engine import Engine, State
    from job_search_helper.repository import MemoryRepository
    from test_engine import company, posting
    native = posting('REAL-1', ats='ADP', url='https://example.com/jobs/1?jobId=123')
    browser_url = native['url'] + '&utm_source=careers'
    synthetic = dict(native, posting_id=_posting_id(browser_url), ats='Browser', url=browser_url)
    result = _fallback_result([native], [synthetic, synthetic])
    assert result.status == 'partial'
    state = State(tmp_path / 'fallback.db')
    repo = MemoryRepository({'Companies': [company()]})
    try:
        engine = Engine(repo, state)
        with patch('job_search_helper.engine.classify_title', return_value='review'):
            for row in [*result.jobs, *result.jobs]:
                engine._stage_posting({}, company(), row)
        history = repo.read('Job History')
        assert len(history) == 1
        assert history[0]['Requisition ID'] == 'REAL-1'
        assert result.jobs == [native]
    finally:
        state.close()


def test_fallback_preserves_real_identity_conflicts_and_unrelated_hashes(tmp_path):
    import pytest
    from job_search_helper.browser_scraper import _posting_id
    from job_search_helper.engine import Engine, State
    from job_search_helper.repository import MemoryRepository
    from test_engine import company, posting
    native = posting('REAL-1', ats='ADP', url='https://example.com/jobs/1')
    for other_id in ('REAL-2', _posting_id('https://example.com/jobs/another')):
        other = dict(native, posting_id=other_id)
        result = _fallback_result([native], [other])
        assert result.jobs == [native, other]
        state = State(tmp_path / (other_id + '.db'))
        try:
            engine = Engine(MemoryRepository({'Companies': [company()]}), state)
            with patch('job_search_helper.engine.classify_title', return_value='review'):
                engine._stage_posting({}, company(), result.jobs[0])
                with pytest.raises(ValueError, match='disambiguation'):
                    engine._stage_posting({}, company(), result.jobs[1])
        finally:
            state.close()


def test_fallback_does_not_silently_drop_records_without_identity():
    direct = [{'title': 'Direct A'}, {'title': 'Direct B'}]
    browser = [{'title': 'Browser C', 'posting_id': 'browser-unknown'}]
    assert _fallback_result(direct, browser).jobs == direct + browser
