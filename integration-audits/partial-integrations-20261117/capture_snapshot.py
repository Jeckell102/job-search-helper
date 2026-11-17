"""Read-only inventory of the final cycle; exports only company/source metadata."""
from pathlib import Path
import collections
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone

ROOT = Path('/home/chris/job-search-helper_old')
OUT = Path(__file__).resolve().parent


def db(name):
    return sqlite3.connect(f'file:{ROOT}/.state/{name}?mode=ro', uri=True, timeout=10)


def classify(item):
    direct = item['reason'].split('Browser fallback returned', 1)[0].lower()
    if 'attributeerror' in direct:
        return 'A1 Shared adapter exception'
    if 'only pinned official' in direct or 'unexpected company or source' in direct:
        return 'A2 Source/transport contract mismatch'
    if 'workday' in direct and ('human verification' in direct or 'access denied' in direct):
        return 'B1 Workday access/response investigation'
    if any(s in direct for s in ('shared/parent','shared jibe','company scope','subset or stale','multiple ats boards')):
        return 'C1 Employer scope or multiple boards'
    if any(s in direct for s in ('no public careers','no public employer','linkedin-only','employment-interest form','no public postings','does not expose a public')):
        return 'D1 No proven public inventory'
    if any(s in direct for s in ('no supported ats','no verified shared board','no verifiable job','expected an html','candidate-site identifier','discovery size limit','redirects to another host')):
        return 'C2 Native source discovery/routing'
    if any(s in direct for s in ('http 404','http 308','http 301','http 302','http 422')):
        return 'C3 Stale URL/redirect/request repair'
    if any(s in direct for s in ('human verification','access denied','denied access','http 403','http 429','http 406')):
        return 'B2 Other access/HTTP response investigation'
    if any(s in direct for s in ('network/timeout','timed out','http 5','timeout failure')):
        return 'B3 Network/service failure'
    return 'A3 Provider parser/pagination/validation'


def main():
    OUT.mkdir(exist_ok=True)
    with db('state.db') as conn:
        cycles = sorted([json.loads(row[0]) for row in conn.execute('select data from cycles')], key=lambda c:c.get('started_at',''))
    cycle = cycles[-1]
    previous = cycles[-2]
    with db('jobs.sqlite3') as conn:
        companies = {d['Company ID']:d for (raw,) in conn.execute("select data from records where tab='Companies'") if (d:=json.loads(raw)).get('Company ID')}
    source = ROOT/'src/job_search_helper'
    source_files = list(source.glob('*.py'))
    tests = list((ROOT/'tests').glob('test_*.py'))
    texts = {p:p.read_text() for p in source_files}
    rows = []
    for cid, item in cycle['companies'].items():
        if item.get('stage') != 'partial':
            continue
        company = companies.get(cid, {})
        name = item['company']
        modules = [str(p.relative_to(ROOT)) for p,t in texts.items() if p.name != 'company_sources.py' and
                   (cid in t or (len(name)>5 and name.casefold() in t.casefold()))]
        module_stems = {Path(p).stem for p in modules} - {'ats','engine','runner'}
        test_files = [str(p.relative_to(ROOT)) for p in tests if any(stem in p.stem for stem in module_stems)]
        prior = previous['companies'].get(cid,{})
        row = dict(company_id=cid, company=name, category=classify(item),
                   configured_url=company.get('Official Careers URL',''), configured_ats=company.get('ATS / Source',''),
                   source_url=item.get('source_url',''), requested_url=item.get('requested_url',''),
                   result_ats=item.get('ats',''), fetched_at=item.get('fetched_at',''), reason=item.get('reason',''),
                   pending_url_count=len(item.get('browser_pending_urls',[])),
                   discovery_incomplete=item.get('browser_discovery_incomplete',False),
                   last_inventory_count=company.get('Last Inventory Count'), modules=modules, tests=test_files,
                   previous_stage=prior.get('stage'), previous_reason=prior.get('reason',''),
                   prior_complete_cycles=[c['id'] for c in cycles[:-1] if c['companies'].get(cid,{}).get('stage')=='complete'][-3:])
        rows.append(row)
    result = dict(captured_at=datetime.now(timezone.utc).isoformat(), runtime=str(ROOT), cycle_id=cycle['id'],
                  cycle_status=cycle['status'], cycle_started_at=cycle.get('started_at'), cycle_completed_at=cycle.get('completed_at'),
                  stages=dict(collections.Counter(x.get('stage') for x in cycle['companies'].values())),
                  previous_cycle_id=previous['id'], categories=dict(collections.Counter(x['category'] for x in rows)),
                  source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}, companies=rows)
    (OUT/'snapshot.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_hashes','companies')},indent=2))
    print('Partial companies complete in previous cycle:',sum(x['previous_stage']=='complete' for x in rows))


if __name__ == '__main__':
    main()
