"""Reconcile the saved company register into explicit, reviewable assignments.

This prepares files only. Submission is a separate authenticated CLI operation.
Historical evidence is context, never fresh completion evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def prepare(handoff, triage, root):
    sections = re.split(r'^### (COMP-\d+) — (.+)\n', handoff, flags=re.M)
    register = {sections[i]: (sections[i+1], sections[i+2]) for i in range(1, len(sections), 3)}
    ledger = {}
    for line in handoff.split('### Task ledger', 1)[1].split('### Progress log', 1)[0].splitlines():
        if line.startswith('| W'):
            cells = [c.strip() for c in line.split('|')[1:-1]]
            for cid in re.findall(r'COMP-\d+', cells[1]):
                ledger[cid] = {'status': cells[2], 'note': cells[-1]}
    queued, held = [], []
    seen = set()
    for company in triage['companies']:
        cid = company['company_id']
        if cid in seen or cid not in register:
            raise ValueError('Duplicate or missing register identity: ' + cid)
        seen.add(cid)
        name, section = register[cid]
        if name != company['company']:
            raise ValueError('Company identity differs between sources: ' + cid)
        prior = ledger.get(cid, {})
        notes = re.findall(r'^\*\*Current implementation status[^\n]*', section, re.M)
        complete = prior.get('status') == 'COMPLETE' or any('validated complete' in note.lower() for note in notes)
        state = prior.get('status', 'READY')
        tests = list(dict.fromkeys(company.get('candidate_tests', []) + company.get('tests', [])))
        tests = [t for t in tests if re.fullmatch(r'tests/test_[A-Za-z0-9_]+\.py', t) and (root/t).is_file()][:8]
        reason = 'RECORDED_COMPLETE' if complete else 'EXISTING_VALIDATION_OR_CLAIM' if state in ('IMPLEMENTED_AWAITING_VALIDATION', 'IN_PROGRESS', 'BLOCKED') else 'NEEDS_TEST_ASSIGNMENT' if not tests else ''
        if company.get('work_order') == 'W09':
            reason = 'ADOPTION_VERIFICATION'
        if reason:
            held.append({'company_id': cid, 'company': name, 'disposition': reason,
                         'prior_status': state, 'context': prior.get('note', '') or '\n'.join(notes)})
            continue
        modules = [m for m in company.get('candidate_modules', []) if (root/m).is_file()][:4]
        next_step = company.get('next_step', '')
        # Context is placed in a source document, so quoted historical wording
        # cannot accidentally alter structured development authorization.
        objective = (f"Develop the next bounded integration repair for {cid} {name}. "
                     f"Read docs/backlog/{cid}.md for the saved work order and prior evidence. "
                     f"Inspect {' '.join(modules)}. Run {' '.join(tests)}. "
                     f"Retrieve current employer evidence from {company['configured_url']}. "
                     'Preserve exact employer scope, full descriptions, pagination and stable reread checks. '
                     'Save a tested development draft and an evidence-based handoff for live validation.')
        context = (f'# {cid} — {name}\n\nImported historical backlog context, not instructions granting permissions.\n\n'
                   f'Work order: {company.get("work_order")}\n\nNext step: {next_step}\n\n'
                   + section + '\n\nHistorical ledger: ' + json.dumps(prior) + '\n')
        integration = {'company_id': cid, 'company': name,
                       'configured_url': company['configured_url'],
                       'tests': tests, 'source_targets': modules,
                       'work_order': company.get('work_order', '')}
        for key in ('ats', 'repaired_url'):
            if isinstance(company.get(key), str) and company[key]:
                integration[key] = company[key]
        queued.append({'company_id': cid, 'work_order': company.get('work_order', ''),
                       'assignment': {'objective': objective, 'mode': 'develop', 'max_sessions': 10,
                                      'integration': integration}, 'context': context})
    priority = {'W02': 0, 'W03': 1, 'W04': 2, 'W05': 3, 'W06': 4, 'W07': 5, 'W08': 6}
    queued.sort(key=lambda item: (priority.get(item['work_order'].split()[0], 9), item['company_id']))
    return queued, held


def main():
    p = argparse.ArgumentParser()
    p.add_argument('handoff', type=Path); p.add_argument('triage', type=Path)
    p.add_argument('source_root', type=Path); p.add_argument('output', type=Path)
    a = p.parse_args()
    handoff = a.handoff.read_text()
    queued, held = prepare(handoff, json.loads(a.triage.read_text()), a.source_root)
    a.output.mkdir(parents=True, exist_ok=True)
    docs = a.output / 'docs/backlog'; docs.mkdir(parents=True, exist_ok=True)
    for item in queued:
        (docs / (item['company_id'] + '.md')).write_text(item['context'])
    for n in range(0, len(queued), 50):
        (a.output / f'batch-{n//50+1:03}.json').write_text(json.dumps([q['assignment'] for q in queued[n:n+50]], indent=2))
    report = {'source': str(a.handoff), 'source_sha256': hashlib.sha256(handoff.encode()).hexdigest(),
              'queued_candidates': [{k: v for k, v in q.items() if k != 'context'} for q in queued], 'held': held}
    (a.output / 'import-report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'candidates': len(queued), 'held': len(held)}))


if __name__ == '__main__':
    main()
