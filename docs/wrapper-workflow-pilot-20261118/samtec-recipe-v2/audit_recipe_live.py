"""Read saved evidence only. No network or model requests."""
import collections,hashlib,json,re,sys
from pathlib import Path
from urllib.parse import urlsplit
from reconcile_public import Page, normalized
from independent_samtec_detail import detail_evidence
BASE=Path('/home/chris/job-search-helper_old/temp/pilot-samtec-20261118')
OUT=Path(__file__).parent
version=sys.argv[1] if len(sys.argv)>1 else '2'
run=BASE/('live-recipe-'+version);result=run/'result'
r=json.loads((result/'live-validation.json').read_text())
assert json.loads((run/'exit.json').read_text())['exit_code']==0
assert r['result']=='PASS_LIVE_INTEGRITY_AND_PUBLIC_RECONCILIATION'
assert r['production_transport'] is True and r['transport_injection'] is False and r['sources_unchanged'] and r['stable_ids_urls']
assert r['inputs']==dict(ats='Jobvite',careers_url='https://jobs.jobvite.com/samtec/search',company_id='COMP-0739',company='Samtec')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
qa=json.loads((OUT.parent/('pilot-samtec-recipe-v2-20261118/INDEPENDENT_RECIPE_QA.json' if version=='2' else 'pilot-samtec-recipe-20261118/INDEPENDENT_RECIPE_QA.json')).read_text())
assert r['sources']['src/job_search_helper/shared_boards.py']==qa['candidate_sha256']
repo=BASE/('compiled-candidate-'+version+'/repo')
assert all(sha(repo/f)==h for f,h in r['sources'].items())
public_ids=set();public_pages=[]
for page in r['public_reconciliation']['listing_pages']:
 p=result/page['file'];assert sha(p)==page['sha256'];parser=Page();parser.feed(p.read_text())
 ids={re.fullmatch(r'/samtec/job/([A-Za-z0-9]+)',urlsplit(a.get('href','')).path).group(1) for a,_ in parser.links if re.fullmatch(r'/samtec/job/([A-Za-z0-9]+)',urlsplit(a.get('href','')).path)}
 assert len(ids)==page['jobs'];assert not public_ids.intersection(ids);public_ids.update(ids);public_pages.append(page)
assert len(public_ids)==r['public_reconciliation']['public_total']>0
for request in r['requests']:
 assert request.get('status')==200 and 'error' not in request
 assert sha(result/request['body_file'])==request['body_sha256']
assert len({q['body_file'] for q in r['requests']})==len(r['requests'])
summaries=[]
for record in r['passes']:
 n=record['pass'];assert all(record['checks'].values()) and record['status']=='complete'
 p=result/record['inventory_file'];assert sha(p)==record['inventory_sha256'];jobs=json.loads(p.read_text())['jobs']
 assert {j['posting_id'] for j in jobs}==public_ids
 requests=[q for q in r['requests'] if q['pass']==n];counts=collections.Counter(q['url'] for q in requests)
 for page in public_pages:assert counts[page['url']]==2
 for j in jobs:
  assert counts[j['url']]==1
  q=next(q for q in requests if q['url']==j['url'])
  evidence=detail_evidence((result/q['body_file']).read_text(),j['url'])
  for field in ['title','description','location','department']:
   assert ' '.join(evidence[field].split())==' '.join(j[field].split()), (j['url'],field)
  assert j['company_id']=='COMP-0739' and j['company']=='Samtec'
 summaries.append({'pass':n,'jobs':len(jobs),'requests':len(requests),'listing_pages':len(public_pages),'listing_reads_per_page':2,'fresh_detail_reads':len(jobs),'full_description_matches':len(jobs),'inventory_sha256':sha(p)})
assert len(summaries)==2
invocation=json.loads((run/'invocation.json').read_text());assert invocation['transport_injected'] is False and invocation['production_writes'] is False
report={'result':'PASS_INDEPENDENT_LIVE_QA','independent':True,'candidate_sha256':qa['candidate_sha256'],'live_report_sha256':sha(result/'live-validation.json'),'invocation_sha256':sha(run/'invocation.json'),'source_files_verified':len(r['sources']),'passes':summaries,'unique_public_jobs':len(public_ids),'total_captured_requests':len(r['requests']),'production_transport':'Normal ats.fetch_inventory with no injected transport. Observer delegates unchanged to original shared_boards.Transport.request.','public_reconciliation':'Independent saved public listing IDs and every captured full HTML description, title, location and department checked again offline. No new requests.','scope':'All public Samtec postings before personal filtering. Isolated candidate only, not installed or published.','authorship':'AI selected bounded configuration IDs; trusted host-written Python recipe generated listing and transport code.'}
(OUT/('INDEPENDENT_LIVE_RECIPE_'+version+'_QA.json')).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
