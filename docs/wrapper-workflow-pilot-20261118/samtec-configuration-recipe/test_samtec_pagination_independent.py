"""Offline normal-dispatch acceptance tests; use candidate repo's src on PYTHONPATH."""
import collections
import json
import threading
import unittest
from job_search_helper.ats import HTTPResponse, fetch_inventory

ROOT='https://jobs.jobvite.com'
START=ROOT+'/samtec/search'
P1=START+'/?p=1'
P2=START+'/?p=2'
DESCRIPTION='Design, qualify, manufacture and test electrical interconnect products. Work with engineering teams, document requirements and deliver validated solutions for customers. '

def listing(ids,start,end,total,next_url=None,previous=False):
    rows=''.join('<a href="/samtec/job/'+i+'">Engineer '+i+'</a>' for i in ids)
    pager='<div class="jv-pagination-text">%s-%s of %s</div>'%(start,end,total)
    if next_url:pager+='<a class="jv-pagination-next" href="'+next_url+'">Next</a>'
    if previous:pager+='<a class="jv-pagination-prev" href="/samtec/search">Previous</a>'
    return '<html><h1>Samtec Careers</h1><div class="jv-job-list">'+rows+'</div>'+pager+'</html>'

def detail(i):
    data={'@context':'https://schema.org','@type':'JobPosting','identifier':i,'title':'Engineer '+i,'description':DESCRIPTION,'url':ROOT+'/samtec/job/'+i,'hiringOrganization':{'@type':'Organization','name':'Samtec'},'jobLocation':{'@type':'Place','address':{'addressLocality':'New Albany','addressRegion':'Indiana','addressCountry':'US'}}}
    return '<script type="application/ld+json">'+json.dumps(data)+'</script>'

def pages():
    data={START:listing(['oA','oB'],1,2,5,'//jobs.jobvite.com/samtec/search/?p=1'),P1:listing(['oC','oD'],3,4,5,'?p=2',True),P2:listing(['oE'],5,5,5,previous=True)}
    data.update({ROOT+'/samtec/job/'+i:detail(i) for i in ['oA','oB','oC','oD','oE','oF']})
    return data

class FixtureTransport:
    def __init__(self,data):self.data=data;self.calls=[];self.counts=collections.Counter();self.lock=threading.Lock()
    def get(self,url):
        with self.lock:
            self.calls.append(url);self.counts[url]+=1
            value=self.data[url]
            if callable(value):value=value(self.counts[url])
        return value if isinstance(value,HTTPResponse) else HTTPResponse(200,value.encode())
    def post(self,*args):raise AssertionError('Unexpected POST')

class SamtecPaginationTests(unittest.TestCase):
    def run_inventory(self,data):
        t=FixtureTransport(data)
        result=fetch_inventory('Jobvite',START,'COMP-0739','Samtec',transport=t)
        return result,t
    def assert_incomplete(self,data):
        result,t=self.run_inventory(data)
        self.assertNotEqual(result.status,'complete',result.reason)
        return result,t
    def test_three_pages_normal_dispatch_full_details_and_all_page_reread(self):
        result,t=self.run_inventory(pages())
        self.assertEqual(result.status,'complete',result.reason)
        self.assertEqual({j['url'] for j in result.jobs},{ROOT+'/samtec/job/'+i for i in ['oA','oB','oC','oD','oE']})
        for url in [START,P1,P2]:self.assertEqual(t.counts[url],2)
        for job in result.jobs:
            self.assertEqual(job['description'],DESCRIPTION.strip())
            self.assertEqual(t.counts[job['url']],1)
    def test_changed_final_page_is_reconciled_with_new_detail(self):
        data=pages();data[P2]=lambda n:listing(['oE' if n==1 else 'oF'],5,5,5,previous=True)
        result,t=self.run_inventory(data)
        self.assertEqual(result.status,'complete',result.reason)
        self.assertIn(ROOT+'/samtec/job/oF',{j['url'] for j in result.jobs})
        self.assertNotIn(ROOT+'/samtec/job/oE',{j['url'] for j in result.jobs})
        for url in [START,P1,P2]:self.assertGreaterEqual(t.counts[url],3)
        self.assertEqual(t.counts[ROOT+'/samtec/job/oF'],1)
    def test_missing_next_cannot_truncate_inventory(self):
        data=pages();data[START]=listing(['oA','oB'],1,2,5);self.assert_incomplete(data)
    def test_total_mismatch_on_later_page(self):
        data=pages();data[P2]=listing(['oE'],5,5,6);self.assert_incomplete(data)
    def test_next_cycle_rejected_before_repeated_fetch(self):
        data=pages();data[P1]=listing(['oC','oD'],3,4,5,START)
        _,t=self.assert_incomplete(data);self.assertEqual(t.counts[START],1)
    def test_cross_host_next_never_requested(self):
        data=pages();bad='https://evil.test/samtec/search/?p=1';data[START]=listing(['oA','oB'],1,2,5,bad)
        _,t=self.assert_incomplete(data);self.assertNotIn(bad,t.calls)
    def test_filtered_next_never_requested(self):
        data=pages();bad=P1+'&q=engineer';data[START]=listing(['oA','oB'],1,2,5,bad)
        _,t=self.assert_incomplete(data);self.assertNotIn(bad,t.calls)
    def test_conflicting_duplicate_ids_fail_closed(self):
        data=pages();data[P1]=listing(['oA','oD'],3,4,5,'?p=2').replace('Engineer oA','Different role')
        self.assert_incomplete(data)
    def test_duplicate_identical_ids_fail_closed(self):
        data=pages();data[P1]=listing(['oA','oD'],3,4,5,'?p=2');self.assert_incomplete(data)
    def test_invalid_detail_is_not_complete(self):
        data=pages();data[ROOT+'/samtec/job/oE']='<h1>Unavailable</h1>';self.assert_incomplete(data)
    def test_missing_container_on_later_page(self):
        data=pages();data[P1]=data[P1].replace('class="jv-job-list"','class="featured"');self.assert_incomplete(data)
    def test_range_gap_is_not_complete(self):
        data=pages();data[P1]=listing(['oC','oD'],4,5,5,'?p=2');self.assert_incomplete(data)
    def test_range_page_count_mismatch(self):
        data=pages();data[P1]=listing(['oC'],3,4,5,'?p=2');self.assert_incomplete(data)
    def test_missing_range_cannot_use_script_numbers(self):
        data=pages();data[START]=data[START].replace('<div class="jv-pagination-text">1-2 of 5</div>','<script>"1-2 of 5"</script>');self.assert_incomplete(data)
    def test_multiple_next_links_are_ambiguous(self):
        data=pages();data[START]+='<a class="jv-pagination-next" href="'+P2+'">Next</a>';self.assert_incomplete(data)
    def test_terminal_page_advertising_next_is_not_complete(self):
        data=pages();data[P2]=listing(['oE'],5,5,5,'?p=3',True);self.assert_incomplete(data)
    def test_html_shell_is_not_empty_success(self):
        self.assert_incomplete({START:'<h1>Samtec</h1><script>enable javascript</script>'})
    def test_http_failure_is_not_empty_success(self):
        self.assert_incomplete({START:HTTPResponse(503,b'Unavailable')})
    def test_page_limit_fail_closed_before_twenty_first_request(self):
        data={}
        for n in range(21):
            u=START if n==0 else START+'/?p='+str(n)
            data[u]=listing(['oN'+str(n)],n+1,n+1,21,'?p='+str(n+1) if n<20 else None)
            data[ROOT+'/samtec/job/oN'+str(n)]=detail('oN'+str(n))
        _,t=self.assert_incomplete(data)
        self.assertLessEqual(len(t.calls),20)

if __name__=='__main__':unittest.main(verbosity=2)
