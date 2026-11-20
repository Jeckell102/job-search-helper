from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.redwire import SOURCE, DEFENSE_SOURCE, fetch_redwire, fetch_redwire_space


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


def defense_detail(title, ident):
    import json
    payload = {"@type": "JobPosting", "title": title,
               "description": "A substantive Redwire role description. " * 30,
               "identifier": ident, "datePosted": "2026-10-22"}
    return '<div class="jv-job-list"><a href="/edgeautonomy-careers/job/%s">%s</a></div><script type="application/ld+json">%s</script>' % (
        ident, title, json.dumps(payload))


def both_boards(space_page=None, defense_page=None):
    space_page = space_page or '<a href="/jobs/one">One</a>'
    defense_page = defense_page or defense_detail('One', 'd1')
    return Pages({SOURCE: space_page,
                  SOURCE.replace('/search', '/one'): detail('One', 's1'),
                  DEFENSE_SOURCE: defense_page,
                  DEFENSE_SOURCE.rsplit('/jobs', 1)[0] + '/job/d1': defense_detail('One', 'd1')})


def test_redwire_paginates_details_and_rereads():
    page1 = '<a href="/jobs/one">One</a><a href="/jobs/search?page=2">2</a>'
    page2 = '<a href="/jobs/two">Two</a>'
    pages = Pages({SOURCE: page1, SOURCE + '?page=2': page2,
                   SOURCE.replace('/search', '/one'): detail('One', 'one'),
                   SOURCE.replace('/search', '/two'): detail('Two', 'two'),
                   DEFENSE_SOURCE: defense_detail('Three', 'd1'),
                   DEFENSE_SOURCE.rsplit('/jobs', 1)[0] + '/job/d1': defense_detail('Three', 'd1')})
    result = fetch_redwire(SOURCE, 'COMP-0378', 'Redwire', pages)
    assert result.status == 'complete'
    assert [job['title'] for job in result.jobs] == ['One', 'Two', 'Three']
    assert pages.calls.count(SOURCE) == 2


def test_redwire_routes_through_installed_inventory():
    pages = both_boards()
    result = fetch_inventory('Redwire careers (Space + Defense Tech)', SOURCE, 'COMP-0378', 'Redwire', pages)
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


def test_redwire_unresolved_defense_board_is_partial_not_complete():
    pages = Pages({SOURCE: '<a href="/jobs/one">One</a>',
                   SOURCE.replace('/search', '/one'): detail('One', 'one'),
                   DEFENSE_SOURCE: '<div class="jv-job-list">no board links</div>'})
    result = fetch_redwire(SOURCE, 'COMP-0378', 'Redwire', pages)
    assert result.status == 'partial'
    assert 'Defense Tech=partial' in result.reason or 'Defense Tech=unsupported' in result.reason
