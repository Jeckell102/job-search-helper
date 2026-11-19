"""Explicit field-level, three-way synchronization. Never replace a whole tab.

Network calls occur outside SQLite transactions. Dirty fields remain queued
until acknowledged, and a newer local edit cannot be cleared by an older ack.
Sheets has no conditional cell-write transaction: structural edits during a
publish are unsupported. Use filter views instead of physically sorting rows.
"""
from __future__ import annotations

from collections import defaultdict
import copy
import hashlib
import json
import time
from typing import Mapping

from .repository import RepositoryError, USER_FIELDS, _equivalent, _identity_key
from .sqlite_repository import REVIEW_FIELDS, encode, identity_for, timestamp
from .sheet_profile import COMPACT_PULL_FIELDS, profile_schemas, prune_local_only_delivery

PULL_FIELDS = {
    'Companies': None,
    'Opportunities': None,
    'Job History': ['Job Key', 'Added to Opportunities?', 'Review Status', 'Review Started At',
                    'Decision', 'Fit Level', 'Rejection Reason', 'Review Notes', 'Source Hash',
                    'Last Evaluated', 'Description Hash', 'Reconsideration Count',
                    'Reconsideration Status', 'Material Change Summary'],
}
HUMAN_FIELDS = {
    'Companies': {'Company', 'Category', 'Technology / Focus', 'Website', 'Why It Fits',
                  'Priority', 'Company Status', 'Notes', 'Official Careers URL', 'ATS / Source',
                  'Automatic Retry?', 'Scan State', 'Claimed By', 'Claim Token', 'Claim Expires At'},
    'Opportunities': set(USER_FIELDS) | {'Notes'},
    'Job History': {'Added to Opportunities?', 'Review Notes'},
}
ORDER = {'Job Evidence': 0, 'Job History': 1, 'Opportunities': 2, 'Companies': 3, 'Scan Cycles': 4}


# A posting with no compensation is persisted by the scraper as this exact,
# structured empty envelope.  It is deliberately narrower than "any JSON" or
# "any falsy value": a malformed or unfamiliar source value must remain under
# reconciliation rather than being silently replaced by a spreadsheet value.
_EMPTY_EXTRACTED_SALARY = {
    'compensationTierSummary': None,
    'compensationTiers': [],
    'scrapeableCompensationSalarySummary': None,
    'summaryComponents': [],
}


def _missing_extracted_salary(value):
    """Return True only for a blank field or the known empty scraper envelope."""
    if value is None or not str(value).strip():
        return True
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return False
    return parsed == _EMPTY_EXTRACTED_SALARY


def _plausible_salary_estimate(value):
    """Keep the fallback narrow: a spreadsheet salary must contain a number."""
    return bool(str(value).strip()) and any(character.isdigit() for character in str(value))


def _digest(value):
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


def _required_id(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Exact Sheets {label} is required.')
    return value.strip()


def unique_rows(tab, numbered):
    seen = set()
    for number, row in numbered:
        identity = identity_for(tab, row)
        label = tuple(sorted((h, _identity_key(h, v)) for h, v in identity.items()))
        if label in seen:
            raise RepositoryError(f'{tab}: duplicate remote identity; synchronization is paused for safety.')
        seen.add(label)
    return numbered


class SheetsSynchronizer:
    def __init__(self, local, remote):
        if local.spreadsheet_id != remote.spreadsheet_id:
            raise RepositoryError('Remote and local workbook IDs differ.')
        self.local, self.remote = local, remote
        self.publication = profile_schemas(local.get_meta('sheets_profile'))
        self.pull_fields = COMPACT_PULL_FIELDS if self.publication is not None else PULL_FIELDS
        self.last_pull = 0.0

    def merge_remote(self, tab, numbered, *, complete_snapshot=True):
        """Import changed fields, not stale whole-row snapshots."""
        numbered = unique_rows(tab, list(numbered))
        imported = changed = 0
        seen = set()
        with self.local.transaction():
            # During a local key upgrade, Sheets still names the record by
            # its last published key. Only an unsent change with a durable
            # baseline establishes that alias; row numbers never do.
            prior_keys = defaultdict(list)
            if tab == 'Job History':
                for rid, data in self.local.db.execute(
                        'SELECT b.row_id,b.data FROM baseline b JOIN dirty d '
                        'ON b.tab=d.tab AND b.row_id=d.row_id '
                        'WHERE b.tab=? AND d.header=?', (tab, 'Job Key')):
                    key = json.loads(data).get('Job Key', '')
                    if key:
                        prior_keys[_identity_key('Job Key', key)].append(rid)
            for number, observed in numbered:
                identity = identity_for(tab, observed)
                matches = self.local.matches(tab, identity)
                if tab == 'Job History':
                    ids = {rid for rid, _ in matches}
                    ids.update(prior_keys.get(_identity_key('Job Key', observed['Job Key']), []))
                    matches = [(rid, self.local.row(tab, rid)) for rid in sorted(ids)]
                if not matches and tab == 'Companies' and not observed.get('Company ID'):
                    matches = self.local.matches(tab, {'Company': observed.get('Company', '')})
                if len(matches) > 1:
                    raise RepositoryError(f'{tab}: ambiguous local identity.')
                if not matches:
                    if tab != 'Companies' and set(observed) != set(self.local.schemas[tab]):
                        # A partial row is not enough to create a new authoritative job.
                        raise RepositoryError(f'{tab}: unrecognized remote row {number}; full import/reconciliation required.')
                    rid = self.local.db.execute('SELECT COALESCE(MAX(row_id),0)+1 FROM records WHERE tab=?', (tab,)).fetchone()[0]
                    row = {h: observed.get(h, '') for h in self.local.schemas[tab]}
                    self.local._put(tab, rid, row)
                    self.local._baseline(tab, rid, row)
                    self.local.event('remote_intake', tab, rid, {'identity': identity})
                    imported += 1; seen.add(rid)
                    continue
                rid, current = matches[0]
                if rid in seen:
                    raise RepositoryError(f'{tab}: multiple remote identities resolve to one local record; reconciliation required.')
                seen.add(rid)
                base = self.local.baseline(tab, rid) or {}
                dirty = {h for (h,) in self.local.db.execute('SELECT header FROM dirty WHERE tab=? AND row_id=?', (tab, rid))}
                manual = False
                missing = self.local.db.execute('SELECT 1 FROM conflicts WHERE tab=? AND row_id=? AND header=?', (tab, rid, '__missing__')).fetchone()
                if missing and tab == 'Companies':
                    current['Company Status'] = observed.get('Company Status', 'Active')
                self.local.db.execute('DELETE FROM conflicts WHERE tab=? AND row_id=? AND header=?', (tab, rid, '__missing__'))
                receipt = self.local.db.execute('SELECT data FROM delivery_attempts WHERE tab=? AND row_id=?', (tab, rid)).fetchone()
                attempted = json.loads(receipt[0]) if receipt else {}
                touched = False
                for header, value in observed.items():
                    before = base.get(header, '')
                    local_value = current.get(header, '')
                    if _equivalent(header, value, before):
                        self.local.db.execute('DELETE FROM conflicts WHERE tab=? AND row_id=? AND header=?', (tab, rid, header))
                        continue
                    choice_field = tab == 'Job History' and header == 'Added to Opportunities?'
                    own_echo = header in attempted and _equivalent(header, attempted[header], value)
                    if _equivalent(header, value, local_value) and (not choice_field or own_echo):
                        # Our own acknowledged or ambiguously delivered output; not a manual override.
                        base[header] = value
                        self.local.db.execute('DELETE FROM conflicts WHERE tab=? AND row_id=? AND header=?', (tab, rid, header))
                        self.local.db.execute('DELETE FROM dirty WHERE tab=? AND row_id=? AND header=?', (tab, rid, header))
                        continue
                    if tab == 'Job History' and header == 'Added to Opportunities?':
                        if str(value).strip().casefold() not in {'yes', 'no', 'pending', 'manual review', ''}:
                            self.local.conflict(tab, rid, header, 'Invalid manual choice; use Yes, No, or Pending.')
                            continue
                        manual = True
                    elif tab == 'Job History' and header in REVIEW_FIELDS | {'Last Evaluated', 'Description Hash', 'Reconsideration Count', 'Material Change Summary'}:
                        if observed.get('Source Hash', '') != current.get('Source Hash', ''):
                            self.local.conflict(tab, rid, header, 'Remote review refers to an older source version; not imported.')
                            continue
                        if self.local.db.execute('SELECT 1 FROM manual_choices WHERE tab=? AND row_id=?', (tab, rid)).fetchone():
                            self.local.conflict(tab, rid, header, 'Remote review conflicts with a protected manual choice.')
                            continue
                    elif (tab == 'Opportunities' and header == 'Salary / Range'
                          and header not in dirty
                          and _missing_extracted_salary(local_value)
                          and _plausible_salary_estimate(value)):
                        # User-maintained estimates are a fallback only when
                        # the current posting yielded no salary at all.  A
                        # nonblank or newly-updated extracted value continues
                        # to be locally managed and therefore conflicts.
                        pass
                    elif header not in HUMAN_FIELDS.get(tab, set()):
                        # Source/version and progress fields belong to local processing.
                        self.local.conflict(tab, rid, header, 'Remote edit to a locally managed field needs reconciliation.')
                        continue
                    if header in {'Notes', 'Review Notes'} and header in dirty and not _equivalent(header, local_value, before):
                        previous, local_text, remote_text = str(before or ''), str(local_value or ''), str(value or '')
                        if not local_text.startswith(previous):
                            self.local.conflict(tab, rid, header, 'Both sides replaced notes; reconcile instead of losing either version.')
                            continue
                        suffix = local_text[len(previous):].strip()
                        combined = remote_text + ('\n\n' if remote_text else '') + suffix if suffix and suffix not in remote_text else remote_text
                        current[header] = combined
                        base[header] = value
                        if combined == remote_text:
                            self.local.db.execute('DELETE FROM dirty WHERE tab=? AND row_id=? AND header=?', (tab, rid, header))
                        self.local.db.execute('DELETE FROM conflicts WHERE tab=? AND row_id=? AND header=?', (tab, rid, header))
                        self.local.event('notes_merged', tab, rid, {'field': header})
                        changed += 1; touched = True
                        continue
                    current[header] = value
                    base[header] = value
                    self.local.db.execute('DELETE FROM dirty WHERE tab=? AND row_id=? AND header=?', (tab, rid, header))
                    self.local.db.execute('DELETE FROM conflicts WHERE tab=? AND row_id=? AND header=?', (tab, rid, header))
                    self.local.event('remote_edit', tab, rid, {'field': header, 'before': local_value, 'after': value})
                    changed += 1; touched = True
                if manual:
                    choice = str(observed.get('Added to Opportunities?', '')).strip().casefold()
                    # This row's explicit user choice wins over a simultaneous AI result.
                    self.local.db.execute('DELETE FROM conflicts WHERE tab=? AND row_id=? AND header IN (' + ','.join('?' for _ in REVIEW_FIELDS) + ')', (tab, rid, *sorted(REVIEW_FIELDS)))
                    if choice in {'yes', 'no'}:
                        self.local.db.execute('INSERT INTO manual_choices VALUES (?,?,?,?) ON CONFLICT(tab,row_id) DO UPDATE SET value=excluded.value,at=excluded.at',
                                              (tab, rid, choice.title(), timestamp()))
                        derived = {'Review Status': 'Reviewed', 'Review Started At': '',
                                   'Decision': 'Accept' if choice == 'yes' else 'Reject'}
                    elif choice == 'pending':
                        self.local.db.execute('DELETE FROM manual_choices WHERE tab=? AND row_id=?', (tab, rid))
                        derived = {'Review Status': 'Needs Review', 'Review Started At': '', 'Decision': '', 'Rejection Reason': ''}
                    else:
                        # Blank/Manual Review is not permission to resume an automated decision.
                        derived = {'Review Status': 'Manual Review', 'Review Started At': ''}
                    for header, value in derived.items():
                        if current.get(header, '') != value:
                            current[header] = value
                            self.local.mark_dirty(tab, rid, [header])
                    if choice in {'yes', 'no'} and current.get('Company') and current.get('Official Job URL'):
                        for oid, opportunity in self.local.matches('Opportunities', {
                                'Company': current['Company'], 'Job URL': current['Official Job URL']}):
                            if choice == 'no' and self.local.baseline('Opportunities', oid) is None:
                                self.local.conflict('Opportunities', oid, '__manual_no__',
                                    'Unpublished opportunity held because the user selected No in Job History.')
                            elif choice == 'yes':
                                self.local.db.execute('DELETE FROM conflicts WHERE tab=? AND row_id=? AND header=?',
                                    ('Opportunities', oid, '__manual_no__'))
                                self.local.db.execute('DELETE FROM conflicts WHERE tab=? AND row_id=? AND header=?',
                                    ('Opportunities', oid, '__selection__'))
                    touched = True
                if touched:
                    self.local._put(tab, rid, current)
                self.local._baseline(tab, rid, base)
            # Deleting a sheet row never deletes the underlying record/application history.
            known = {r[0] for r in self.local.db.execute('SELECT row_id FROM baseline WHERE tab=?', (tab,))} if complete_snapshot else set()
            for rid in known - seen:
                self.local.conflict(tab, rid, '__missing__', 'Previously synchronized row is missing remotely; it will not be reinserted automatically.')
                if tab == 'Companies':
                    row = self.local.row(tab, rid); row['Company Status'] = 'Paused'
                    self.local._put(tab, rid, row)
        return {'imported': imported, 'changed_fields': changed}

    def pull(self):
        main = getattr(self.remote, 'main', self.remote)
        if hasattr(main, '_metadata_cache'):
            main._metadata_cache = None
            main._header_cache.clear()
        totals = {}
        for tab, headers in self.pull_fields.items():
            if headers is None:
                # Cell-aware reads preserve rich hyperlink targets, dates, and labels.
                numbered = list(enumerate(self.remote.read(tab), 2))
            else:
                numbered = self.remote.read_columns(tab, headers)
            totals[tab] = self.merge_remote(tab, numbered)
        from .engine import Engine
        engine = Engine(self.local, None)
        # Stable IDs must exist before the first external watermark is seeded.
        # Otherwise an old ID-less row could be mistaken for a new Company on
        # the very next pull after this normal local assignment.
        for row in self.local.read('Companies'):
            if row.get('Company') and not row.get('Company ID'):
                engine._assign_company_id(row)
        # The first full Companies snapshot is only a durable watermark.  On
        # subsequent pulls, changed external Company facts enter the same
        # transactional outbox as supported local mutations.  This remains a
        # one-shot reconciliation during a normal sync, not a resident watcher.
        if hasattr(self.local, 'bootstrap_company_event_reconciliation'):
            baseline = self.local.bootstrap_company_event_reconciliation()
            totals['company_event_baseline'] = baseline
            if not baseline['bootstrapped']:
                totals['company_event_reconciliation'] = self.local.reconcile_external_company_events()
        totals['manual_opportunities'] = engine.sync_manual_opportunities()
        self.last_pull = time.monotonic()
        with self.local.transaction():
            self.local.set_meta('last_pull', timestamp())
        return totals

    def _operations(self, limit=500, max_bytes=2_000_000, *, row_scope=None):
        if row_scope is None:
            prune_local_only_delivery(self.local)
        candidates = self.local.db.execute('''SELECT DISTINCT d.tab,d.row_id FROM dirty d
          WHERE NOT EXISTS (SELECT 1 FROM conflicts c WHERE c.tab=d.tab AND c.row_id=d.row_id)''').fetchall()
        candidates.sort(key=lambda r: (ORDER[r[0]], r[1]))
        plans = []; size = 0
        for tab, rid in candidates:
            if row_scope is not None and (tab, rid) not in row_scope:
                continue
            if self.publication is not None and tab not in self.publication:
                continue
            current = self.local.row(tab, rid)
            base = self.local.baseline(tab, rid)
            if tab == 'Opportunities' and base is None:
                history = self.local.matches('Job History', {'Company': current.get('Company', ''),
                    'Official Job URL': current.get('Job URL', '')})
                if len(history) != 1 or str(history[0][1].get('Added to Opportunities?', '')).casefold() != 'yes':
                    with self.local.transaction():
                        self.local.conflict(tab, rid, '__selection__', 'Unpublished opportunity has no unique current Yes selection.')
                    continue
                history_base = self.local.baseline('Job History', history[0][0])
                if not history_base or str(history_base.get('Added to Opportunities?', '')).casefold() != 'yes':
                    # Publish the corresponding Yes first, then append on the next batch.
                    continue
            fields = {h for (h,) in self.local.db.execute('SELECT header FROM dirty WHERE tab=? AND row_id=?', (tab, rid))}
            if row_scope is not None:
                fields &= set(row_scope[(tab, rid)])
                if not fields:
                    continue
            if self.publication is not None:
                # A scraper already running during activation may still enqueue
                # full-schema delivery flags after the cleanup transaction.
                fields &= set(self.publication[tab])
                if not fields:
                    continue
            if self.publication is None and tab == 'Job History' and current.get('Source Hash'):
                evidence = self.local.matches('Job Evidence', {'Job Key': current['Job Key'], 'Source Hash': current['Source Hash']})
                if any(self.local.db.execute('SELECT 1 FROM dirty WHERE tab=? AND row_id=?', ('Job Evidence', eid)).fetchone() for eid, _ in evidence):
                    continue
            identity = identity_for(tab, base or current)
            if tab == 'Job History' and base and not _equivalent('Job Key', base.get('Job Key', ''), current.get('Job Key', '')):
                # Key migrations use the established company/job URL pair,
                # with the old key guarded in expected below. The repository
                # deliberately forbids changing an operation's own identity.
                stable = ('Company', 'Official Job URL')
                if not all(base.get(h) and _equivalent(h, base[h], current.get(h, '')) for h in stable):
                    with self.local.transaction():
                        self.local.conflict(tab, rid, '__identity__',
                            'Job key and identifying details changed together; reconcile before publication.')
                    continue
                identity = {h: base[h] for h in stable}
            if base and tab == 'Opportunities' and any(
                    not _equivalent(h, current.get(h, ''), value)
                    for h, value in identity.items()):
                # An automated source refresh must not change the attributes
                # that distinguish retained applications, or acknowledge a
                # different sibling after a lost response.
                with self.local.transaction():
                    self.local.conflict(tab, rid, '__identity__',
                        'Opportunity identifying details changed locally; reconcile before publication.')
                continue
            # A not-yet-published generated company ID must match its intake name.
            if tab == 'Companies' and base and not base.get('Company ID'):
                identity = {'Company': base['Company']}
            values = {h: current.get(h, '') for h in fields if h not in identity}
            notes = {}
            if base and tab == 'Opportunities':
                for h in USER_FIELDS:
                    if h in values:
                        with self.local.transaction():
                            self.local.conflict(tab, rid, h, 'Application fields can only be changed by the user in Sheets.')
                        values = None; break
                if values is None:
                    continue
                if 'Notes' in values:
                    before, after = str(base.get('Notes', '') or ''), str(values.pop('Notes') or '')
                    if not after.startswith(before):
                        with self.local.transaction():
                            self.local.conflict(tab, rid, 'Notes', 'Non-append change to personal notes needs reconciliation.')
                        continue
                    suffix = after[len(before):].strip()
                    if suffix:
                        notes['Notes'] = suffix
            expected = {h: base.get(h, '') for h in set(values) | set(notes)} if base else {}
            if base and tab == 'Job History':
                guards = ('Added to Opportunities?', 'Review Status', 'Source Hash') if self.publication is None else ('Added to Opportunities?',)
                expected.update({h: base.get(h, '') for h in guards})
            inserted = current if base is None else {}
            if self.publication is not None:
                inserted = {h: v for h, v in inserted.items() if h in self.publication[tab]}
            op = {'tab': tab, 'identity': identity, 'values': values, 'append_if_missing': base is None,
                  'on_insert': inserted, 'expected': expected, 'append_notes': notes}
            cost = len(encode(op).encode())
            if plans and (len(plans) >= limit or size + cost > max_bytes):
                break
            plans.append((tab, rid, fields, current, op)); size += cost
        return plans

    def _normalize_exact_scope(self, row_scope):
        """Validate explicit stable row identities without discovering work."""
        if not isinstance(row_scope, (list, tuple)) or not row_scope:
            raise ValueError('Exact Sheets row scope must be a nonempty explicit sequence.')
        normalized = []
        seen = set()
        for item in row_scope:
            required = {'tab', 'identity', 'fields', 'append_if_missing'}
            if (not isinstance(item, Mapping) or not required <= set(item)
                    or set(item) - required - {'row_id', 'guards', 'expected'}):
                raise ValueError('Exact Sheets row scope has an invalid shape.')
            tab, row_id = item['tab'], item.get('row_id')
            identity, fields = item['identity'], item['fields']
            append_if_missing = item['append_if_missing']
            guards = item.get('guards', {})
            expected = item.get('expected', {})
            if (tab not in ORDER or (row_id is not None and
                                     (type(row_id) is not int or row_id < 1))
                    or not isinstance(identity, Mapping) or not identity
                    or any(not str(value).strip() for value in identity.values())
                    or not isinstance(fields, (list, tuple)) or not fields
                    or type(append_if_missing) is not bool
                    or any(not isinstance(header, str) or not header for header in fields)
                    or len(fields) != len(set(fields))
                    or not isinstance(guards, Mapping)
                    or set(guards) - set(self.local.schemas.get(tab, ()))
                    or not isinstance(expected, Mapping)):
                raise ValueError('Exact Sheets row scope contains an invalid row.')
            matches = self.local.matches(tab, identity)
            if len(matches) != 1:
                raise ValueError('Exact Sheets stable identity is missing or ambiguous.')
            resolved_row_id = matches[0][0]
            if row_id is not None and row_id != resolved_row_id:
                raise ValueError('Exact Sheets row hint no longer matches its stable identity.')
            row_id = resolved_row_id
            if self.publication is not None:
                if tab not in self.publication or set(fields) - set(self.publication[tab]):
                    raise ValueError('Exact Sheets scope contains a non-publishable field.')
                if set(expected) - set(self.publication[tab]):
                    raise ValueError('Exact Sheets expected guard contains a non-publishable field.')
            elif tab not in self.local.schemas or set(fields) - set(self.local.schemas[tab]):
                raise ValueError('Exact Sheets scope contains an unknown field.')
            elif set(expected) - set(self.local.schemas[tab]):
                raise ValueError('Exact Sheets expected guard contains an unknown field.')
            label = (tab, row_id)
            if label in seen:
                raise ValueError('Exact Sheets row scope repeats a local row.')
            seen.add(label)
            normalized.append({'tab': tab, 'row_id': row_id,
                               'identity': {str(key): copy.deepcopy(value)
                                            for key, value in sorted(identity.items())},
                               'fields': sorted(fields),
                               'append_if_missing': append_if_missing,
                               'guards': {str(key): copy.deepcopy(value)
                                          for key, value in sorted(guards.items())},
                               'expected': {str(key): copy.deepcopy(value)
                                            for key, value in sorted(expected.items())}})
        return sorted(normalized, key=lambda item: (ORDER[item['tab']], item['row_id']))

    def _plan_exact_row(self, item, frozen_operation=None):
        """Derive one operation from only one explicitly named local row."""
        tab, row_id = item['tab'], item['row_id']
        current = self.local.row(tab, row_id)
        if current is None:
            raise ValueError('Exact Sheets scoped local row is missing.')
        matches = self.local.matches(tab, item['identity'])
        if len(matches) != 1 or matches[0][0] != row_id:
            raise ValueError('Exact Sheets stable identity moved or became ambiguous.')
        if self.local.db.execute(
                'SELECT 1 FROM conflicts WHERE tab=? AND row_id=? LIMIT 1',
                (tab, row_id)).fetchone():
            raise ValueError('Exact Sheets scoped row has an unresolved conflict.')
        if any(not _equivalent(header, current.get(header, ''), value)
               for header, value in item['guards'].items()):
            raise ValueError('Exact Sheets local manual or source guard changed.')
        if (tab == 'Job History' and str(current.get('Source Hash', '')).strip()
                and 'Source Hash' not in item['guards']):
            raise ValueError('Exact Sheets Source Hash guard is required.')
        dirty = {header for (header,) in self.local.db.execute(
            'SELECT header FROM dirty WHERE tab=? AND row_id=?', (tab, row_id))}
        fields = set(item['fields'])
        missing_dirty = (fields - set(item['identity'])) - dirty
        # A new row has no baseline yet.  Empty frozen insert cells may not
        # appear in SQLite's dirty table because writing blank over blank is
        # not a cell change; the verified exact local journal is the authority
        # for the whole insert.  Existing rows still require every selected
        # mutable field to remain dirty.
        base = self.local.baseline(tab, row_id)
        if not item['append_if_missing'] and base is not None and missing_dirty:
            raise ValueError(
                'Exact Sheets frozen scope is no longer dirty: '
                + ', '.join(sorted(missing_dirty)))

        # A blank scraper salary must not replace a user estimate.  Removing
        # the field here makes an unsafe frozen projection fail equality.
        if ('Salary / Range' in fields and base
                and _missing_extracted_salary(current.get('Salary / Range'))
                and _plausible_salary_estimate(base.get('Salary / Range'))):
            fields.remove('Salary / Range')
        if not fields:
            raise ValueError('Exact Sheets scoped operation became empty.')

        identity = (copy.deepcopy(frozen_operation['identity'])
                    if frozen_operation is not None else identity_for(tab, base or current))
        if tab == 'Job History' and base and not _equivalent(
                'Job Key', base.get('Job Key', ''), current.get('Job Key', '')):
            stable = ('Company', 'Official Job URL')
            if not all(base.get(header) and _equivalent(
                    header, base[header], current.get(header, '')) for header in stable):
                raise ValueError('Exact Sheets Job History identity changed unsafely.')
            identity = {header: base[header] for header in stable}
        if base and tab == 'Opportunities' and any(
                not _equivalent(header, current.get(header, ''), value)
                for header, value in identity.items()):
            raise ValueError('Exact Sheets Opportunity identity changed locally.')
        if tab == 'Companies' and base and not base.get('Company ID'):
            identity = {'Company': base['Company']}

        value_fields = fields - set(identity)
        if frozen_operation is not None:
            value_fields = set(frozen_operation.get('values', {}))
            value_fields.update(frozen_operation.get('append_notes', {}))
        values = {header: current.get(header, '') for header in value_fields
                  if frozen_operation is not None or header not in identity}
        notes = {}
        if base and tab == 'Opportunities':
            forbidden = set(values) & set(USER_FIELDS)
            if forbidden:
                raise ValueError('Exact Sheets cannot publish user-owned application fields.')
            if 'Notes' in values:
                before, after = str(base.get('Notes', '') or ''), str(values.pop('Notes') or '')
                if not after.startswith(before):
                    raise ValueError('Exact Sheets personal notes are not append-only.')
                suffix = after[len(before):].strip()
                if suffix:
                    notes['Notes'] = suffix
        expected = copy.deepcopy(item['expected'])
        if base and not item['append_if_missing']:
            required_expected = set(values) | set(notes)
            if tab == 'Job History':
                required_expected.add('Added to Opportunities?')
            if not required_expected <= set(expected):
                raise ValueError('Exact Sheets scope omits a required remote expected guard.')
            if any(not _equivalent(header, base.get(header, ''), expected[header])
                   for header in required_expected):
                raise ValueError('Exact Sheets remote expected guard differs from the local baseline.')
        # For a not-yet-baselined insert, frozen expected values are remote
        # no-clobber guards.  They are not asserted as a local baseline; the
        # exact projection seal and the remote commit enforce them if the
        # stable identity unexpectedly already exists.
        if frozen_operation is not None and item['append_if_missing']:
            inserted = {header: current.get(header, '')
                        for header in frozen_operation.get('on_insert', {})}
        else:
            inserted = current if base is None and item['append_if_missing'] else {}
            if self.publication is not None:
                inserted = {header: value for header, value in inserted.items()
                            if header in self.publication[tab]}
        if not values and not notes and not inserted:
            raise ValueError('Exact Sheets scoped operation has no remote mutation.')
        operation = {'tab': tab, 'identity': identity, 'values': values,
                     'append_if_missing': item['append_if_missing'], 'on_insert': inserted,
                     'expected': expected, 'append_notes': notes}
        return {'tab': tab, 'row_id': row_id, 'identity': item['identity'],
                'fields': sorted(fields), 'sent': copy.deepcopy(current),
                'guards': copy.deepcopy(item['guards']),
                'expected': copy.deepcopy(item['expected']), 'operation': operation}

    def plan_exact_scope(self, row_scope, frozen_projection):
        """Plan only explicit rows and require exact frozen-projection equality.

        This method does not call ``pull``, ``once``, ``publish_batch``,
        ``prune_local_only_delivery`` or global dirty-candidate discovery.
        """
        if not isinstance(frozen_projection, list) or not frozen_projection:
            raise ValueError('Exact Sheets frozen projection must be a nonempty operation list.')
        normalized = self._normalize_exact_scope(row_scope)
        if len(normalized) != len(frozen_projection):
            raise ValueError('Exact Sheets scope and frozen projection lengths differ.')
        if any(not isinstance(operation, Mapping)
               or type(operation.get('append_if_missing')) is not bool
               or item['append_if_missing'] != operation['append_if_missing']
               for item, operation in zip(normalized, frozen_projection)):
            raise ValueError('Exact Sheets sealed insert semantics differ from the frozen projection.')
        rows = [self._plan_exact_row(item, operation)
                for item, operation in zip(normalized, frozen_projection)]
        operations = [row['operation'] for row in rows]
        if encode(operations) != encode(frozen_projection):
            raise ValueError('Exact Sheets scoped plan differs from the frozen projection.')
        return {'operations': copy.deepcopy(operations), 'rows': rows,
                'projection_digest': _digest(operations)}

    def _validate_exact_plan(self, exact_plan):
        if (not isinstance(exact_plan, Mapping)
                or set(exact_plan) != {'operations', 'rows', 'projection_digest'}
                or not isinstance(exact_plan.get('operations'), list)
                or not exact_plan['operations']
                or not isinstance(exact_plan.get('rows'), list)
                or len(exact_plan['operations']) != len(exact_plan['rows'])
                or exact_plan.get('projection_digest') != _digest(exact_plan['operations'])):
            raise ValueError('Exact Sheets plan is invalid or unsealed.')
        for row, operation in zip(exact_plan['rows'], exact_plan['operations']):
            if row.get('operation') != operation:
                raise ValueError('Exact Sheets row evidence differs from its operation.')
        return exact_plan

    def _revalidate_exact_rows(self, exact_plan):
        """Prove selected local rows/guards are unchanged immediately prewrite."""
        for evidence in exact_plan['rows']:
            matches = self.local.matches(evidence['tab'], evidence['identity'])
            if len(matches) != 1 or matches[0][0] != evidence['row_id']:
                raise ValueError('Exact Sheets local identity changed before remote write.')
            current = matches[0][1]
            if any(not _equivalent(header, current.get(header, ''), value)
                   for header, value in evidence.get('guards', {}).items()):
                raise ValueError('Exact Sheets local guard changed before remote write.')
            if any(not _equivalent(header, current.get(header, ''),
                                   evidence['sent'].get(header, ''))
                   for header in evidence['fields']):
                raise ValueError('Exact Sheets selected local value changed before remote write.')
            dirty = {header for (header,) in self.local.db.execute(
                'SELECT header FROM dirty WHERE tab=? AND row_id=?',
                (evidence['tab'], evidence['row_id']))}
            baseline = self.local.baseline(evidence['tab'], evidence['row_id'])
            if (baseline is not None
                    and not (set(evidence['fields']) - set(evidence['identity'])) <= dirty):
                raise ValueError('Exact Sheets selected field was acknowledged before remote write.')

    def readback_exact_scope(self, exact_plan, *, receipt_id, intent_id,
                             intent_projection_digest):
        """Read only exact identities/rows and return bound confirmation."""
        exact_plan = self._validate_exact_plan(exact_plan)
        receipt_id = _required_id(receipt_id, 'receipt ID')
        intent_id = _required_id(intent_id, 'intent ID')
        intent_projection_digest = _required_id(
            intent_projection_digest, 'intent projection digest')
        if intent_projection_digest != exact_plan['projection_digest']:
            raise ValueError('Exact Sheets pending intent names another projection.')
        observed = []
        for evidence, operation in zip(exact_plan['rows'], exact_plan['operations']):
            tab = operation['tab']
            identity = dict(operation['identity'])
            for values in (operation.get('on_insert', {}), operation.get('values', {})):
                identity.update({key: value for key, value in values.items() if key in identity})
            numbered = self.remote.read_columns(tab, sorted(identity))
            matches = [number for number, row in numbered if all(
                _equivalent(header, row.get(header, ''), value)
                for header, value in identity.items())]
            if len(matches) != 1:
                raise ValueError('Exact Sheets remote identity is missing or ambiguous.')
            actual = self.remote.read_row(tab, matches[0])
            for values in (operation.get('on_insert', {}), operation.get('values', {})):
                if any(not _equivalent(header, actual.get(header, ''), value)
                       for header, value in values.items()):
                    raise ValueError('Exact Sheets remote readback differs from the frozen projection.')
            for header, suffix in operation.get('append_notes', {}).items():
                if str(suffix) not in str(actual.get(header, '')):
                    raise ValueError('Exact Sheets remote note readback is missing its frozen suffix.')
            observed.append({'tab': tab, 'row_id': evidence['row_id'],
                             'identity': copy.deepcopy(evidence['identity']),
                             'fields': list(evidence['fields']),
                             'sent': copy.deepcopy(evidence['sent']),
                             'actual': {header: actual.get(header, '')
                                        for header in evidence['fields']}})
        acknowledgement_id = _digest({
            'receipt_id': receipt_id, 'intent_id': intent_id,
            'projection_digest': exact_plan['projection_digest'],
            'observed': observed,
        })
        return {'receipt_id': receipt_id, 'intent_id': intent_id,
                'intent_projection_digest': intent_projection_digest,
                'projection_digest': exact_plan['projection_digest'],
                'rows': observed, 'acknowledgement_id': acknowledgement_id}

    @staticmethod
    def _exact_readback_records(exact_plan, readback):
        from .publication_receipts import record_fingerprints
        rows = {}
        for operation, observed in zip(exact_plan['operations'], readback['rows']):
            identity = dict(operation['identity'])
            for values in (operation.get('on_insert', {}), operation.get('values', {})):
                identity.update({key: value for key, value in values.items()
                                 if key in identity})
            row = dict(identity)
            row.update(observed['actual'])
            rows.setdefault(operation['tab'], []).append(row)
        return record_fingerprints(exact_plan['operations'], rows)

    def _require_exact_inbox(self, inbox):
        """Require the concrete durable authority for this exact workbook."""
        from .inbox import InventoryInbox
        if not isinstance(inbox, InventoryInbox):
            raise ValueError('Exact Sheets requires a real durable inventory inbox.')
        with inbox.lock:
            destinations = inbox.connection.execute('SELECT id FROM destination').fetchall()
        if destinations != [(self.local.spreadsheet_id,)]:
            raise ValueError('Exact Sheets inventory inbox belongs to another workbook.')
        return inbox

    def publish_exact_scope(self, exact_plan, *, inbox, cycle_id, company_id,
                            plan_digest, receipt_id, intent_id,
                            remote_projection_digest=None, remote_cursor=0,
                            max_operations=100,
                            max_bytes=500_000):
        """Claim one durable intent, then write once or perform readback only.

        The inbox, not the caller, decides whether this is the one permitted
        remote attempt.  Once claimed, every retry is readback-only, including
        recovery from a timeout after a successful Google request.
        """
        exact_plan = self._validate_exact_plan(exact_plan)
        inbox = self._require_exact_inbox(inbox)
        cycle_id = _required_id(cycle_id, 'cycle ID')
        company_id = _required_id(company_id, 'Company ID')
        plan_digest = _required_id(plan_digest, 'plan digest')
        receipt_id = _required_id(receipt_id, 'receipt ID')
        intent_id = _required_id(intent_id, 'intent ID')
        if remote_projection_digest is None:
            remote_projection_digest = exact_plan['projection_digest']
        remote_projection_digest = _required_id(
            remote_projection_digest, 'remote projection digest')
        if type(remote_cursor) is not int or remote_cursor < 0:
            raise ValueError('Exact Sheets remote cursor is invalid.')
        if (type(max_operations) is not int or not 1 <= max_operations <= 100
                or type(max_bytes) is not int or not 1 <= max_bytes <= 500_000):
            raise ValueError('Exact Sheets remote bounds are invalid.')
        operations = exact_plan['operations']
        size = len(encode(operations).encode('utf-8'))
        if len(operations) > max_operations or size > max_bytes:
            raise ValueError('Exact Sheets frozen projection exceeds the remote bound.')
        # Avoid blocking readback-only recovery on a newer local edit: the
        # acknowledgement path deliberately preserves it.  A never-attempted
        # intent is checked both before and immediately after its atomic claim.
        remote_state = inbox.exact_remote_state(cycle_id, company_id)
        if not isinstance(remote_state, Mapping) or not remote_state.get(
                'first_attempt_claimed'):
            self._revalidate_exact_rows(exact_plan)
        claim = inbox.claim_exact_remote_attempt(
            cycle_id, company_id, local_plan_digest=plan_digest,
            projection_digest=remote_projection_digest,
            receipt_id=receipt_id, intent_id=intent_id, cursor=remote_cursor,
            count=len(operations), chunk_digest=exact_plan['projection_digest'],
            timestamp=timestamp())
        if not isinstance(claim, Mapping) or type(claim.get('first_attempt')) is not bool:
            raise ValueError('Exact Sheets durable intent claim is invalid.')
        result = None
        if claim['first_attempt']:
            self._revalidate_exact_rows(exact_plan)
            result = self.remote.commit(copy.deepcopy(operations))
        readback = self.readback_exact_scope(
            exact_plan, receipt_id=receipt_id, intent_id=intent_id,
            intent_projection_digest=exact_plan['projection_digest'])
        from .inbox import _SHEETS_CONFIRMATION_CAPABILITY
        inbox._confirm_exact_remote_chunk(
            cycle_id, company_id, local_plan_digest=plan_digest,
            projection_digest=remote_projection_digest,
            receipt_id=receipt_id, intent_id=intent_id, cursor=remote_cursor,
            chunk_digest=exact_plan['projection_digest'], timestamp=timestamp(),
            _capability=_SHEETS_CONFIRMATION_CAPABILITY)
        return {'commit': result, 'readback': readback,
                'first_attempt': claim['first_attempt'],
                'acknowledgement_id': readback['acknowledgement_id']}

    def confirm_exact_scope(self, exact_plan, *, inbox, cycle_id, company_id,
                            plan_digest, receipt_id, intent_id):
        """Read back the complete scope and durably confirm it as one operation."""
        exact_plan = self._validate_exact_plan(exact_plan)
        inbox = self._require_exact_inbox(inbox)
        cycle_id = _required_id(cycle_id, 'cycle ID')
        company_id = _required_id(company_id, 'Company ID')
        plan_digest = _required_id(plan_digest, 'plan digest')
        receipt_id = _required_id(receipt_id, 'receipt ID')
        intent_id = _required_id(intent_id, 'intent ID')
        remote_state = inbox.exact_remote_state(cycle_id, company_id)
        if (not isinstance(remote_state, Mapping)
                or remote_state.get('local_plan_digest') != plan_digest
                or remote_state.get('projection_digest') != exact_plan['projection_digest']
                or remote_state.get('receipt_id') != receipt_id
                or remote_state.get('intent_id') != intent_id
                or remote_state.get('remote_cursor') != len(exact_plan['operations'])):
            raise ValueError('Exact Sheets complete remote journal is unavailable.')
        readback = self.readback_exact_scope(
            exact_plan, receipt_id=receipt_id, intent_id=intent_id,
            intent_projection_digest=exact_plan['projection_digest'])
        from .inbox import _SHEETS_CONFIRMATION_CAPABILITY
        inbox._confirm_exact_remote(
            cycle_id, company_id, local_plan_digest=plan_digest,
            projection_digest=exact_plan['projection_digest'],
            receipt_id=receipt_id, intent_id=intent_id,
            cursor=len(exact_plan['operations']),
            observed_records=self._exact_readback_records(exact_plan, readback),
            acknowledgement_id=readback['acknowledgement_id'],
            timestamp=timestamp(),
            _capability=_SHEETS_CONFIRMATION_CAPABILITY)
        return readback

    def acknowledge_exact_scope(self, exact_plan, readback, *, inbox, cycle_id,
                                company_id, plan_digest, receipt_id,
                                intent_id, acknowledgement_id):
        """Acknowledge only confirmed visible fields and preserve later edits."""
        exact_plan = self._validate_exact_plan(exact_plan)
        inbox = self._require_exact_inbox(inbox)
        cycle_id = _required_id(cycle_id, 'cycle ID')
        company_id = _required_id(company_id, 'Company ID')
        plan_digest = _required_id(plan_digest, 'plan digest')
        receipt_id = _required_id(receipt_id, 'receipt ID')
        intent_id = _required_id(intent_id, 'intent ID')
        acknowledgement_id = _required_id(acknowledgement_id, 'acknowledgement ID')
        expected_acknowledgement = _digest({
            'receipt_id': receipt_id,
            'intent_id': readback.get('intent_id') if isinstance(readback, Mapping) else None,
            'projection_digest': exact_plan['projection_digest'],
            'observed': readback.get('rows') if isinstance(readback, Mapping) else None,
        })
        if (not isinstance(readback, Mapping)
                or readback.get('receipt_id') != receipt_id
                or readback.get('intent_id') != intent_id
                or readback.get('intent_projection_digest') != exact_plan['projection_digest']
                or readback.get('projection_digest') != exact_plan['projection_digest']
                or readback.get('acknowledgement_id') != expected_acknowledgement
                or acknowledgement_id != expected_acknowledgement
                or not isinstance(readback.get('rows'), list)
                or len(readback['rows']) != len(exact_plan['rows'])):
            raise ValueError('Exact Sheets acknowledgement binding is unavailable or invalid.')
        inbox.require_exact_remote_confirmed(
            cycle_id, company_id, local_plan_digest=plan_digest,
            projection_digest=exact_plan['projection_digest'],
            receipt_id=receipt_id, intent_id=intent_id,
            acknowledgement_id=acknowledgement_id)
        if not self.local.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='exact_local_applications'").fetchone():
            raise ValueError('Exact Sheets acknowledgement lacks a verified local plan binding.')
        selected_digest = _digest(readback['rows'])
        with self.local.transaction():
            parent = self.local.db.execute(
                'SELECT apply_id,plan_digest,state FROM exact_local_applications '
                'WHERE cycle=? AND company=?', (cycle_id, company_id)).fetchone()
            if parent is None or parent[1] != plan_digest or parent[2] != 'VERIFIED':
                raise ValueError('Exact Sheets acknowledgement lacks a verified local plan binding.')
            apply_id = parent[0]
            prior = self.local.db.execute(
                'SELECT acknowledgement_id,selected_fields_digest '
                'FROM exact_local_acknowledgements WHERE apply_id=? AND receipt_id=?',
                (apply_id, receipt_id)).fetchone()
            if prior is not None:
                if prior != (acknowledgement_id, selected_digest):
                    raise ValueError('Exact Sheets acknowledgement changed after persistence.')
                return {'acknowledged_rows': len(readback['rows']), 'recovered': True,
                        'apply_id': apply_id, 'acknowledgement_id': acknowledgement_id}
            for evidence, observed in zip(exact_plan['rows'], readback['rows']):
                if any(observed.get(key) != evidence.get(key)
                       for key in ('tab', 'row_id', 'identity', 'fields', 'sent')):
                    raise ValueError('Exact Sheets readback row binding changed.')
                tab, row_id = evidence['tab'], evidence['row_id']
                matches = self.local.matches(tab, evidence['identity'])
                if len(matches) != 1 or matches[0][0] != row_id:
                    raise ValueError('Exact Sheets local identity moved before acknowledgement.')
                current = matches[0][1]
                if any(not _equivalent(header, current.get(header, ''), value)
                       for header, value in evidence.get('guards', {}).items()):
                    raise ValueError('Exact Sheets local guard changed before acknowledgement.')
                baseline = self.local.baseline(tab, row_id) or {}
                for header in evidence['fields']:
                    actual = observed['actual'].get(header, '')
                    sent = evidence['sent'].get(header, '')
                    if not _equivalent(header, actual, sent):
                        raise ValueError('Exact Sheets confirmed value differs from frozen sent value.')
                    baseline[header] = actual
                    if _equivalent(header, current.get(header, ''), sent):
                        self.local.db.execute(
                            'DELETE FROM dirty WHERE tab=? AND row_id=? AND header=?',
                            (tab, row_id, header))
                self.local._baseline(tab, row_id, baseline)
                # This exact path never creates rows in the normal writer's
                # shared delivery_attempts table.  Therefore none can be
                # attributed to this receipt, and every row is left intact.
            self.local.db.execute(
                'INSERT INTO exact_local_acknowledgements VALUES (?,?,?,?,?)',
                (apply_id, receipt_id, acknowledgement_id,
                 selected_digest, timestamp()))
        return {'acknowledged_rows': len(readback['rows']), 'recovered': False,
                'apply_id': apply_id, 'acknowledgement_id': acknowledgement_id}

    def publish_batch(self, limit=500, *, row_scope=None, guards=()):
        """Publish queued fields, optionally restricted to explicit local rows/fields."""
        plans = self._operations(limit, row_scope=row_scope)
        if not plans:
            return {'published_rows': 0}
        # Record attempted values before sending, so a later pull can distinguish
        # a lost acknowledgement from an unrelated manual choice matching an AI result.
        with self.local.transaction():
            for tab, rid, fields, sent, op in plans:
                attempted = {h: sent.get(h, '') for h in fields}
                self.local.db.execute('INSERT INTO delivery_attempts VALUES (?,?,?) ON CONFLICT(tab,row_id) DO UPDATE SET data=excluded.data',
                                      (tab, rid, encode(attempted)))
        operations = [*guards, *(p[4] for p in plans)]
        for tab, rid, fields, sent, op in plans:
            if tab == 'Opportunities' and op['append_if_missing']:
                history = self.local.matches('Job History', {'Company': sent['Company'], 'Official Job URL': sent['Job URL']})
                if len(history) != 1:
                    raise RepositoryError('Opportunity lost its unique associated history record before publication.')
                row = history[0][1]
                if str(row.get('Added to Opportunities?', '')).casefold() != 'yes':
                    raise RepositoryError('Opportunity selection changed before publication; pull fresh controls.')
                values = {'Added to Opportunities?': 'Yes', 'Source Hash': row.get('Source Hash', '')}
                if self.publication is not None:
                    values.pop('Source Hash')
                # A no-change guard in the SAME Google batch prevents an Opportunity
                # append after a No edit already visible at Google's fresh read.
                operations.insert(0, {'tab': 'Job History', 'identity': {'Job Key': row['Job Key']},
                                      'values': values, 'expected': values})
        try:
            result = self.remote.commit(operations)
        except Exception:
            # A timeout may follow a successful remote write. Do not clear any
            # delivery state; the same identities/values are safe to reconcile.
            raise
        committed = dict(getattr(self.remote, '_committed_rows', {}))
        # A replay may be a no-op and return no touched rows. Resolve by stable
        # identity, then read back only missing rows, outside the local lock.
        def find_actual(tab, sent):
            target = identity_for(tab, sent)
            matches = [row for row in committed.get(tab, [])
                       if all(_equivalent(h, row.get(h, ''), v) for h, v in target.items())]
            if len(matches) > 1:
                raise RepositoryError(f'{tab}: ambiguous publication acknowledgement.')
            return matches[0] if matches else None
        for tab, rid, fields, sent, op in plans:
            if find_actual(tab, sent) is not None:
                continue
            target = identity_for(tab, sent)
            matches = [(n, row) for n, row in self.remote.read_columns(tab, list(target))
                       if all(_equivalent(h, row.get(h, ''), v) for h, v in target.items())]
            if len(matches) > 1:
                raise RepositoryError(f'{tab}: duplicate remote identity during readback.')
            if matches:
                row = self.remote.read_row(tab, matches[0][0])
                if not all(_equivalent(h, row.get(h, ''), v) for h, v in target.items()):
                    raise RepositoryError(f'{tab}: row moved during acknowledgement; retry a fresh sync.')
                committed.setdefault(tab, []).append(row)
        published = 0
        with self.local.transaction():
            for tab, rid, fields, sent, op in plans:
                base = self.local.baseline(tab, rid) or {}
                current = self.local.row(tab, rid)
                # A repository review lock can skip a row without failing the batch.
                actual = None
                for row in committed.get(tab, []):
                    target = identity_for(tab, sent)
                    if all(_equivalent(h, row.get(h, ''), value) for h, value in target.items()):
                        actual = row; break
                if actual is None:
                    continue
                acknowledged = set()
                for h in fields:
                    if _equivalent(h, actual.get(h, ''), sent.get(h, '')):
                        base[h] = actual.get(h, '')
                        acknowledged.add(h)
                        if _equivalent(h, current.get(h, ''), sent.get(h, '')):
                            self.local.db.execute('DELETE FROM dirty WHERE tab=? AND row_id=? AND header=?', (tab, rid, h))
                for h, value in op['identity'].items():
                    base[h] = actual.get(h, value)
                if tab == 'Companies' and actual.get('Company ID'):
                    base['Company ID'] = actual['Company ID']
                self.local._baseline(tab, rid, base)
                self.local.db.execute('DELETE FROM delivery_attempts WHERE tab=? AND row_id=?', (tab, rid))
                if fields <= acknowledged:
                    published += 1
            self.local.set_meta('last_sync', timestamp())
            self.local.set_meta('last_error', '')
        return {**result, 'published_rows': published}

    def once(self):
        pulled = self.pull()
        published = self.publish_batch()
        return {'pull': pulled, 'publish': published, **self.local.status()}
