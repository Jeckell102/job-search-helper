from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.redwire import SOURCE, fetch_redwire


DETAIL = """<script type='application/ld+json'>{json}</script>"""


def detail(title, ident):
    import json
    return DETAIL.format(json=json.dumps({"@type": "JobPosting", "title": title,
        "description": "A substantive Redwire role description. " * 30,
        "identifier": {"value": ident}, "datePosted": "2026-10-22",
        "jobLocation": [{"address": {"addressLocality": "Longmont", "addressRegion": "Colorado", "addressCountry": "US"}}]}))


class Pages:
    def __init__(self, bodies):
        self.bodies = bodies
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return HTTPResponse(200, self.bodies[url].encode(), {"content-type": "text/html"})


def test_redwire_paginates_details_and_rereads():
    page1 = '<a href="/jobs/one">One</a><a href="/jobs/search?page=2">2</a>'
    page2 = '<a href="/jobs/two">Two</a>'
    pages = Pages({SOURCE: page1, SOURCE + '?page=2': page2,
                   SOURCE.replace('/search', '/one'): detail('One', 'one'),
                   SOURCE.replace('/search', '/two'): detail('Two', 'two')})
    result = fetch_redwire(SOURCE, 'COMP-0378', 'Redwire', pages)
    assert result.status == 'complete'
    assert [job['title'] for job in result.jobs] == ['One', 'Two']
    assert pages.calls.count(SOURCE) == 2


def test_redwire_routes_through_installed_inventory():
    pages = Pages({SOURCE: '<a href="/jobs/one">One</a>',
                   SOURCE.replace('/search', '/one'): detail('One', 'one')})
    result = fetch_inventory('Redwire careers (Clinch)', SOURCE, 'COMP-0378', 'Redwire', pages)
    assert result.status == 'complete'


def test_redwire_rejects_scope_and_inventory_drift():
    assert fetch_redwire(SOURCE, 'OTHER', 'Redwire', Pages({})).status == 'unsupported'
    first = '<a href="/jobs/one">One</a>'
    changed = '<a href="/jobs/two">Two</a>'
    class Drift(Pages):
        def get(self, url):
            if url == SOURCE and sum(call == SOURCE for call in self.calls):
                self.bodies[SOURCE] = changed
            return super().get(url)
    pages = Drift({SOURCE: first, SOURCE.replace('/search', '/one'): detail('One', 'one'),
                   SOURCE.replace('/search', '/two'): detail('Two', 'two')})
    result = fetch_redwire(SOURCE, 'COMP-0378', 'Redwire', pages)
    assert result.status == 'partial'
