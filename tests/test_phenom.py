from contextlib import redirect_stderr
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from job_search_helper.ats import FetchError, HTTPResponse, Inventory, fetch_inventory
from job_search_helper.browser_scraper import with_browser_fallback
from job_search_helper.engine import _inventory_source
from job_search_helper.phenom import _read, _listing, _posting, _identity, fetch_phenom
from test_ats import Transport


BASE = "https://careers.example.com/us/en/"
SOURCE = BASE + "search-results"
APP = {"refNum": "ACMEUS", "baseUrl": BASE, "siteType": "external", "locale": "en_us"}


def entry(number=1, **changes):
    return dict({"jobId": str(number), "jobSeqNo": f"ACMEUS{number}EXTERNALENUS",
                 "title": f"Systems Engineer {number}", "siteType": "external", "jobVisibility": ["external"]}, **changes)


def html(ddo=None, app=None, params=None):
    body = ('<html><script>/*&lt;!--*/ var phApp = phApp || ' + json.dumps(app or APP)
            + '; phApp.ddo = ' + json.dumps(ddo or {})
            + '; phApp.sessionParams = ' + json.dumps(params or {}) + '; /*--&gt;*/</script></html>')
    return HTTPResponse(200, body.encode(), {"content-type": "text/html; charset=utf-8"})


def listing(items=None, total=1, offset=0, keywords="", targeted=False, **changes):
    items = [entry()] if items is None else items
    result = {"status": 200, "hits": len(items), "totalHits": total,
              "data": {"jobs": items, "keywords": keywords},
              "eid": {"searchType": "keyword" if keywords else "allJobs", "query": keywords}}
    if targeted:
        result.update(lpKey="engineering-division", eid={"searchType": "landingPage", "query": "business:engineering"})
    result.update(changes)
    return html({"targetedJobs" if targeted else "eagerLoadRefineSearch": result}, params={"from": str(offset)})


def detail(number=1, **changes):
    job = dict(entry(number), refNum="ACMEUS", reqId=f"REQ-{number}",
               description="<p>Integrate mission systems.</p>", requiredSkillsEducation="<p>Five years experience.</p>",
               preferredSkillsEducation="<p>Field deployment.</p>", payRange="120000 - 160000 USD per year",
               multi_location=[{"location": "Dayton, Ohio"}, {"location": "Remote, US"}], RemoteType="Hybrid",
               postedDate="2026-10-01", jobUpdatedDate="2026-10-08")
    job.update(changes)
    return html({"jobDetail": {"status": 200, "data": {"job": job}}})


class PhenomTests(unittest.TestCase):
    def setUp(self):
        capture = redirect_stderr(StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def fetch(self, responses, url=SOURCE, company="Acme", ats="Phenom"):
        t = Transport(responses)
        return fetch_inventory(ats, url, "C-1", company, discovery_transport=t), t

    def test_full_postings_pagination_and_final_recheck(self):
        result, t = self.fetch([listing(total=2), listing([entry(2)], 2, 1), detail(), detail(2), listing(total=2), listing([entry(2)], 2, 1)])
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 2)
        self.assertEqual(t.urls, [SOURCE + "?s=1", SOURCE + "?s=1&from=1", BASE + "job/1", BASE + "job/2", SOURCE + "?s=1", SOURCE + "?s=1&from=1"])
        job = result.jobs[0]
        self.assertEqual(job["posting_id"], "1")
        self.assertEqual(job["req_id"], "REQ-1")
        self.assertEqual(job["ats"], "Phenom")
        for phrase in ("Integrate mission systems.", "Five years experience.", "Field deployment."):
            self.assertIn(phrase, job["description"])
        self.assertEqual(job["location"], "Dayton, Ohio; Remote, US")
        self.assertIn("USD per year", job["compensation"])
        self.assertEqual(job["work_arrangement"], "Hybrid")

    def test_mode_switch_does_not_shift_first_page(self):
        from urllib.parse import urlsplit, parse_qs
        class ModeTransport:
            def get(self, url):
                if '/job/' in url:
                    return detail(int(url.rsplit('/', 1)[1]))
                q = parse_qs(urlsplit(url).query)
                offset = int(q.get('from', ['0'])[0])
                # The default first page promotes job 2, also on search page 2.
                number = 2 if offset or q.get('s') != ['1'] else 1
                return listing([entry(number)], total=2, offset=offset)
        result = fetch_phenom('Phenom', SOURCE, 'C', 'Acme', ModeTransport())
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual([r['posting_id'] for r in result.jobs], ['1', '2'])

    def test_listing_snapshot_precedes_slow_details(self):
        from urllib.parse import urlsplit, parse_qs
        class MovingTransport:
            def __init__(self): self.details_started = False
            def get(self, url):
                if '/job/' in url:
                    self.details_started = True
                    return detail(int(url.rsplit('/', 1)[1]))
                offset = int(parse_qs(urlsplit(url).query).get('from', ['0'])[0])
                number = (1 if self.details_started else 2) if offset else 1
                return listing([entry(number)], total=2, offset=offset)
        result = fetch_phenom('Phenom', SOURCE, 'C', 'Acme', MovingTransport())
        self.assertEqual(result.status, 'partial', result.reason)
        self.assertIn('repeated', result.reason)
        self.assertEqual([j['posting_id'] for j in result.jobs], ['1', '2'])

    def test_home_routes_to_observed_locale_search(self):
        result, t = self.fetch([html(), listing(), detail(), listing()], BASE)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(result.source_url, SOURCE + "?s=1")
        self.assertEqual(t.urls[1], SOURCE + "?s=1")

    def test_zero_inventory_requires_valid_count_and_recheck(self):
        result, t = self.fetch([listing([], 0), listing([], 0)])
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(t.urls), 2)
        for page in (html(), listing([], 1), listing([], None), listing([], False), listing([], 0, hits=1)):
            result, _ = self.fetch([page, html()])
            self.assertNotEqual(result.status, "complete")

    def test_failure_retains_only_fully_fetched_jobs(self):
        with patch("job_search_helper.phenom.MAX_RECONCILIATIONS", 0):
            result, _ = self.fetch([listing([entry(), entry(2)], 2), detail(), HTTPResponse(503, b"unavailable"), listing([entry(), entry(2)], 2)])
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.jobs), 1)
        self.assertIn("job detail 2", result.reason)

    def test_listing_inconsistency_never_establishes_closure(self):
        bad_pages = [listing([entry()], 2, 1), listing([entry(2)], 3, 1), listing([], 2, 1),
                     listing([entry(2)], 2, 0), listing([entry(2)], 2, 1, keywords="other")]
        for bad in bad_pages:
            result, _ = self.fetch([listing(total=2), bad, detail()])
            self.assertEqual(result.status, "partial", result.reason)
            self.assertEqual(len(result.jobs), 1)

    def test_page_limit_and_changed_final_inventory_are_partial(self):
        with patch("job_search_helper.phenom.MAX_PAGES", 1):
            result, _ = self.fetch([listing(total=2), detail()])
            self.assertEqual(result.status, "partial")
        for final in (listing([entry(2)]), listing([], 0), listing([entry(title="Changed")])):
            with patch("job_search_helper.phenom.MAX_RECONCILIATIONS", 0):
                result, _ = self.fetch([listing(), detail(), final])
            self.assertEqual(result.status, "partial")
            self.assertEqual(len(result.jobs), 1)

    def test_missing_description_or_identity_mismatch_is_partial(self):
        for changes in ({"description": ""}, {"description": None}, {"jobId": "2"}, {"jobSeqNo": "other"},
                        {"title": "Changed"}, {"refNum": "OTHER"}, {"siteType": "internal"},
                        {"jobVisibility": ["internal"]}, {"jobStatus": "Closed"}, {"multi_location": [None]}):
            with patch("job_search_helper.phenom.MAX_RECONCILIATIONS", 0):
                result, _ = self.fetch([listing(), detail(**changes), listing()])
            self.assertEqual(result.status, "partial", changes)
            self.assertEqual(result.jobs, [])

    def test_bad_listings_never_fetch_details(self):
        for items in ([entry(), entry()], [entry(jobId="../apply")], [entry(siteType="internal")],
                      [entry(jobVisibility=["internal"])], [entry(jobSeqNo="OTHER1")], [None]):
            result, t = self.fetch([listing(items, len(items))])
            self.assertEqual(result.status, "partial")
            self.assertEqual(len(t.urls), 1)

    def test_keyword_scope_is_preserved_and_confirmed(self):
        source = SOURCE + "?keywords=field+engineer"
        result, t = self.fetch([listing(total=2, keywords="field engineer"),
                                listing([entry(2)], 2, 1, keywords="field engineer"), detail(), detail(2),
                                listing(total=2, keywords="field engineer"), listing([entry(2)], 2, 1, keywords="field engineer")], source)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertTrue(t.urls[1].endswith("keywords=field+engineer&from=1"))
        self.assertEqual(result.source_url, source)
        self.assertNotEqual(_inventory_source(source), _inventory_source(SOURCE))
        result, _ = self.fetch([listing()], source)
        self.assertEqual(result.status, "partial")

    def test_filtered_page_without_offset_echo_still_reconciles_unique_total(self):
        second = listing([entry(2)], 2, 1, keywords="field")
        second.body = second.body.replace(b'"from": "1"', b'"pageName": "search-results"')
        result, _ = self.fetch([listing(total=2, keywords="field"), second, detail(), detail(2),
                                listing(total=2, keywords="field"), second], SOURCE + "?keywords=field")
        self.assertEqual(result.status, "complete", result.reason)

    def test_custom_landing_scope_is_preserved_during_pagination(self):
        source = "https://careers.example.com/division"
        pages = [listing(total=2, targeted=True), listing([entry(2)], 2, 1, targeted=True), detail(), detail(2),
                 listing(total=2, targeted=True), listing([entry(2)], 2, 1, targeted=True)]
        result, t = self.fetch(pages, source, ats="Phenom shared parent")
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(result.source_url, source)
        self.assertEqual(t.urls[1], source + "?from=1")
        result, t = self.fetch([html()], source)
        self.assertEqual(result.status, "unsupported")
        self.assertEqual(t.urls, [source])

    def test_changed_landing_scope_is_partial(self):
        result, _ = self.fetch([listing(total=2, targeted=True),
                                listing([entry(2)], 2, 1, targeted=True, lpKey="different"), detail()],
                               "https://careers.example.com/division")
        self.assertEqual(result.status, "partial")

    def test_divisions_cannot_receive_unfiltered_parent_inventory(self):
        for host, company in (("careers.rtx.com", "Raytheon"), ("careers.rtx.com", "Collins Aerospace"),
                              ("careers.hpe.com", "HPE Aruba Networking"), ("careers.hpe.com", "Juniper Networks")):
            app = dict(APP, baseUrl=f"https://{host}/us/en/")
            result, t = self.fetch([html(app=app)], app["baseUrl"], company)
            self.assertEqual(result.status, "unsupported")
            self.assertEqual(result.jobs, [])
            self.assertEqual(len(t.urls), 1)

    def test_unsafe_and_unknown_filters_fail_before_network(self):
        for url in ("http://careers.example.com", "https://127.0.0.1/jobs", SOURCE + "?category=engineering",
                    SOURCE + "?from=10", SOURCE + "?keywords=a&keywords=b", SOURCE + "#filters",
                    "https://user:pass@careers.example.com/"):
            result, t = self.fetch([], url)
            self.assertEqual(result.status, "unsupported", url)
            self.assertEqual(t.urls, [])

    def test_redirects_cannot_change_employer_or_discard_scope(self):
        for target in ("https://other.example.com/search-results", "http://careers.example.com/us/en/search-results"):
            result, t = self.fetch([HTTPResponse(302, b"", {"Location": target})])
            self.assertEqual(result.status, "unsupported")
            self.assertEqual(len(t.urls), 1)
        result, t = self.fetch([HTTPResponse(302, b"", {"Location": SOURCE})], SOURCE + "?keywords=field")
        self.assertEqual(result.status, "unsupported")
        self.assertEqual(len(t.urls), 1)

    def test_denials_and_challenges_remain_blocked(self):
        for page in (HTTPResponse(403, b"Denied"), HTTPResponse(200, b"<title>Just a moment</title>")):
            result, _ = self.fetch([page])
            self.assertEqual(result.status, "blocked")

    def test_non_json_bootstrap_is_never_executed(self):
        for body in (b'<script>var phApp = phApp || function(){return {};};</script>',
                     b'<script>var phApp = phApp || {} + alert(1); phApp.ddo = {};</script>'):
            result, _ = self.fetch([HTTPResponse(200, body)])
            self.assertEqual(result.status, "partial")

    def test_generic_browser_fallback_cannot_override_scope_or_identity(self):
        for status in ("unsupported", "blocked", "partial"):
            expected = Inventory(status, reason="Scope/inventory unverified", ats="Phenom")
            with patch("job_search_helper.browser_scraper.fetch_browser_inventory") as browser:
                result = with_browser_fallback(lambda *a: expected)("Phenom", SOURCE, "C-1", "Acme")
                self.assertIs(result, expected)
                browser.assert_not_called()

    def test_known_employer_routes_without_a_phenom_label(self):
        with patch("job_search_helper.phenom.fetch_phenom", return_value=Inventory("partial", ats="Phenom")) as fetch:
            result = fetch_inventory("Browser", "https://careers.mitre.org/us/en", "C-1", "MITRE")
            fetch.assert_called_once()
            self.assertEqual(result.ats, "Phenom")

    def test_sanitized_live_samples(self):
        samples = Path(__file__).parent / "fixtures" / "phenom"
        self.assertTrue(samples.is_dir())
        for path in sorted(samples.glob("*.json")):
            data = json.loads(path.read_text())
            source, app = data["url"], data["app"]
            host = __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(source).hostname
            page = _read(source, Transport([html(data["ddo"], app, data["params"])]), (host, 443))
            entries, total, _ = _listing(page, 0, "")
            self.assertGreater(total, 0)
            if data.get("detail"):
                dp = data["detail"]
                detail_page = _read(dp["url"], Transport([html(dp["ddo"], app)]), (host, 443))
                job = _posting(detail_page, entries[0], _identity(app), "test", path.stem)
                self.assertGreater(len(job["description"]), 500)


if __name__ == "__main__":
    unittest.main()

class WidgetSearchTests(unittest.TestCase):
    def test_widget_requests_are_sorted_and_filters_cannot_leak(self):
        from job_search_helper.phenom_session import PhenomSession
        app = dict(APP, widgetApiEndpoint='https://careers.example.com/widgets')
        result = {'status':200,'hits':1,'totalHits':1,'data':{'jobs':[entry()], 'ui_selections':{}}}
        session = PhenomSession(SOURCE)
        with patch.object(session, '_request', return_value=HTTPResponse(200,json.dumps({'refineSearch':result}).encode())) as request:
            session.search(app, {}, 0)
            payload = request.call_args.args[1]
            self.assertEqual(payload['sort'], {'order':'desc','field':'postedDate'})
            self.assertTrue(payload['jobs'])
            self.assertEqual(payload['selected_fields'], {})
        result['data']['ui_selections'] = {'country':['Other']}
        with patch.object(session, '_request', return_value=HTTPResponse(200,json.dumps({'refineSearch':result}).encode())):
            with self.assertRaises(FetchError):session.search(app, {}, 0)

    def test_widget_full_details_and_final_inventory_check(self):
        class WidgetTransport(Transport):
            def __init__(self):
                super().__init__([listing(), detail()]);self.offsets=[]
            def search(self, app, params, offset):
                self.offsets.append(offset)
                return {'status':200,'hits':1,'totalHits':1,'data':{'jobs':[entry()], 'keywords':''}}
        t=WidgetTransport()
        r=fetch_phenom('Phenom',SOURCE,'c','Acme',t)
        self.assertEqual(r.status,'complete',r.reason)
        self.assertEqual(len(r.jobs),1)
        self.assertEqual(t.offsets,[0,0])

class WidgetPaginationTests(unittest.TestCase):
    def test_all_widget_pages_precede_details_and_final_drift_stays_partial(self):
        class T(Transport):
            def __init__(self, drift):
                super().__init__([listing()] + [detail(i) for i in range(1,52)])
                self.offsets=[];self.drift=drift
            def search(self, app, params, offset):
                self.offsets.append(offset)
                if len(self.offsets)<3:
                    self.assert_no_details = len(self.urls)==1
                items=[entry(i) for i in range(1,51)] if offset==0 else [entry(51)]
                if self.drift and len(self.offsets)==3:items[0]=entry(99)
                return {'status':200,'hits':len(items),'totalHits':51,'data':{'jobs':items}}
        for drift in [False,True]:
            with self.subTest(drift=drift):
                t=T(drift)
                with patch('job_search_helper.phenom.MAX_RECONCILIATIONS', 0):
                    r=fetch_phenom('Phenom',SOURCE,'c','Acme',t)
                self.assertTrue(t.assert_no_details)
                self.assertEqual(t.offsets,[0,50,0,50]);self.assertEqual(len(r.jobs),51)
                self.assertEqual(r.status,'partial' if drift else 'complete',r.reason)

    def test_widget_access_denial_stops_before_details(self):
        class T(Transport):
            def search(self, app, params, offset):raise FetchError('blocked','denied')
        t=T([listing(),detail()]);r=fetch_phenom('Phenom',SOURCE,'c','Acme',t)
        self.assertEqual(r.status,'blocked');self.assertEqual(len(t.urls),1)

    def test_landing_scope_does_not_use_unfiltered_widget(self):
        class T(Transport):
            def search(self,*args):raise AssertionError('Scoped landing expanded')
        t=T([listing(targeted=True),detail(),listing(targeted=True)])
        r=fetch_phenom('Phenom',BASE+'division','c','Acme',t)
        self.assertEqual(r.status,'complete',r.reason)
