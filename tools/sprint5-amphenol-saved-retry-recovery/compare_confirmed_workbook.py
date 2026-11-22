"""Read only the workbook rows selected by a verified repair publication receipt."""

from collections import Counter, defaultdict

from job_search_helper.publication_receipts import SYNC_CONFIRMED, _canonical, record_fingerprints
from job_search_helper.repository import _equivalent
from job_search_helper.sheet_profile import COMPACT_SCHEMAS


def compare_confirmed_workbook(remote, receipt, application, baselines, *, archived_plan=None):
    """Compare acknowledged fields over a read-only workbook connection.

    The caller supplies the verified local application and receipt join.
    Baselines are keyed by the retained local (tab, row_id). When supplied,
    the archive must be the same plan already verified against the local journal.
    """
    if (receipt['state'] != SYNC_CONFIRMED or not receipt['acknowledgement_id']
            or application['state'] != 'VERIFIED'):
        raise ValueError('A terminal receipt and verified local application are required.')

    by_tab = defaultdict(list)
    labels = set()
    for item in application['row_scope']:
        tab, identity, fields = item['tab'], item['identity'], item['fields']
        columns = set(COMPACT_SCHEMAS.get(tab, ()))
        label = tab + ':' + _canonical(identity)
        if (not identity or not fields or label in labels
                or not (set(identity) | set(fields)) <= columns):
            raise ValueError('Invalid or duplicate compact workbook row scope.')
        baseline = baselines[(tab, item['row_id'])]
        if not set(fields) <= set(baseline):
            raise ValueError('The acknowledged baseline does not include all published fields.')
        labels.add(label)
        by_tab[tab].append((label, identity, fields, baseline))
    if not labels or labels != set(receipt['records']):
        raise ValueError('Workbook row scope differs from the original receipt.')

    if archived_plan is not None:
        from job_search_helper.exact_local_plan import _validate_plan

        _, _, operations = _validate_plan(archived_plan, application['cycle_id'], application['company_id'])
        if (archived_plan.get('record_fingerprint_version', 1) != 1
                or archived_plan['plan_digest'] != application['plan_digest']
                or archived_plan['remote_projection_digest'] != application['remote_projection_digest']
                or record_fingerprints(operations) != receipt['records']):
            raise ValueError('Archived plan differs from the acknowledged application or receipt.')

    counts = Counter()
    verified_fingerprints = 0
    workbook_rows = defaultdict(list)
    baseline_rows = defaultdict(list)
    for tab, scoped in by_tab.items():
        identity_headers = sorted({header for _, identity, _, _ in scoped for header in identity})
        listed = remote.read_columns(tab, identity_headers)
        selected = {}
        for label, identity, fields, baseline in scoped:
            matches = [
                number for number, row in listed
                if all(_equivalent(header, row.get(header, ''), value) for header, value in identity.items())
            ]
            if len(matches) != 1 or matches[0] in selected:
                raise ValueError(f'{tab} workbook identity is missing or ambiguous.')
            selected[matches[0]] = (label, identity, fields, baseline)

        observed = remote.read_rows(tab, selected)
        if set(observed) != set(selected):
            raise ValueError(f'{tab} workbook read did not return the selected rows.')
        for number, (label, identity, fields, baseline) in selected.items():
            row = observed[number]
            expected = {**{field: baseline[field] for field in fields}, **identity}
            if any(header not in row or not _equivalent(header, row[header], value)
                   for header, value in expected.items()):
                raise ValueError(f'{tab} workbook row differs from its acknowledged scope.')
            if archived_plan is not None:
                workbook_rows[tab].append(row)
                baseline_rows[tab].append({**identity, **{field: baseline[field] for field in fields}})
                counts[tab] += 1
                continue
            # Appended note suffixes are not recoverable from row scope alone.
            fingerprints = set()
            for source in (baseline, row):
                comparison = {'tab': tab, 'identity': identity,
                              'values': {field: source[field] for field in fields}}
                fingerprints.add(record_fingerprints([comparison]).get(label))
            if fingerprints == {receipt['records'][label]}:
                verified_fingerprints += 1
            counts[tab] += 1

    if archived_plan is not None:
        if any(record_fingerprints(operations, rows) != receipt['records']
               for rows in (baseline_rows, workbook_rows)):
            raise ValueError('Baseline or workbook fields and appended notes differ from the acknowledged receipt.')
        verified_fingerprints = len(labels)

    return {
        'matched_rows': dict(counts),
        'matched_original_fingerprints': verified_fingerprints,
        'rows_without_original_fingerprint': len(labels) - verified_fingerprints,
    }
