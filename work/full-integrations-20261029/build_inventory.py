import csv
import json
import sqlite3
from pathlib import Path

ROOT = Path('/home/chris/job-search-helper_old')
OUT = ROOT / 'work' / 'full-integrations-20261029'
CYCLE_ID = 'CYC-5E605AD44439'

def read_json(value):
    return json.loads(value) if isinstance(value, str) else value

def main():
    state = sqlite3.connect(ROOT / '.state' / 'state.db')
    jobs = sqlite3.connect(ROOT / '.state' / 'jobs.sqlite3')
    inventories = sqlite3.connect(ROOT / '.state' / 'inventories.sqlite3')
    cycle = read_json(state.execute('select data from cycles where id=?', (CYCLE_ID,)).fetchone()[0])
    companies = {}
    for (data,) in jobs.execute("select data from records where tab='Companies' order by row_id"):
        row = read_json(data)
        if row.get('Company ID'):
            companies[row['Company ID']] = row
    inv = {}
    for company_id, payload, blocked in inventories.execute(
        'select company,payload,blocked from inventories where cycle=?', (CYCLE_ID,)
    ):
        record = read_json(payload)
        record['_blocked_flag'] = bool(blocked)
        inv[company_id] = record
    rows = []
    for company_id, scan in cycle['companies'].items():
        if scan.get('stage') == 'complete':
            continue
        configured = companies.get(company_id, {})
        saved = inv.get(company_id, {})
        jobs_list = saved.get('jobs') or []
        rows.append({
            'company_id': company_id,
            'company': scan.get('company') or configured.get('Company', ''),
            'category': configured.get('Category', ''),
            'technology_focus': configured.get('Technology / Focus', ''),
            'priority': configured.get('Priority', ''),
            'company_status': configured.get('Company Status', ''),
            'official_careers_url': configured.get('Official Careers URL', ''),
            'ats_source_configured': configured.get('ATS / Source', ''),
            'website': configured.get('Website', ''),
            'scan_stage': scan.get('stage', ''),
            'inventory_status': scan.get('inventory_status') or saved.get('inventory_status', ''),
            'scan_ats': scan.get('ats') or saved.get('ats', ''),
            'source_url': scan.get('source_url') or saved.get('source_url', ''),
            'requested_url': scan.get('requested_url') or saved.get('requested_url', ''),
            'inventory_count_current_run': len(jobs_list),
            'inventory_count_sheet_last': configured.get('Last Inventory Count', ''),
            'browser_pending_url_count': len(scan.get('browser_pending_urls') or saved.get('browser_pending_urls') or []),
            'browser_discovery_incomplete': bool(scan.get('browser_discovery_incomplete') or saved.get('browser_discovery_incomplete')),
            'reason': scan.get('reason') or saved.get('reason', ''),
            'last_checked': configured.get('Last Checked', ''),
            'last_scan_result': configured.get('Last Scan Result', ''),
            'next_action': configured.get('Next Action', ''),
            'automatic_retry': configured.get('Automatic Retry?', ''),
            'fetched_at': scan.get('fetched_at') or saved.get('fetched_at', ''),
        })
    rows.sort(key=lambda r: r['company_id'])
    OUT.mkdir(parents=True, exist_ok=True)
    metadata = {
        'cycle_id': CYCLE_ID,
        'cycle_started_at': cycle.get('started_at'),
        'cycle_status': cycle.get('status'),
        'definition': 'All companies whose latest cycle stage is not complete; this is the authoritative full-inventory backlog.',
        'counts': {'total_companies': len(cycle['companies']), 'complete': sum(v.get('stage') == 'complete' for v in cycle['companies'].values()), 'incomplete': len(rows)},
        'stage_counts': {},
        'caveat': 'A saved source-repair/REPAIRS entry does not imply a complete inventory. Completeness is determined only by the latest cycle stage and inventory status.',
        'companies': rows,
    }
    for row in rows:
        metadata['stage_counts'][row['scan_stage']] = metadata['stage_counts'].get(row['scan_stage'], 0) + 1
    (OUT / 'inventory.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + '\n')
    fields = list(rows[0])
    with (OUT / 'inventory.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({'count': len(rows), 'stage_counts': metadata['stage_counts'], 'json': str(OUT / 'inventory.json'), 'csv': str(OUT / 'inventory.csv')}))

if __name__ == '__main__':
    main()
