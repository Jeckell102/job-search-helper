import unittest
from pathlib import Path
from urllib.parse import urlsplit

from job_search_helper.ats import HTTPResponse
from job_search_helper.successfactors import fetch_successfactors, _leonardo_sitemap


SOURCE = "https://careers.leonardodrs.com/go/All-Jobs/8131200/"
FIXTURE = Path(__file__).parent / "fixtures" / "successfactors" / "leonardo-sitemap-423.xml"


def _urls(count=26):
    return [f"https://careers.leonardodrs.com/job/Test-{i}/{i:04d}/" for i in range(1, count + 1)]


class SitemapBoard:
    def __init__(self, urls, *, sitemap_urls=None, final_sitemap_urls=None, title_drift=False, description_mode="good", final_count=None, final_title_drift=False):
        self.urls = list(urls)
        self.sitemap_urls = list(sitemap_urls if sitemap_urls is not None else urls)
        self.final_sitemap_urls = list(final_sitemap_urls) if final_sitemap_urls is not None else None
        self.title_drift = title_drift
        self.description_mode = description_mode
        self.sitemap_reads = 0
        self.listing_reads = 0
        self.final_count = final_count
        self.final_title_drift = final_title_drift

    def _sitemap(self):
        self.sitemap_reads += 1
        urls = self.final_sitemap_urls if self.sitemap_reads > 1 and self.final_sitemap_urls is not None else self.sitemap_urls
        return ("<urlset>" + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>").encode()

    def get(self, url):
        if url.endswith("/sitemap.xml"):
            return HTTPResponse(200, self._sitemap())
        if "/job/" in url:
            ident = urlsplit(url).path.rstrip("/").split("/")[-1]
            title = "Changed title" if self.title_drift else f"Role {ident}"
            if self.description_mode == "truncated":
                body = f'<link rel="canonical" href="{url}"/><span itemprop="title">{title}</span><div itemprop="description">Complete duties, but the body was cut off.'
            elif self.description_mode == "duplicate":
                body = (f'<link rel="canonical" href="{url}"/><span itemprop="title">{title}</span>'
                        '<div itemprop="description">A</div><div itemprop="description">B</div>')
            else:
                body = (f'<link rel="canonical" href="{url}"/><span itemprop="title">{title}</span>'
                        f'<div itemprop="description">Complete public body for {ident}</div>')
            return HTTPResponse(200, body.encode())
        self.listing_reads += 1
        links = "".join(f'<a class="jobTitle-link" href="{u}">Role {urlsplit(u).path.rstrip("/").split("/")[-1]}</a>'
                         for u in self.urls[:25])
        if self.listing_reads > 1 and self.final_title_drift:
            links = links.replace('Role ', 'Changed ')
        last = min(25, len(self.urls))
        total = self.final_count if self.listing_reads > 1 and self.final_count is not None else len(self.urls)
        return HTTPResponse(200, f"Results <b>1 – {last}</b> of <b>{total}</b>{links}".encode())


class LeonardoSitemapAcceptanceTests(unittest.TestCase):
    def test_actual_423_sitemap_has_complete_unique_identity_set(self):
        body = FIXTURE.read_bytes()
        self.assertEqual(body.count(b"<url>"), 423)
        self.assertEqual(len(set(__import__("re").findall(rb"/job/[^<]+", body))), 423)
        class CapturedSitemap:
            def get(self, url):
                return HTTPResponse(200, body)
        parsed = _leonardo_sitemap(CapturedSitemap(), SOURCE, 423)
        self.assertEqual(len(parsed), 423)
        self.assertEqual(parsed['1428159000'], 'https://careers.leonardodrs.com/job/Bridgeton-Field-Service-Manager-MO-63044/1428159000/')

    def test_order_only_sitemap_change_is_safe(self):
        urls = _urls(26)
        board = SitemapBoard(urls, final_sitemap_urls=list(reversed(urls)))
        result = fetch_successfactors(SOURCE, "COMP-0081", "Leonardo DRS", board)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 26)

    def test_duplicate_identity_or_url_and_count_mismatch_are_partial(self):
        urls = _urls(26)
        cases = {
            "duplicate_id": urls[:-1] + [urls[0].replace('Test-1/', 'Other-slug/')],
            "duplicate_url": urls[:-1] + [urls[0]],
            "count_mismatch": urls[:-1],
        }
        for label, sitemap_urls in cases.items():
            with self.subTest(label=label):
                board = SitemapBoard(urls, sitemap_urls=sitemap_urls)
                self.assertEqual(fetch_successfactors(SOURCE, "COMP-0081", "Leonardo DRS", board).status, "partial")

    def test_first_page_title_or_final_sitemap_membership_change_is_partial(self):
        urls = _urls(26)
        board = SitemapBoard(urls, title_drift=True)
        self.assertEqual(fetch_successfactors(SOURCE, "COMP-0081", "Leonardo DRS", board).status, "partial")
        changed = list(urls); changed[-1] = "https://careers.leonardodrs.com/job/Replacement/9999/"
        board = SitemapBoard(urls, final_sitemap_urls=changed)
        self.assertEqual(fetch_successfactors(SOURCE, "COMP-0081", "Leonardo DRS", board).status, "partial")

    def test_final_published_count_or_title_change_is_partial(self):
        for options in ({'final_count': 27}, {'final_title_drift': True}):
            with self.subTest(options=options):
                result = fetch_successfactors(SOURCE, "COMP-0081", "Leonardo DRS", SitemapBoard(_urls(26), **options))
                self.assertEqual(result.status, 'partial')
                self.assertEqual(len(result.jobs), 26)

    def test_truncated_or_duplicate_description_is_partial(self):
        urls = _urls(26)
        for mode in ("truncated", "duplicate"):
            with self.subTest(mode=mode):
                board = SitemapBoard(urls, description_mode=mode)
                self.assertEqual(fetch_successfactors(SOURCE, "COMP-0081", "Leonardo DRS", board).status, "partial")
