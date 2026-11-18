"""Real saved public evidence replay, not network or synthetic detail fixtures."""
import hashlib,json,re,unittest
from pathlib import Path
from job_search_helper.ats import fetch_inventory
from test_samtec_pagination_independent import FixtureTransport,START
from independent_samtec_detail import detail_evidence
BASE=Path('/home/chris/job-search-helper_old/temp/pilot-samtec-20261118/live-recipe-1/result')
REPORT=json.loads((BASE/'live-validation.json').read_text())
DATA={}
for q in REPORT['requests']:
 raw=(BASE/q['body_file']).read_bytes()
 assert hashlib.sha256(raw).hexdigest()==q['body_sha256']
 DATA[q['url']]=raw.decode()
DETAILS=sorted(u for u in DATA if re.fullmatch('/samtec/job/[A-Za-z0-9]+',__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(u).path))
FIRST=DETAILS[0]
class RealDetailTests(unittest.TestCase):
 def run_inventory(self,data):
  t=FixtureTransport(data);r=fetch_inventory('Jobvite',START,'COMP-0739','Samtec',transport=t);return r,t
 def assert_bad(self,body):
  data=dict(DATA);data[FIRST]=body;r,t=self.run_inventory(data)
  self.assertNotEqual(r.status,'complete',r.reason)
  self.assertNotIn(FIRST,{j['url'] for j in r.jobs})
 def test_all_148_actual_details_complete_exact_fields_and_fresh_reread(self):
  r,t=self.run_inventory(dict(DATA));self.assertEqual(r.status,'complete',r.reason);self.assertEqual(len(r.jobs),148)
  self.assertEqual({j['url'] for j in r.jobs},set(DETAILS))
  for j in r.jobs:
   e=detail_evidence(DATA[j['url']],j['url'])
   for field in ['title','description','location','department']:
    with self.subTest(url=j['url'],field=field):self.assertEqual(' '.join(j[field].split()),' '.join(e[field].split()))
   self.assertEqual(j['company_id'],'COMP-0739');self.assertEqual(j['company'],'Samtec');self.assertEqual(t.counts[j['url']],1)
  for url in DATA:
   if url not in DETAILS:self.assertEqual(t.counts[url],2)
 def test_wrong_listing_title_rejected(self):
  s=DATA[FIRST];s=re.sub(r'(<h2 class="jv-header">).*?(</h2>)',r'\1Wrong title\2',s,count=1,flags=re.S);self.assert_bad(s)
 def test_missing_description_rejected(self):self.assert_bad(DATA[FIRST].replace('class="jv-job-detail-description"','class="not-description"'))
 def test_duplicate_description_rejected(self):self.assert_bad(DATA[FIRST]+'<div class="jv-job-detail-description">Duplicate description</div>')
 def test_truncated_description_rejected(self):self.assert_bad(DATA[FIRST].split('<div class="jv-job-detail-bottom-actions">')[0].rsplit('</div>',1)[0])
 def test_wrong_position_employer_rejected(self):self.assert_bad(DATA[FIRST].replace('Position at Samtec, Inc','Position at Other, Inc'))
 def test_missing_position_employer_rejected(self):self.assert_bad(DATA[FIRST].replace('class="jv-meta"','class="other-meta"'))
 def test_cross_employer_application_rejected(self):self.assert_bad(DATA[FIRST].replace('/samtec/job/','/other/job/'))
 def test_wrong_job_application_rejected(self):
  ident=FIRST.rsplit('/',1)[1];self.assert_bad(DATA[FIRST].replace('/'+ident+'/apply','/wrongID/apply'))
 def test_missing_apply_rejected(self):self.assert_bad(DATA[FIRST].replace('jv-button-apply','not-apply'))
 def test_duplicate_title_rejected(self):self.assert_bad(DATA[FIRST]+'<h2 class="jv-header">Another title</h2>')
 def test_missing_location_rejected(self):self.assert_bad(DATA[FIRST].replace('jv-job-detail-meta','not-location'))
 def test_ambiguous_location_separator_rejected(self):self.assert_bad(DATA[FIRST].replace("<span class='jv-inline-separator'></span>","<span class='jv-inline-separator'></span><span class='jv-inline-separator'></span>"))
 def test_wrong_company_binding_rejected(self):
  from job_search_helper import shared_boards as sb
  e=detail_evidence(DATA[FIRST],FIRST);entry={'id':FIRST.rsplit('/',1)[1],'title':e['title'],'url':FIRST}
  for cid,company in [('COMP-0000','Samtec'),('COMP-0739','Other')]:
   with self.subTest(cid=cid,company=company),self.assertRaises(sb.FetchError):
    sb.html_posting(sb.board_link(FIRST),FixtureTransport(DATA),entry,cid,company)
 def test_script_only_description_marker_rejected(self):
  self.assert_bad(DATA[FIRST].replace('class="jv-job-detail-description"','class="missing"')+'<script>"<div class=\"jv-job-detail-description\">fake</div>"</script>')
if __name__=='__main__':unittest.main(verbosity=2)
