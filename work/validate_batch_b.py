from concurrent.futures import ThreadPoolExecutor, as_completed
from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import REPAIRS

CASES = [
    ('COMP-0076', 'RTX'), ('COMP-0077', 'Collins Aerospace'),
    ('COMP-0078', 'Raytheon'), ('COMP-0079', 'Boeing Defense Space & Security'),
    ('COMP-0095', 'L3Harris Technologies'), ('COMP-0107', 'Silvus Technologies'),
    ('COMP-0130', 'Motorola Solutions'),
]

def run(item):
    cid, company = item
    e = REPAIRS[cid]
    result = fetch_inventory(e['ats'], e['url'], cid, company)
    return cid, company, result.status, len(result.jobs), result.reason[:300]

with ThreadPoolExecutor(max_workers=7) as pool:
    futures = [pool.submit(run, item) for item in CASES]
    for future in as_completed(futures):
        print(future.result(), flush=True)
