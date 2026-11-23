from pathlib import Path
import sys
from xml.etree import ElementTree

from job_search_helper.successfactors import CROWN_SOURCE
from job_search_helper.successfactors_sitemap import fetch_from_sitemap

sys.path.insert(0, str(Path(__file__).parent))
from crown_inventory_regression import CrownBoard, HOST, JOBS


def fixture_parse(xml):
    """Simulate a model response; this is not the production parser."""
    return {
        url.text.rstrip('/').rsplit('/', 1)[-1]: url.text
        for url in ElementTree.fromstring(xml).iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
    }


def pull(board, parse=fixture_parse):
    return fetch_from_sitemap(
        CROWN_SOURCE, 'COMP-0588', 'Crown Equipment', board,
        job_prefixes=('/job/', '/TheGoods/job/', '/17West/job/'), parse=parse,
    )


def test_exact_full_result_and_two_sitemap_reads():
    board = CrownBoard()
    result = pull(board)
    assert result.status == 'complete'
    assert {row['url'] for row in result.jobs} == {HOST + path for path in JOBS}
    assert board.calls[HOST + '/sitemap.xml'] == 2


def test_missing_description_keeps_saved_details_partial():
    result = pull(CrownBoard(missing_description=True))
    assert result.status == 'partial'
    assert len(result.jobs) == 2
    assert all(row['description'] for row in result.jobs)


def test_model_map_cannot_widen_host_scope():
    board = CrownBoard()
    result = pull(board, lambda xml: {**fixture_parse(xml), '10004': 'https://foreign.example/job/Role/10004/'})
    assert result.status == 'partial'
    assert not result.jobs
    assert len(board.calls) == 2


def test_model_cannot_omit_a_posting_outside_the_visible_listing():
    def visible_only(xml):
        mapping = fixture_parse(xml)
        del mapping['10003']
        return mapping

    result = pull(CrownBoard(), visible_only)
    assert result.status == 'partial'
    assert not result.jobs


def test_changed_final_membership_never_reports_complete():
    calls = 0

    def change(xml):
        nonlocal calls
        calls += 1
        mapping = fixture_parse(xml)
        if calls == 2:
            mapping.pop('10003')
        return mapping

    result = pull(CrownBoard(), change)
    assert result.status == 'partial'
    assert len(result.jobs) == 3
