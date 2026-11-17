"""Read source and reproduce narrowly scoped issues offline; no runtime writes."""
from pathlib import Path
import hashlib
import json
import sys

ROOT=Path('/home/chris/job-search-helper_old')
OUT=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'src'))
from job_search_helper.caterpillar import _parse_xml
from job_search_helper.company_sources import repair_source
from job_search_helper.ats import is_oracle_host

needles={
 'shared_boards.py':['key=qs[0]','key.get','marker='],
 'ats.py':['def is_oracle_host','fa\\.','fetch_asti(careers_url','fetch_massvirtual(careers_url','fetch_hughes(careers_url','html_transport =','fetch_videoray(careers_url'],
 'asti.py':['len(out)!=2','client=transport'],
 'hughes.py':['total!=14','t=transport'],
 'massvirtual.py':['client=transport'],
 'videoray.py':['discovery_transport = discovery_transport or transport'],
 'black_river.py':['len(first) != 14'],
 'freefly.py':['len(first) != 15'],
 'aitech.py':['len(first)!=17'],
 'jr_automation.py':['total != 64'],
 'kuka.py':['len(rows) != 115'],
 'caterpillar.py':['tags.intersection','return Inventory("complete"','careers_url.rstrip'],
 'browser_scraper.py':['company_id == "COMP-0074"','from .lockheed import'],
 'company_sources.py':["'COMP-0074'",'def repair_source'],
}
result={'code':{},'offline_reproductions':{}}
for name,patterns in needles.items():
 p=ROOT/'src/job_search_helper'/name
 result['code'][str(p.relative_to(ROOT))]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'lines':[{'line':i,'text':line} for i,line in enumerate(p.read_text().splitlines(),1) if any(s in line for s in patterns)]}
xml=b'<jobs><job><id>one</id><title>One</title><url>https://careers.caterpillar.com/en/jobs/r1/one/</url><description>One full description</description></job><job><id>two</id><title>Two</title><url>https://careers.caterpillar.com/en/jobs/r2/two/</url><description>Two full description</description></job></jobs>'
result['offline_reproductions']['caterpillar_two_distinct_records']={'input_records':2,'parsed_records':_parse_xml(xml),'input_xml':xml.decode()}
result['offline_reproductions']['garrett_oracle_host_recognized']=is_oracle_host('ehth.fa.em2.oraclecloud.com')
snapshot=json.loads((OUT/'snapshot.json').read_text())
result['current_source_repair']={}
for row in snapshot['companies']:
 if row['company_id'] in {'COMP-0074','COMP-0238','COMP-0248','COMP-0736'}:
  result['current_source_repair'][row['company_id']]={'input_ats':row['configured_ats'],'input_url':row['configured_url'],'output':repair_source(row['configured_ats'],row['configured_url'],row['company_id'],row['company'])}
(OUT/'code-findings.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result['offline_reproductions'],indent=2))
print(json.dumps(result['current_source_repair'],indent=2))
