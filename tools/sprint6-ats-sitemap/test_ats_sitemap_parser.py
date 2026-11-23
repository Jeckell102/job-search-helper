"""Focused immutable contract for the new ATS model-authored parser file."""


from job_search_helper import ats_sitemap_parser
from job_search_helper.ats import HTTPResponse, fetch_inventory


ROOT = 'https://jobs.atsautomation.com/'
SOURCE = (
    ROOT + 'search/?createNewAlert=false&q=&locationsearch=&optionsFacetsDD_brand=&optionsFacetsDD_country='
    '&optionsFacetsDD_location=&optionsFacetsDD_lang='
)
IDS = {
    '10001': ROOT + 'job/Test-Engineering/10001/',
    '10002': ROOT + 'PA/job/Test-Process-Role/10002/',
    '10003': ROOT + 'Comecer/job/Test-Technical-Role/10003/',
}


def sitemap(locations):
    return ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + ''.join(f'<url><loc>{url}</loc></url>' for url in locations)
            + '</urlset>')


class Board:
    def __init__(self, *, missing=None):
        self.calls = []
        self.missing = missing

    def get(self, url):
        self.calls.append(url)
        if url == SOURCE:
            jobs = [
                f'<a class="jobTitle-link" href="{location}">Role {identity}</a>'
                for identity, location in list(IDS.items())[:2]
            ]
            return HTTPResponse(200, ''.join(jobs * 3).encode())
        if url == ROOT + 'sitemap.xml':
            return HTTPResponse(200, sitemap([*IDS.values(), ROOT]).encode())
        identity = {value: key for key, value in IDS.items()}[url]
        description = '' if identity == self.missing else (
            f'<div itemprop="description">Full description and duties for role {identity}.</div>'
        )
        return HTTPResponse(200, (
            f'<link rel="canonical" href="{url}"><span itemprop="title">Role {identity}</span>' + description
        ).encode())


def test_candidate_returns_exact_namespaced_group_membership():
    assert ats_sitemap_parser.PARSER_READY is True
    assert ats_sitemap_parser.parse_job_sitemap(sitemap([*IDS.values(), ROOT])) == IDS


def test_candidate_denies_duplicate_and_foreign_job_urls():
    import pytest

    for extra in (IDS['10001'], 'https://foreign.example/job/Test/10004/', ROOT + 'Other/job/Test/10004/'):
        with pytest.raises(ValueError):
            ats_sitemap_parser.parse_job_sitemap(sitemap([*IDS.values(), extra]))


def test_normal_ats_dispatch_uses_host_completion_guard():
    board = Board()
    result = fetch_inventory('SuccessFactors', ROOT, 'COMP-0573', 'ATS Corporation', discovery_transport=board)
    assert result.status == 'complete', result.reason
    assert {job['posting_id']: job['url'] for job in result.jobs} == IDS
    assert board.calls.count(ROOT + 'sitemap.xml') == 2


def test_normal_ats_dispatch_keeps_missing_description_partial():
    board = Board(missing='10003')
    result = fetch_inventory('SuccessFactors', ROOT, 'COMP-0573', 'ATS Corporation', discovery_transport=board)
    assert result.status == 'partial', result.reason
    assert {job['posting_id'] for job in result.jobs} == {'10001', '10002'}
