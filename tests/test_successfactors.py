import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from job_search_helper.ats import HTTPResponse
from job_search_helper.successfactors import fetch_successfactors


SOURCE = "https://careers.leonardodrs.com/go/All-Jobs/8131200/"
THALES_SOURCE = "https://careers.thalesdsi.com/search/?q="
ABACO_SOURCE = "https://jobs.ametek.com/go/Abaco/8908500/?q=&sortColumn=referencedate&sortDirection=desc"

def leonardo_sitemap(ids):
    return ("<urlset>" + "".join(
        f"<url><loc>https://careers.leonardodrs.com/job/Test-{i}/{i:04d}/</loc></url>" for i in ids
    ) + "</urlset>").encode()


def listing(start, total=26):
    ids = range(start + 1, min(start + 26, total + 1))
    links = "".join(
        f'<a class="jobTitle-link" href="/job/Test-{ident}/{ident:04d}/">Role {ident}</a>'
        for ident in ids
    )
    return f'Results <b>{start + 1} – {min(start + 25, total)}</b> of <b>{total}</b>{links}'


class LeonardoBoard:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        if url.endswith("/sitemap.xml"):
            return HTTPResponse(200, leonardo_sitemap(range(1, 27)))
        if "/job/" in url:
            ident = int(url.rstrip("/").split("/")[-1])
            return HTTPResponse(200, (f'<link rel="canonical" href="{url}" />'
                                      f'<span itemprop="title">Role {ident}</span><div itemprop="description">Full description {ident}</div>').encode())
        if "/25/?" in url:
            return HTTPResponse(200, listing(25).encode())
        return HTTPResponse(200, listing(0).encode())


class SuccessFactorsTests(unittest.TestCase):
    @staticmethod
    def _range_board(total, page_width, *, malformed=False, repeat=False):
        class Board:
            def __init__(self): self.urls=[]
            def get(self, url):
                self.urls.append(url)
                if "/job/" in url:
                    ident=int(url.rstrip("/").split("/")[-1]); return HTTPResponse(200, f'<span itemprop="title">Role {ident}</span><div itemprop="description">Full description {ident}</div>'.encode())
                start=int(parse_qs(urlsplit(url).query).get("startrow", [0])[0])
                first=start+1; last=min(start+page_width,total)
                if malformed: last=min(total,first+page_width)
                ids=range(first,last+1)
                if repeat and start: ids=range(1,min(page_width,total)+1)
                links="".join(f'<a class="jobTitle-link" href="/job/Test-{i}/{i:04d}/">Role {i}</a>' for i in ids)
                reported_first = first + 1 if malformed else first
                return HTTPResponse(200, f'Results <b>{reported_first} – {last}</b> of <b>{total}</b>{links}'.encode())
        return Board()

    def test_thales_uses_exact_jobs2web_host_and_all_28_published_jobs(self):
        class ThalesBoard:
            def __init__(self): self.urls = []
            def get(self, url):
                self.urls.append(url)
                if "/job/" in url:
                    ident = int(url.rstrip("/").split("/")[-1])
                    return HTTPResponse(200, (f'<link rel="canonical" href="{url}" />'
                                              f'<span itemprop="title">Role {ident}</span><div itemprop="description">Full description {ident}</div>').encode())
                links = "".join(f'<a class="jobTitle-link" href="/job/Test-{i}/{i:04d}/">Role {i}</a>' for i in range(1, 29))
                return HTTPResponse(200, f'Results <b>1 – 28</b> of <b>28</b>{links}'.encode())
        board = ThalesBoard()
        result = fetch_successfactors(THALES_SOURCE, "COMP-0082", "Thales Defense & Security, Inc.", board)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 28)
        self.assertEqual(len({job["posting_id"] for job in result.jobs}), 28)
        self.assertTrue(all("careers.thalesdsi.com" in url for url in board.urls))
        listing_urls = [url for url in board.urls if "/job/" not in url]
        self.assertTrue(listing_urls)
        self.assertTrue(all(parse_qs(urlsplit(url).query, keep_blank_values=True).get("q") == [""] for url in listing_urls))
        self.assertTrue(all(parse_qs(urlsplit(url).query, keep_blank_values=True).get("sortColumn") == ["referencedate"] for url in listing_urls))

    def test_thales_missing_detail_stays_partial(self):
        class Board:
            def get(self, url):
                if "/job/" in url:
                    return HTTPResponse(200, b'<span itemprop="title">Role 1</span>')
                return HTTPResponse(200, b'Results <b>1 - 1</b> of <b>1</b><a class="jobTitle-link" href="/job/Test-1/0001/">Role 1</a>')
        result = fetch_successfactors(THALES_SOURCE, "COMP-0082", "Thales Defense & Security, Inc.", Board())
        self.assertEqual(result.status, "partial")

    def test_thales_published_range_supports_29_jobs_without_static_page_size(self):
        board = self._range_board(29, 29)
        result = fetch_successfactors(THALES_SOURCE, "COMP-0082", "Thales Defense & Security, Inc.", board)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 29)

    def test_thales_published_ranges_advance_50_then_25(self):
        board = self._range_board(75, 50)
        result = fetch_successfactors(THALES_SOURCE, "COMP-0082", "Thales Defense & Security, Inc.", board)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 75)
        self.assertTrue(any("startrow=50" in url for url in board.urls))

    def test_thales_repeated_source_offset_stays_partial(self):
        board = self._range_board(75, 50, repeat=True)
        result = fetch_successfactors(THALES_SOURCE, "COMP-0082", "Thales Defense & Security, Inc.", board)
        self.assertEqual(result.status, "partial")

    def test_thales_repeated_matching_header_and_footer_ranges_are_allowed(self):
        class Board:
            def get(self, url):
                if "/job/" in url:
                    ident=int(url.rstrip("/").split("/")[-1]); return HTTPResponse(200, f'<span itemprop="title">Role {ident}</span><div itemprop="description">Full description {ident}</div>'.encode())
                links=''.join(f'<a class="jobTitle-link" href="/job/Test-{i}/{i:04d}/">Role {i}</a>' for i in range(1,3))
                body=f'Results <b>1 – 2</b> of <b>2</b>{links}'
                return HTTPResponse(200, (body + body).encode())
        result = fetch_successfactors(THALES_SOURCE, "COMP-0082", "Thales Defense & Security, Inc.", Board())
        self.assertEqual(result.status, "complete", result.reason)

    def test_thales_conflicting_header_and_footer_ranges_stay_partial(self):
        class Board:
            def get(self, url):
                links='<a class="jobTitle-link" href="/job/Test-1/0001/">Role 1</a>'
                return HTTPResponse(200, f'Results <b>1 – 1</b> of <b>1</b>{links}Results <b>1 – 2</b> of <b>2</b>{links}'.encode())
        result = fetch_successfactors(THALES_SOURCE, "COMP-0082", "Thales Defense & Security, Inc.", Board())
        self.assertEqual(result.status, "partial")

    def test_thales_nonfirst_page_change_is_caught_by_final_recheck(self):
        class Board:
            def __init__(self): self.page50_calls=0
            def get(self, url):
                if "/job/" in url:
                    ident=int(url.rstrip("/").split("/")[-1]); return HTTPResponse(200, f'<span itemprop="title">Role {ident}</span><div itemprop="description">Full description {ident}</div>'.encode())
                from urllib.parse import parse_qs, urlsplit
                start=int(parse_qs(urlsplit(url).query).get("startrow", [0])[0]); first=start+1; last=min(start+50,75)
                if start==50:
                    self.page50_calls+=1
                    if self.page50_calls>1: first,last=52,76
                links=''.join(f'<a class="jobTitle-link" href="/job/Test-{i}/{i:04d}/">Role {i}</a>' for i in range(first,last+1))
                return HTTPResponse(200, f'Results <b>{first} – {last}</b> of <b>75</b>{links}'.encode())
        result = fetch_successfactors(THALES_SOURCE, "COMP-0082", "Thales Defense & Security, Inc.", Board())
        self.assertEqual(result.status, "partial")

    def test_thales_malformed_published_range_stays_partial(self):
        board = self._range_board(29, 29, malformed=True)
        result = fetch_successfactors(THALES_SOURCE, "COMP-0082", "Thales Defense & Security, Inc.", board)
        self.assertEqual(result.status, "partial")

    def test_thales_duplicate_listing_stays_partial(self):
        class Board:
            def get(self, url):
                links = '<a class="jobTitle-link" href="/job/Test-1/0001/">Role 1</a>' * 2
                return HTTPResponse(200, f'Results <b>1 – 2</b> of <b>2</b>{links}'.encode())
        result = fetch_successfactors(THALES_SOURCE, "COMP-0082", "Thales Defense & Security, Inc.", Board())
        self.assertEqual(result.status, "partial")
    def test_leonardo_uses_published_path_offset_pagination(self):
        board = LeonardoBoard()
        result = fetch_successfactors(SOURCE, "COMP-0081", "Leonardo DRS", board)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 26)
        self.assertIn("https://careers.leonardodrs.com/sitemap.xml", board.urls)
        self.assertEqual(len({job["posting_id"] for job in result.jobs}), 26)

    def test_leonardo_legacy_requisition_detail_preserves_provider_id_and_req_id(self):
        fixture = (Path(__file__).parent / "fixtures" / "successfactors" /
                   "leonardo-conflicting-detail-1428159000.html").read_bytes()

        class Board:
            def get(self, url):
                if "/job/" in url:
                    return HTTPResponse(200, fixture)
                if url.endswith("/sitemap.xml"):
                    return HTTPResponse(200, b'<urlset><url><loc>https://careers.leonardodrs.com/job/Bridgeton-Field-Service-Manager-MO-63044/1428159000/</loc></url></urlset>')
                return HTTPResponse(
                    200,
                    b'Results <b>1 - 1</b> of <b>1</b>'
                    b'<a class="jobTitle-link" href="/job/Bridgeton-Field-Service-Manager-MO-63044/1428159000/">'
                    b'Field Service Manager</a>',
                )

        result = fetch_successfactors(SOURCE, "COMP-0081", "Leonardo DRS", Board())
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(result.jobs[0]["posting_id"], "1428159000")
        self.assertEqual(result.jobs[0]["req_id"], "115435")
        self.assertIn("Job Summary", result.jobs[0]["description"])

    def test_leonardo_later_page_drift_is_caught_by_final_reread(self):
        class Board:
            def __init__(self):
                self.page25_reads = 0

            def get(self, url):
                if url.endswith("/sitemap.xml"):
                    return HTTPResponse(200, leonardo_sitemap(range(1, 31)))
                if "/job/" in url:
                    ident = int(url.rstrip("/").split("/")[-1])
                    body = (f'<span itemprop="title">Role {ident}</span>'
                            f'<div itemprop="description">Complete description {ident}</div>')
                    return HTTPResponse(200, body.encode())
                start = int(urlsplit(url).path.rstrip("/").split("/")[-1]) if "/8131200/" in url and urlsplit(url).path.rstrip("/").split("/")[-1].isdigit() else 0
                if start == 25:
                    self.page25_reads += 1
                    first = 27 if self.page25_reads > 1 else 26
                else:
                    first = 1
                last = min(first + 24, 30)
                links = "".join(
                    f'<a class="jobTitle-link" href="/job/Test-{i}/{i:04d}/">Role {i}</a>'
                    for i in range(first, last + 1)
                )
                return HTTPResponse(200, f"Results <b>{first} – {last}</b> of <b>30</b>{links}".encode())

        result = fetch_successfactors(SOURCE, "COMP-0081", "Leonardo DRS", Board())
        self.assertEqual(result.status, "partial")

    def test_leonardo_late_job_id_marker_and_canonical_are_required(self):
        fixture = (Path(__file__).parent / "fixtures" / "successfactors" /
                   "leonardo-detail-1439528700.html").read_bytes()

        class Board:
            def __init__(self, body): self.body = body

            def get(self, url):
                if "/job/" in url:
                    return HTTPResponse(200, self.body)
                if url.endswith("/sitemap.xml"):
                    return HTTPResponse(200, b'<urlset><url><loc>https://careers.leonardodrs.com/job/Germantown-Senior-Software-Engineer-UI-Focused-Full-Stack-MD-20876/1439528700/</loc></url></urlset>')
                return HTTPResponse(
                    200,
                    b'Results <b>1 - 1</b> of <b>1</b>'
                    b'<a class="jobTitle-link" href="/job/Germantown-Senior-Software-Engineer-UI-Focused-Full-Stack-MD-20876/1439528700/">'
                    b'Senior Software Engineer - UI-Focused Full-Stack</a>',
                )

        result = fetch_successfactors(SOURCE, "COMP-0081", "Leonardo DRS", Board(fixture))
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(result.jobs[0]["req_id"], "115700")
        self.assertIn("What You Bring", result.jobs[0]["description"])

        wrong_canonical = fixture.replace(
            b'https://careers.leonardodrs.com/job/Germantown-Senior-Software-Engineer-UI-Focused-Full-Stack-MD-20876/1439528700/',
            b'https://careers.leonardodrs.com/job/Other/9999999999/',
        )
        self.assertEqual(fetch_successfactors(SOURCE, "COMP-0081", "Leonardo DRS", Board(wrong_canonical)).status, "partial")
        cut = fixture.find(b'itemprop="description"')
        self.assertGreater(cut, 0)
        self.assertEqual(fetch_successfactors(SOURCE, "COMP-0081", "Leonardo DRS", Board(fixture[:cut])).status, "partial")

    def test_leonardo_malformed_or_foreign_sitemap_is_partial(self):
        class Board:
            def __init__(self, sitemap): self.sitemap = sitemap

            def get(self, url):
                if url.endswith("/sitemap.xml"):
                    return HTTPResponse(200, self.sitemap)
                return HTTPResponse(
                    200,
                    b'Results <b>1 - 1</b> of <b>1</b>'
                    b'<a class="jobTitle-link" href="/job/Test-1/0001/">Role 1</a>',
                )

        for sitemap in (b"<urlset>", b"<urlset><url><loc>https://other.example/job/X/0001/</loc></url></urlset>"):
            with self.subTest(sitemap=sitemap):
                self.assertEqual(fetch_successfactors(SOURCE, "COMP-0081", "Leonardo DRS", Board(sitemap)).status, "partial")

    def test_leonardo_captured_board_contract_supports_425_jobs_and_full_body(self):
        class Board:
            def __init__(self): self.urls = []
            def get(self, url):
                self.urls.append(url)
                if url.endswith("/sitemap.xml"):
                    return HTTPResponse(200, leonardo_sitemap(range(1, 424)))
                if "/job/" in url:
                    ident = int(url.rstrip("/").split("/")[-1])
                    body = (f'<span itemprop="title">Role {ident}</span>'
                            f'<div itemprop="description">Responsibilities for Role {ident}. '
                            f'Qualifications: verified full public body for Role {ident}.</div>')
                    body = f'<link rel="canonical" href="{url}" />' + body
                    return HTTPResponse(200, body.encode())
                match = __import__("re").search(r"/8131200/(\d+)/", url)
                start = int(match.group(1)) if match else 0
                total = 423
                first, last = start + 1, min(start + 25, total)
                links = "".join(
                    f'<a class="jobTitle-link" href="/job/Test-{i}/{i:04d}/">Role {i}</a>'
                    for i in range(first, last + 1)
                )
                return HTTPResponse(200, f"Results <b>{first} – {last}</b> of <b>{total}</b>{links}".encode())

        board = Board()
        result = fetch_successfactors(SOURCE, "COMP-0081", "Leonardo DRS", board)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 423)
        self.assertEqual(len({job["posting_id"] for job in result.jobs}), 423)
        self.assertTrue(all("Qualifications: verified full public body" in job["description"] for job in result.jobs))
        self.assertIn("https://careers.leonardodrs.com/sitemap.xml", board.urls)

    def test_abaco_captures_full_published_detail_body_and_business_unit(self):
        board = _AbacoBoard(23)
        result = fetch_successfactors(ABACO_SOURCE, "COMP-0423", "Abaco Systems", board)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 23)
        self.assertTrue(all("Compensation" in job["description"] for job in result.jobs))
        self.assertTrue(all("Benefits" in job["description"] for job in result.jobs))
        self.assertTrue(all("Abaco Business Unit" in job["description"] for job in result.jobs))

    def test_abaco_published_ranges_support_30_jobs_and_offset_page(self):
        board = _AbacoBoard(30)
        result = fetch_successfactors(ABACO_SOURCE, "COMP-0423", "Abaco Systems", board)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 30)
        self.assertTrue(any("/25/" in url or "startrow=25" in url for url in board.urls))

    def test_abaco_missing_or_foreign_business_unit_is_partial(self):
        for mode in ("missing", "foreign"):
            with self.subTest(mode=mode):
                board = _AbacoBoard(1, business_unit=mode)
                result = fetch_successfactors(ABACO_SOURCE, "COMP-0423", "Abaco Systems", board)
                self.assertEqual(result.status, "partial")

    def test_abaco_title_mismatch_and_truncated_listing_are_partial(self):
        board = _AbacoBoard(1, title_mismatch=True)
        self.assertEqual(fetch_successfactors(ABACO_SOURCE, "COMP-0423", "Abaco Systems", board).status, "partial")
        board = _AbacoBoard(30, truncate_second_page=True)
        self.assertEqual(fetch_successfactors(ABACO_SOURCE, "COMP-0423", "Abaco Systems", board).status, "partial")

    def test_abaco_second_page_drift_is_caught_by_final_recheck(self):
        board = _AbacoBoard(30, drift_second_page=True)
        result = fetch_successfactors(ABACO_SOURCE, "COMP-0423", "Abaco Systems", board)
        self.assertEqual(result.status, "partial")

    def test_abaco_rejects_wrong_canonical_even_when_title_matches(self):
        board = _AbacoBoard(1, canonical_mode="wrong")
        result = fetch_successfactors(ABACO_SOURCE, "COMP-0423", "Abaco Systems", board)
        self.assertEqual(result.status, "partial")

    def test_abaco_void_markup_and_script_style_noise_are_handled(self):
        board = _AbacoBoard(1, noisy=True)
        result = fetch_successfactors(ABACO_SOURCE, "COMP-0423", "Abaco Systems", board)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertIn("Compensation", result.jobs[0]["description"])
        self.assertNotIn("script-noise", result.jobs[0]["description"])
        self.assertNotIn("style-noise", result.jobs[0]["description"])

    def test_abaco_unclosed_display_shell_is_partial(self):
        board = _AbacoBoard(1, unclosed=True)
        self.assertEqual(fetch_successfactors(ABACO_SOURCE, "COMP-0423", "Abaco Systems", board).status, "partial")


def _abaco_start(url):
    if "/25/" in url:
        return 25
    return int(parse_qs(urlsplit(url).query).get("startrow", [0])[0])


class _AbacoBoard:
    """Portable Jobs2Web replay matching the captured Abaco markup contract."""
    def __init__(self, total, business_unit="Abaco Business Unit", title_mismatch=False,
                 truncate_second_page=False, drift_second_page=False, canonical_mode="ok",
                 noisy=False, unclosed=False):
        self.total = total
        self.business_unit = business_unit
        self.title_mismatch = title_mismatch
        self.truncate_second_page = truncate_second_page
        self.drift_second_page = drift_second_page
        self.canonical_mode = canonical_mode
        self.noisy = noisy
        self.unclosed = unclosed
        self.urls = []
        self.page_reads = {}

    def get(self, url):
        self.urls.append(url)
        if "/job/" in url:
            ident = int(url.rstrip("/").split("/")[-1])
            title = f"Role {ident}"
            if self.title_mismatch:
                title = "Wrong title"
            unit = "" if self.business_unit == "missing" else self.business_unit
            unit_markup = "" if not unit else f'<span data-careersite-propertyid="businessunit">{unit}</span>'
            canonical = f'https://jobs.ametek.com/job/Test-{ident}/{ident:04d}/'
            if self.canonical_mode == "wrong":
                canonical = 'https://jobs.ametek.com/job/Other/9999999999/'
            noise = '<br><img src="pixel"><meta name="x" content="y"><script>script-noise</script><style>style-noise</style>' if self.noisy else ''
            closing = '' if self.unclosed else '</div>'
            body = (f'<link rel="canonical" href="{canonical}" />'
                    f'<div class="jobDisplayShell"><span itemprop="title">{title}</span>{unit_markup}'
                    f'<div itemprop="description">Core duties for Role {ident}{noise}</div>'
                    f'<section>Compensation: salary range. Benefits: comprehensive.</section>{closing}')
            return HTTPResponse(200, body.encode())
        start = _abaco_start(url)
        first = start + 1
        last = min(start + 25, self.total)
        if self.truncate_second_page and start:
            last = min(last, first + 2)
        if self.drift_second_page and start and self.page_reads.get(start, 0):
            first += 1
        self.page_reads[start] = self.page_reads.get(start, 0) + 1
        links = "".join(f'<a class="jobTitle-link" href="/job/Test-{i}/{i:04d}/">Role {i}</a>'
                        for i in range(first, last + 1))
        return HTTPResponse(200, f'Results <b>{first} – {last}</b> of <b>{self.total}</b>{links}'.encode())
