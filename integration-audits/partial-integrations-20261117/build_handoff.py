"""Build a complete company register from evidence plus reviewed work orders."""
from collections import Counter
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import hashlib
import json
import re

OUT=Path(__file__).resolve().parent
ROOT=Path('/home/chris/job-search-helper_old')
snapshot=json.loads((OUT/'snapshot.json').read_text())

def clean_url(value):
    value=unescape(value)
    if any(c in value for c in '<>"\x27') or any(ord(c)<33 for c in value): return None
    try:
        p=urlsplit(value)
        if p.scheme!='https' or not p.hostname or p.username or p.password: return None
        pairs=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if k.lower() not in {'_s.crb','token','access_token','authorization','session','sessionid','csrf','csrf_token','_gl'}]
        return urlunsplit((p.scheme,p.netloc,p.path,urlencode(pairs,doseq=True),p.fragment))
    except ValueError: return None

probes=json.loads((OUT/'public-source-probes.json').read_text())
for filename,records in [('public-source-probes.json',probes),('candidate-endpoint-probes.json',json.loads((OUT/'candidate-endpoint-probes.json').read_text()))]:
    for p in records:
        for field in ['ats_candidates','career_links']:
            p[field]=sorted(set(v for raw in p.get(field,[]) if (v:=clean_url(raw))))
    (OUT/filename).write_text(json.dumps(records,indent=2,ensure_ascii=False)+'\n')
byid={alias:p for p in probes for alias in p.get('aliases',[p['key']])}
for key,cid in {'rippling-forterra':'COMP-0066','rippling-droneup':'COMP-0188','hughes-api':'COMP-0118','asti-page':'COMP-0336','massvirtual-feed':'COMP-0344','blackriver-page':'COMP-0166','freefly-page':'COMP-0171','aitech-page':'COMP-0428','jr-page':'COMP-0250','caterpillar-page':'COMP-0238','samtec-page':'COMP-0739','arm-page':'COMP-0724'}.items():
    if key in byid: byid[cid]=byid[key]

DEFAULT={
 'A1':('Strong repair candidate','W01','Repair shared Rippling query-key schema; verify the exact board, all pages, details and final membership.','shared_boards.py'),
 'A2':('Existing adapter repair candidate','W03/W07','Inspect exact dispatcher/source guard and HTML versus API transport; verify actual endpoint before changing the contract.','ats.py'),
 'A3':('Existing provider investigation','W08','Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.','ats.py'),
 'B1':('Access and response investigation','Access investigations','Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.','workday.py'),
 'B2':('Access and response investigation','Access investigations','Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.','discovery.py'),
 'B3':('Network/source investigation','Access investigations','Recheck canonical official URL, TLS/DNS/HTTP status and bounded timeout behavior; confirm native provider after recovery. Do not disable certificate verification or infer an empty board.','discovery.py'),
 'C1':('Employer scope needs proof','Scope investigations','Prove attributable employer/legal-entity/brand and complete board set before implementing or widening a parent/shared source. Verify each regional board and deduplicate stable IDs.','company_sources.py'),
 'C2':('Source discovery still required','Native discovery','Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.','discovery.py'),
 'C3':('Source/redirect investigation','W05 / source repair','Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.','company_sources.py'),
 'D1':('No proven complete public inventory','No public inventory','Seek a newly published official public job inventory; until one exists, preserve explicit unsupported/manual-source status and do not manufacture zero jobs from a contact or interest form.','company_sources.py'),
}
overrides={}
def setnote(ids,disposition,work,next_step,modules=''):
    for number in ids.split():
        cid=number if number.startswith('COMP-') else 'COMP-'+number.zfill(4)
        overrides[cid]=(disposition,work,next_step,modules)

setnote('0118','Strong repair candidate','W02 + W03','Live Hughes API returns 6 rows/totalCount 6 but production guard rejects URL, and module requires 14 jobs/two pages. Fix exact scoped transport and dynamic enumeration/reread together.','hughes.py ats.py')
setnote('0336','Strong repair candidate','W02 + W03','Static official page returns 200; default dispatcher passes API transport rejected by URL guard. Correct HTML client and replace latent exact-two-role contract with verified complete-page evidence.','asti.py ats.py')
setnote('0344','Strong repair candidate','W03','Public Paylocity feed returns 200 with one row; default API guard rejects it. Correct dispatch/transport and verify full row description, employer and repeated full feed.','massvirtual.py paylocity.py ats.py')
setnote('0348','Existing adapter repair candidate','W03','Separate local VideoRay HTML transport from AVAV Workday API client; then prove both inventories and VideoRay attribution and deduplicate overlap. Parent-board access remains unverified.','videoray.py workday.py ats.py')
for n,module in [('0166','black_river'),('0171','freefly'),('0428','aitech'),('0250','jr_automation'),('0246','kuka')]:
 setnote(n,'Strong repair candidate','W02','Replace inspected historical fixed job count with structural/current-total completeness evidence, retain scope/detail checks and stable full reread. Recorded reason below identifies the current mismatch; KUKA count versus scope remains to isolate.',module+'.py')
setnote('0074','Strong routing candidate','W04','Official page links existing Eightfold tenant; current repair_source leaves Browser URL unchanged. Add exact landing alias and verify existing Lockheed adapter through normal dispatch.','lockheed.py browser_scraper.py company_sources.py')
setnote('0238','Correctness repair required before enablement','W07','Repair source mismatch only alongside XML record-iteration, full-description and complete US coverage validation. Offline two-distinct-job XML loses the second record. Investigate current official native source.','caterpillar.py ats.py')
setnote('0449','Strong canonical-source candidate','W05','Verified 301 hire.jobscore.com to careers.jobscore.com same tenant feed. Update exact source/detail host checks, then validate Atom completeness and reread.','ierus.py company_sources.py')
setnote('0506','Canonical-source candidate','W05','Verified Dover migration to jobs.dover.com/scytherobotics?src=app (200). Inspect new listing/detail/empty schema and update narrow old-host/path checks.','scythe_robotics.py company_sources.py')
setnote('0097','Source and parser migration candidate','W05','Verified two 308 redirects to /careers/search/ with state preserved. Re-prove GD Land Systems business-unit scope and new listing contract; redirect alone may not repair Next.js parsing.','gd_land_systems.py')
setnote('0278','Native source unresolved','W05','Official page redirects and embeds Greenhouse machinemetrics, but current native feed returns 404. Do not install this stale embed as a working fix; discover current official board or document no proved inventory.','machinemetrics.py company_sources.py')
setnote('0542','Strong native integration candidate','W06','Official Ashby embed verified; public serverobotics posting feed HTTP 200 with 23 rows. Reuse Ashby normal dispatch and verify full descriptions and inventory reread.','ats.py company_sources.py')
setnote('0749','Strong native integration candidate','W06','Official Greenhouse Ubiquiti links verified; public ubiquiti feed HTTP 200 with 168 rows. Reuse Greenhouse and verify total, full content and reread.','ats.py company_sources.py')
setnote('0710','Native integration candidate','W06','Official Breezy tenant embed verified and /json returns 200 list; reuse Breezy with complete details and final membership validation.','shared_boards.py company_sources.py')
setnote('0789','Native integration candidate','W06','Official page links aerotech.applytojob.com/apply/ (200). Reuse JazzHR, prove complete container/pagination and full details.','shared_boards.py company_sources.py')
setnote('0638','Strong provider-routing candidate','W06','Official Garrett page links Oracle ehth.fa.em2.oraclecloud.com site CX_2001; current is_oracle_host returns false. Add narrowly validated em-region host support across resolver/transport and verify scoped native inventory.','oracle.py ats.py company_sources.py')
setnote('0538 0623 0663 0667','Native integration candidate','W06','Current official page links employer Workday tenant. Add exact source repair using linked board, not login/highlighted search links; verify current response and all-page/detail completeness.','workday.py company_sources.py')
setnote('0660 0731','Native integration candidate','W06','Official careers page links Oracle candidate site. Resolve exact tenant/site and reuse Oracle enumeration/details/reconciliation with intended company scope.','oracle.py company_sources.py')
setnote('0727','Native route mapping candidate','W06','Custom official careers page references Oracle edbz.fa.us2.oraclecloud.com site CX. Prove canonical same-site mapping; then reuse Oracle and full coverage validation.','oracle.py company_sources.py')
setnote('0791','Native integration candidate','W06','Official page embeds Jobvite power-integrations with nl/fr parameters. Prove canonical full board and normalize only verified embed parameters; share Samtec-compatible listing checks.','shared_boards.py company_sources.py')
setnote('0568','Native source discovery candidate','W06','Dayforce privacy link identifies smcnorthamerica/CANDIDATEPORTAL and custom source exposes a search API link; first verify actual complete public board and employer linkage.','shared_extended.py company_sources.py')
setnote('0739','Existing provider parser candidate','W08','Current Jobvite page HTTP 200 has real Samtec detail links while literal jv-job-list gate rejects inventory. Validate new complete container/feed, pagination and explicit empty state.','shared_boards.py')
setnote('0724','Existing provider pagination candidate','W08','TalentBrew reports 452 jobs but stops before page two after 15 retained. Capture next-page/current search contract; repair strict pagination and full reread.','shared_extended.py')
setnote('0248','Filtered scope repair candidate','W08','Current KION URL has unsupported path and multiple Country filters; repair_source leaves it unchanged. Verify intended geography and exact filter semantics; preserve scope rather than dropping filters.','dematic.py workday.py company_sources.py')
setnote('0736','Legacy URL normalization candidate','W08','Separate historical Workday browser metadata from actual filter state; verify current canonical latticesemiconductorscareers board and preserve scope.','workday.py discovery.py company_sources.py')
setnote('0398','Successor/employer scope needs proof','W08','Recorded guard requires verified Gray AES successor searchPositionType=37044. Prove mapping and filtered iCIMS inventory, never import whole Gray family.','icims.py company_sources.py')
setnote('0571','Already implemented; run adoption pending','W09','Current runtime has new scoped Rexroth wrapper; prior same-day receipt complete with 70 US jobs. Final cycle records old broad Bosch fetch. Verify source hashes and new process adoption; do not duplicate implementation.','bosch_rexroth.py ats.py shared_boards.py')
setnote('0003','Access plus inventory-ceiling investigation','Access investigations','Leidos reason includes both Workday 2000-result ceiling and challenge. Reconcile provider limit using verified disjoint public scope partitions if supported; separately classify denied responses. Neither retry nor larger offset alone proves complete.','workday.py')
setnote('0257','Existing detail parser candidate','W08','u-blox listing adapter exists but public detail lacks matching nonempty description. Inspect exact detail identity/body; do not broaden Algolia listing limits or accept summaries as full content.','ublox.py')
setnote('0247','Regional scope/integration gap','Scope investigations','Omron manifest reports official Japan/IAB handoff job.axol.jp without validated adapter. Define intended global/regional coverage and implement missing public region before marking global complete.','omron.py')
setnote('0671','Network/TLS investigation','Access investigations','Recorded TLS/connection failure; test canonical current source and certificate/redirect chain. No confirmed parser defect; keep TLS verification enabled.','discovery.py')
setnote('0529','Source configuration repair candidate','W08','Discovered ATS disagrees with configured ATS. Verify canonical current Vanderlande board, repair exact ATS+URL together and check Bastian overlap/scope.','discovery.py company_sources.py')
setnote('0200 0485','Employer scope needs proof','Scope investigations','Both rows use Symbotic careers. Prove independent Fox Robotics attribution and scope before integrating; never duplicate whole Symbotic inventory under Fox.','company_sources.py')
setnote('0173','Source discovery still required','Native discovery','Automated greenhouse marker is a blog about agricultural greenhouses, not an ATS. Inspect actual official openings; no supported inventory proved by this audit.','discovery.py')
setnote('0700','Source discovery still required','Native discovery','Automated greenhouse marker is a greenhouse-gas reference, not an ATS. Inspect current Timken jobs surface and complete listing contract.','discovery.py')
setnote('0354','No complete public inventory yet proven','No public inventory','Existing source notes describe careers email/LinkedIn, and fresh static probe found no native ATS. Investigate any new official public board; do not infer empty inventory.','xocean.py company_sources.py')
setnote('0560 0570 0573 0588 0594 0604 0620 0658 0740 0742 0765','Provider discovery candidate','W06','Current official source contains SuccessFactors markers/links. Verify exact public listing/tenant, geographic and subsidiary scope, then reuse Jobs2Web or supported SuccessFactors route; asset markers alone are not board evidence.','successfactors.py company_sources.py')
setnote('0554 0564 0621 0622 0779 0780 0781','Provider discovery and scope candidate','W06','Official page has Phenom evidence. Verify full relevant listing and preserve category/region/subsidiary intent; reuse phenom.py only after canonical tenant/filter completeness is proved.','phenom.py company_sources.py')
setnote('0185 0158 0048 0334 0563 0624 0633','Employer scope needs proof','Scope investigations','Official route leads to a broader parent board. Establish exact subsidiary/legal-entity attribution and complete filtered membership; do not relabel parent jobs under this company.','company_sources.py')
setnote('0599 0656','Regional/multiple-board scope needs proof','Scope investigations','Recorded source exposes subset or stale employer links. Map official regional boards, prove intended employer/country set, fetch every board and deduplicate stable IDs.','bamboohr.py company_sources.py')

testfiles=list((ROOT/'tests').glob('test_*.py'))
records=[]
for c in snapshot['companies']:
    choice=overrides.get(c['company_id'],DEFAULT[c['category'][:2]])
    disposition,work,nextstep,mods=choice
    modules=list(dict.fromkeys(['src/job_search_helper/'+m for m in mods.split()]+c['modules']))
    modules=[p for p in modules if (ROOT/p).is_file()]
    tests=sorted(set(c['tests']+[str(p.relative_to(ROOT)) for p in testfiles if any(Path(m).stem in p.stem for m in modules if Path(m).stem not in {'ats','discovery','engine','runner','company_sources'})]))
    p=byid.get(c['company_id'])
    records.append(dict(c,disposition=disposition,work_order=work,next_step=nextstep,candidate_modules=modules,candidate_tests=tests,public_probe=p))

def inline(v): return str(v).replace('|','\\|').replace('\n',' ')
def block(c):
    p=c['public_probe']
    lines=[f"### {c['company_id']} — {c['company']}",f"**Disposition:** {c['disposition']} · **Work order:** {c['work_order']}",f"**Initial group:** {c['category']}",f"**Configured source:** `{c['configured_ats']}` — {c['configured_url'] or '(not set)'}",f"**Cycle source/result ATS:** {c['source_url'] or '(not recorded)'} — `{c['result_ats']}`",f"**Exact recorded reason:** {c['reason']}",f"**Next action:** {c['next_step']}",f"**Candidate code:** {', '.join('`'+x+'`' for x in c['candidate_modules']) or 'Start with `company_sources.py`, `discovery.py`, `ats.py`, and `browser_scraper.py`; no company-specific module found by name/ID scan.'}",f"**Existing test candidates:** {', '.join('`'+x+'`' for x in c['candidate_tests']) or 'Find coverage by adapter/function name; no matching test filename identified.'}"]
    if p:
        lines.append(f"**Fresh public check:** {p['checked_at']}; HTTP {p.get('status','unavailable')}; final URL {p.get('final_url','unknown')}; error {p.get('error','none')}; evidence key `{p['key']}`.")
        links=[v for v in p.get('ats_candidates',[]) if not re.search(r'\.(?:png|jpe?g|webp|svg|woff|css|js)(?:[?#]|$)|/assets/|/images/|/apply_flow/|/login|/Profile|/introduceYourself',v,re.I)]
        if links: lines.append('**Extracted provider-link leads (unverified scope):** '+ ' ; '.join(links[:6]))
        elif p.get('provider_markers'): lines.append('**Provider text/asset leads only:** '+', '.join(p['provider_markers'])+'. These may be false positives; not a verified board.')
        else: lines.append('**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.')
    else: lines.append('**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.')
    lines.append(f"**Checkpoint context:** {c['pending_url_count']} saved pending URLs; discovery incomplete flag `{c['discovery_incomplete']}`; previous cycle stage `{c['previous_stage']}`. Neither pending count nor this flag alone proves coverage.")
    return '\n\n'.join(lines)

categories='| Initial reason group | Companies |\n|---|---:|\n'+'\n'.join(f'| {k} | {v} |' for k,v in sorted(snapshot['categories'].items()))
dispositions=Counter(c['disposition'] for c in records)
categories+='\n\nReviewed dispositions (not guaranteed successful conversions):\n\n| Disposition | Companies |\n|---|---:|\n'+'\n'.join(f'| {k} | {v} |' for k,v in sorted(dispositions.items()))
report=(OUT/'handoff-notes.md').read_text().replace('<!-- CATEGORY_TABLE -->',categories).replace('<!-- COMPANY_REGISTER -->','\n\n'.join(block(c) for c in sorted(records,key=lambda c:c['company_id'])))
(OUT/'PARTIAL_INTEGRATION_HANDOFF.md').write_text(report)
(OUT/'triage.json').write_text(json.dumps({'cycle_id':snapshot['cycle_id'],'dispositions':dict(dispositions),'companies':records},indent=2,ensure_ascii=False)+'\n')

# Copy only a compact prior receipt, without job texts or the unrelated source dump.
prior=OUT.parent/'bosch-rexroth-20261117/evidence/live-validation.json'
if prior.is_file():
    data=json.loads(prior.read_text())
    keys=['status','count','elapsed_seconds','reason','source_url','browser_fallback_allowed','legal_entities','countries']
    summary={k:data[k] for k in keys if k in data}
    summary.update(source_artifact=str(prior),source_sha256=hashlib.sha256(prior.read_bytes()).hexdigest(),note='Earlier same-day validation, not rerun by this audit; current cycle remains partial.')
    (OUT/'bosch-validation-summary.json').write_text(json.dumps(summary,indent=2)+'\n')

ids=[r['company_id'] for r in records]
assert len(ids)==334 and len(set(ids))==334
assert set(re.findall(r'^### (COMP-\d+) —',report,re.M))==set(ids)
assert len(re.findall(r'^### COMP-\d+ —',report,re.M))==334
assert sum(snapshot['stages'].values())==796
assert sum(snapshot['categories'].values())==334
assert sum(dispositions.values())==334
assert '<!-- ' not in report
print(json.dumps({'records':len(ids),'report_bytes':len(report.encode()),'probed_sources':len(probes),'dispositions':dict(dispositions)},indent=2))
