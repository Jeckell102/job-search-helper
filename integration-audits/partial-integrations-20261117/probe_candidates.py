"""Small follow-up on public endpoints linked by inspected employer pages."""
from concurrent.futures import ThreadPoolExecutor
import json
from probe_sources import OUT, inspect

TARGETS={
 'serve-ashby':'https://api.ashbyhq.com/posting-api/job-board/serverobotics?includeCompensation=true',
 'machinemetrics-greenhouse':'https://boards-api.greenhouse.io/v1/boards/machinemetrics/jobs?content=true',
 'ubiquiti-greenhouse':'https://boards-api.greenhouse.io/v1/boards/ubiquiti/jobs?content=true',
 'righthand-breezy':'https://righthand-robotics.breezy.hr/json',
 'aerotech-jazzhr':'https://aerotech.applytojob.com/apply/',
}
with ThreadPoolExecutor(max_workers=5) as pool:
    results=list(pool.map(lambda kv:inspect(*kv),TARGETS.items()))
(OUT/'candidate-endpoint-probes.json').write_text(json.dumps(results,indent=2,ensure_ascii=False)+'\n')
for r in results: print(r['key'],r.get('status'),r.get('json_shape'),r.get('error'))
