"""Additional fail-closed HTML evidence cases using normal dispatch fixtures."""
import unittest
import test_samtec_pagination_independent as base
from test_samtec_pagination_independent import pages, listing, START, P1, P2

class SamtecHTMLBoundaryTests(unittest.TestCase):
    run_inventory=base.SamtecPaginationTests.run_inventory
    assert_incomplete=base.SamtecPaginationTests.assert_incomplete
    def test_duplicate_range_elements_are_ambiguous(self):
        data=pages();data[START]+='<div class="jv-pagination-text">1-2 of 5</div>';self.assert_incomplete(data)
    def test_missing_range_close_cannot_consume_following_content(self):
        data=pages();data[START]=data[START].replace('1-2 of 5</div>','1-2 of 5');self.assert_incomplete(data)
    def test_range_class_in_css_is_not_actual_element(self):
        data=pages();data[START]=data[START].replace('<div class="jv-pagination-text">1-2 of 5</div>','<style>.jv-pagination-text {content:"1-2 of 5"}</style>');self.assert_incomplete(data)
    def test_fake_container_in_script_is_not_evidence(self):
        data=pages();data[START]=data[START].replace('class="jv-job-list"','class="featured"')+'<script>const marker = "jv-job-list";</script>';self.assert_incomplete(data)
    def test_next_without_href_is_not_terminal(self):
        data=pages();data[START]=listing(['oA','oB'],1,2,5)+'<a class="jv-pagination-next">Next</a>';self.assert_incomplete(data)
    def test_next_skipping_page_number_is_rejected(self):
        data=pages();data[START]=listing(['oA','oB'],1,2,5,P2)
        _,t=self.assert_incomplete(data);self.assertNotIn(P2,t.calls)
    def test_cross_employer_next_is_rejected_before_fetch(self):
        data=pages();bad='https://jobs.jobvite.com/other/search/?p=1';data[START]=listing(['oA','oB'],1,2,5,bad)
        _,t=self.assert_incomplete(data);self.assertNotIn(bad,t.calls)
    def test_empty_container_without_explicit_zero_is_not_success(self):
        self.assert_incomplete({START:'<h1>Samtec</h1><div class="jv-job-list"></div><div class="jv-pagination-text">0-0 of 0</div>'})
    def test_nonempty_range_contradicts_no_jobs_text(self):
        self.assert_incomplete({START:'<h1>Samtec</h1><div class="jv-job-list">No jobs</div><div class="jv-pagination-text">1-2 of 5</div>'})
    def test_terminal_range_must_start_after_previous_page(self):
        data=pages();data[P2]=listing(['oE'],1,1,5,previous=True);self.assert_incomplete(data)

if __name__=='__main__':unittest.main(verbosity=2)
