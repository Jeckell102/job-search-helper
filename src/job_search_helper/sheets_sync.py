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

from .repository import (BatchPayloadTooLarge, MissingIdentityError, PreflightWriteError, ReviewFieldsChangedError, RepositoryError,
                         USER_FIELDS, IdentityIndex, _equivalent, _identity_key)
from .sqlite_repository import REVIEW_FIELDS, encode, identity_for, timestamp
from .sheet_profile import COMPACT_PULL_FIELDS, profile_schemas, prune_local_only_delivery
from . import publication_receipts

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
COMPANY_CONTROLS = ('Company Status', 'Official Careers URL', 'ATS / Source', 'Claimed By', 'Claim Token')
COMPANY_SOURCES = {'Official Careers URL', 'ATS / Source'}
COMPANY_ALIAS_PREFIX = 'company_owner_alias:'


# A posting with no compensation is persisted by the scraper as this exact,
# structured empty envelope. It is deliberately narrower than "any JSON" or
# "any falsy value": unfamiliar source data remains under reconciliation.
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


def _clean_observation_field(header, baseline, current, frozen_operation):
    """Prove a clean field or a pinned blank awaiting read-only observation."""
    if header in baseline:
        return _equivalent(header, baseline[header], current.get(header, ''))
    if not isinstance(frozen_operation, Mapping):
        return False
    frozen_values = {}
    for group in ('values', 'on_insert'):
        selected = frozen_operation.get(group, {})
        if not isinstance(selected, Mapping):
            return False
        for name, value in selected.items():
            if (name in frozen_values
                    and not _equivalent(name, frozen_values[name], value)):
                return False
            frozen_values[name] = value
    frozen_notes = frozen_operation.get('append_notes', {})
    if not isinstance(frozen_notes, Mapping):
        return False
    return (header not in frozen_notes
            and header in frozen_values
            and _equivalent(header, frozen_values[header], '')
            and _equivalent(header, current.get(header, ''), ''))


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
        self._publish_limit = 500

    def _refuse_retained_publication_hold(self):
        """Keep generic pull/publish paths outside exceptional ownership."""
        table = self.local.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='retained_publications'").fetchone()
        intake = self.local.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='retained_intake_holds'").fetchone()
        if intake:
            frozen = self.local.db.execute(
                "SELECT reservation_digest FROM retained_intake_holds "
                "WHERE state='FROZEN' ORDER BY reservation_digest LIMIT 1").fetchone()
            if frozen is not None:
                raise RepositoryError(
                    'Retained intake hold requires the dedicated exact publisher.')
        if not table:
            return
        held = self.local.db.execute(
            "SELECT reservation_digest,state FROM retained_publications "
            "WHERE state != 'FIRST_PASS_RELEASED' "
            "ORDER BY reservation_digest LIMIT 1").fetchone()
        if held is not None:
            raise RepositoryError(
                'Retained publication hold requires the dedicated exact publisher.')

    def _company_alias_ids(self, name):
        key = COMPANY_ALIAS_PREFIX + _identity_key('Company', name)
        try:
            ids = json.loads(self.local.get_meta(key) or '[]')
        except (ValueError, TypeError) as exc:
            raise RepositoryError('Invalid saved company ownership aliases; reconciliation required.') from exc
        if not isinstance(ids, list) or any(type(rid) is not int or rid < 1 for rid in ids):
            raise RepositoryError('Invalid saved company ownership aliases; reconciliation required.')
        return set(ids)

    def _remember_company_names(self, rid, *names):
        # A running worker or retained inventory can still refer to an old
        # display name. Preserve that ownership across intake and restarts.
        for name in {_identity_key('Company', name) for name in names if name} - {''}:
            ids = self._company_alias_ids(name) | {rid}
            self.local.set_meta(COMPANY_ALIAS_PREFIX + name, encode(sorted(ids)))

    def _company_context(self, tab, rid, row):
        if tab == 'Companies':
            return rid, row, self.local.baseline(tab, rid)
        name = row.get('Company')
        if not name:
            return None
        ids = {rid for rid, _ in self.local.matches('Companies', {'Company': name})}
        ids.update(self._company_alias_ids(name))
        matches = [(rid, self.local.row('Companies', rid)) for rid in sorted(ids)]
        if any(company is None for _, company in matches):
            raise RepositoryError('Saved company ownership no longer resolves; reconciliation required.')
        if len(matches) > 1:
            raise RepositoryError('Pending publication has an ambiguous company owner; reconcile company identities.')
        if not matches:
            return None  # Historical orphan records have no company controls to assert.
        company_id, company = matches[0]
        return company_id, company, self.local.baseline('Companies', company_id)

    @staticmethod
    def _company_held(company):
        return (str(company.get('Company Status', '')).strip().casefold() in {'pause', 'paused', 'remove'}
                or bool(company.get('Claimed By') or company.get('Claim Token')))

    def _hold_changed_company_source(self, company_id, current, observed, field):
        # The outbox predates a company-source version field. Conservatively
        # retain old-board outputs until an explicit provenance reconciliation;
        # importing the new URL must not silently validate an older inventory.
        owned = {('Companies', company_id)}
        names = {current.get('Company'), observed.get('Company')} - {None, ''}
        for key, _ in self.local.db.execute('SELECT key,value FROM meta WHERE key GLOB ?', (COMPANY_ALIAS_PREFIX + '*',)):
            name = key[len(COMPANY_ALIAS_PREFIX):]
            if company_id in self._company_alias_ids(name):
                names.add(name)
        for tab in ('Job History', 'Job Evidence', 'Opportunities'):
            for name in names:
                owned.update((tab, rid) for rid, _ in self.local.matches(tab, {'Company': name}))
        cycle = current.get('Active Cycle ID')
        if cycle:
            owned.update(('Scan Cycles', rid) for rid, _ in self.local.matches('Scan Cycles', {'Cycle ID': cycle}))
        for tab, rid in owned:
            if tab == 'Companies' or self.local.db.execute('SELECT 1 FROM dirty WHERE tab=? AND row_id=?', (tab, rid)).fetchone():
                self.local.conflict(tab, rid, '__company_source__',
                    f'Company {field} changed; reconcile saved inventories and outputs against the new source before publication.')

    def baseline_tokens(self, tab, *, keys=None):
        """Fence a remote control read against acknowledgements during that read."""
        fields = ('Job Key', 'Added to Opportunities?', 'Review Notes')
        paths = ['$.' + json.dumps(h) for h in fields]
        columns = ','.join('json_extract(data,?)' for _ in fields)
        clause, parameters = '', ()
        if keys is not None:
            keys = list(keys)
            if not keys:
                return {}
            clause = ' AND row_id IN (SELECT row_id FROM lookups WHERE tab=? AND header=? AND value IN (' + ','.join('?' for _ in keys) + '))'
            parameters = (tab, 'Job Key', *[_identity_key('Job Key', key) for key in keys])
        return {rid: tuple('' if v is None else v for v in values)
                for rid, *values in self.local.db.execute(
                    f'SELECT row_id,{columns} FROM baseline WHERE tab=?' + clause, (*paths, tab, *parameters))}

    def merge_remote(self, tab, numbered, *, complete_snapshot=True, expected_baselines=None):
        """Import changed fields, not stale whole-row snapshots."""
        self._refuse_retained_publication_hold()
        numbered = unique_rows(tab, list(numbered))
        imported = changed = stale = 0
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
                if expected_baselines is not None:
                    token = tuple(base.get(h) or '' for h in ('Job Key', 'Added to Opportunities?', 'Review Notes')) if base else None
                    if token != expected_baselines.get(rid):
                        # Another publisher acknowledged a newer control value
                        # while this Google response was in flight. Its older
                        # contents cannot establish a subsequent human edit.
                        stale += 1
                        continue
                dirty = {h for (h,) in self.local.db.execute('SELECT header FROM dirty WHERE tab=? AND row_id=?', (tab, rid))}
                original_company = dict(current) if tab == 'Companies' else None
                if tab == 'Companies':
                    names = (base.get('Company'), current.get('Company'), observed.get('Company'))
                    if len({_identity_key('Company', name) for name in names if name}) > 1:
                        self._remember_company_names(rid, *names)
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
                    elif (tab == 'Opportunities' and header == 'Fit Review'
                          and value in {'Strong Potential Fit', 'Potential Fit', 'Not Relevant', ''}
                          and header not in dirty and header not in attempted
                          and _equivalent(header, local_value, before)):
                        # A review made in Sheets is a one-sided change when
                        # local processing has not changed this rating. Import
                        # it without letting an unrelated date update veto it.
                        # Concurrent local ratings and uncertain deliveries
                        # still take the conflict path below.
                        pass
                    elif (tab == 'Opportunities' and header == 'Salary / Range'
                          and header not in dirty
                          and _missing_extracted_salary(local_value)
                          and _plausible_salary_estimate(value)):
                        # User-maintained estimates are a fallback only when
                        # the current posting yielded no salary at all. A
                        # nonblank or newly-updated extracted value remains
                        # locally managed and therefore conflicts.
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
                    if tab == 'Companies' and header in COMPANY_SOURCES:
                        self._hold_changed_company_source(rid, original_company, observed, header)
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
        return {'imported': imported, 'changed_fields': changed, **({'stale_rows': stale} if stale else {})}

    def pull(self):
        self._refuse_retained_publication_hold()
        main = getattr(self.remote, 'main', self.remote)
        if hasattr(main, '_metadata_cache'):
            main._metadata_cache = None
            main._header_cache.clear()
        totals = {}
        for tab, headers in self.pull_fields.items():
            total = {'imported': 0, 'changed_fields': 0}
            for attempt in range(2):
                tokens = self.baseline_tokens(tab) if tab == 'Job History' else None
                if headers is None:
                    # Cell-aware reads preserve rich hyperlink targets, dates, and labels.
                    numbered = list(enumerate(self.remote.read(tab), 2))
                else:
                    numbered = self.remote.read_columns(tab, headers)
                merged = self.merge_remote(tab, numbered, expected_baselines=tokens)
                for key in total:
                    total[key] += merged[key]
                if not merged.get('stale_rows'):
                    break
            else:
                raise RepositoryError('Review publication advanced during both Sheet reads; retry fresh controls.')
            totals[tab] = total
        from .engine import Engine
        engine = Engine(self.local, None)
        # Stable IDs must exist before the first external watermark is seeded.
        # Otherwise an old ID-less row could be mistaken for a new Company on
        # the very next pull after this normal local assignment.
        for row in self.local.read('Companies'):
            if row.get('Company') and not row.get('Company ID'):
                engine._assign_company_id(row)
        # The first full Companies snapshot is a durable watermark only. Later
        # normal pulls emit a scoped change event rather than watching Sheets.
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
        self._refuse_retained_publication_hold()
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
            if row_scope is None:
                owner = self._company_context(tab, rid, current)
                if owner and (self._company_held(owner[1]) or self.local.db.execute(
                        "SELECT 1 FROM conflicts WHERE tab='Companies' AND row_id=? AND header='__company_source__'", (owner[0],)).fetchone()):
                    continue  # Keep every dirty field, including outputs arriving after intake.
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
            if self.publication is not None and tab == 'Job History' and row_scope is None:
                # Compact Sheets is a projection of locally owned source/review
                # outputs. Intake refreshes only human choices and notes, so an
                # old display value must not permanently veto their publication.
                # Keep human edits and key migrations guarded. Explicit scoped
                # review writes retain all of their expected-field checks.
                expected = {h: v for h, v in expected.items()
                            if h in HUMAN_FIELDS[tab] or h == 'Job Key'}
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

    def _plan_exact_row(self, item, frozen_operation=None, *,
                        delivery_mode='write_once'):
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
            clean_verified = (delivery_mode == 'observation_only'
                              and all(_clean_observation_field(
                                  header, base, current, frozen_operation)
                                      for header in missing_dirty))
            if not clean_verified:
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
        if (base and not item['append_if_missing']
                and delivery_mode != 'observation_only'):
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
        # Local row-scope guards may be stronger than the compact Sheets
        # projection (for example Job History Source Hash).  They are checked
        # above against the local record, but an absent compact column must
        # not be injected into the sealed remote operation.
        remote_expected = expected
        if self.publication is not None:
            remote_expected = {
                header: value for header, value in expected.items()
                if header in self.publication[tab]
            }
        operation = {'tab': tab, 'identity': identity, 'values': values,
                     'append_if_missing': item['append_if_missing'], 'on_insert': inserted,
                     'expected': remote_expected, 'append_notes': notes}
        return {'tab': tab, 'row_id': row_id, 'identity': item['identity'],
                'fields': sorted(fields), 'sent': copy.deepcopy(current),
                'guards': copy.deepcopy(item['guards']),
                'expected': copy.deepcopy(item['expected']), 'operation': operation}

    def plan_exact_scope(self, row_scope, frozen_projection, *,
                         delivery_mode='write_once'):
        """Plan only explicit rows and require exact frozen-projection equality.

        This method does not call ``pull``, ``once``, ``publish_batch``,
        ``prune_local_only_delivery`` or global dirty-candidate discovery.
        """
        if (delivery_mode not in {'write_once', 'observation_only'}
                or not isinstance(frozen_projection, list)
                or not frozen_projection):
            raise ValueError('Exact Sheets frozen projection must be a nonempty operation list.')
        normalized = self._normalize_exact_scope(row_scope)
        if len(normalized) != len(frozen_projection):
            raise ValueError('Exact Sheets scope and frozen projection lengths differ.')
        # Durable local scope is canonicalized by tab and row identity, while
        # the sealed remote projection retains its original delivery order.
        # Pairing these two independent orderings positionally can associate a
        # Job History insert with a Companies update.  Match on the final
        # stable identity instead, then preserve the frozen delivery order.
        def final_identity(operation):
            if not isinstance(operation, Mapping):
                raise ValueError('Exact Sheets frozen projection has an invalid operation.')
            identity = copy.deepcopy(operation.get('identity', {}))
            if not isinstance(identity, Mapping) or not identity:
                raise ValueError('Exact Sheets frozen projection has an invalid identity.')
            for values in (operation.get('on_insert', {}), operation.get('values', {})):
                if not isinstance(values, Mapping):
                    raise ValueError('Exact Sheets frozen projection has invalid values.')
                for header in tuple(identity):
                    if header in values:
                        identity[header] = copy.deepcopy(values[header])
            return identity

        def label(tab, identity):
            return (tab, tuple(sorted(
                (str(header), _identity_key(str(header), value))
                for header, value in identity.items())))

        scoped = {label(item['tab'], item['identity']): item for item in normalized}
        if len(scoped) != len(normalized):
            raise ValueError('Exact Sheets row scope repeats a stable identity.')
        operations = {}
        for operation in frozen_projection:
            if (not isinstance(operation, Mapping)
                    or type(operation.get('append_if_missing')) is not bool):
                raise ValueError('Exact Sheets sealed insert semantics differ from the frozen projection.')
            key = label(operation.get('tab'), final_identity(operation))
            if key in operations:
                raise ValueError('Exact Sheets frozen projection repeats a stable identity.')
            operations[key] = operation
        if set(scoped) != set(operations):
            raise ValueError('Exact Sheets scope and frozen projection identities differ.')
        rows = []
        for operation in frozen_projection:
            item = scoped[label(operation['tab'], final_identity(operation))]
            if item['append_if_missing'] != operation['append_if_missing']:
                raise ValueError('Exact Sheets sealed insert semantics differ from the frozen projection.')
            rows.append(self._plan_exact_row(
                item, operation, delivery_mode=delivery_mode))
        operations = [row['operation'] for row in rows]
        if encode(operations) != encode(frozen_projection):
            raise ValueError('Exact Sheets scoped plan differs from the frozen projection.')
        return {'operations': copy.deepcopy(operations), 'rows': rows,
                'projection_digest': _digest(operations),
                'delivery_mode': delivery_mode}

    def _validate_exact_plan(self, exact_plan):
        if (not isinstance(exact_plan, Mapping)
                or not {'operations', 'rows', 'projection_digest'} <= set(exact_plan)
                or set(exact_plan) - {
                    'operations', 'rows', 'projection_digest',
                    'record_fingerprint_version', 'delivery_mode'}
                or exact_plan.get('delivery_mode', 'write_once') not in {
                    'write_once', 'observation_only'}
                or exact_plan.get('record_fingerprint_version', 1) not in {1, 2}
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
            missing_dirty = ((set(evidence['fields']) - set(evidence['identity']))
                             - dirty)
            if baseline is not None and missing_dirty:
                clean_verified = (
                    exact_plan.get('delivery_mode') == 'observation_only'
                    and all(_clean_observation_field(
                        header, baseline, current, evidence.get('operation'))
                            for header in missing_dirty))
                if not clean_verified:
                    raise ValueError(
                        'Exact Sheets selected field lost its delivery evidence.')

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
            if any(not _equivalent(header, actual.get(header, ''), value)
                   for header, value in identity.items()):
                raise ValueError('Exact Sheets remote row moved during readback.')
            for values in (operation.get('on_insert', {}), operation.get('values', {})):
                if any(not _equivalent(header, actual.get(header, ''), value)
                       for header, value in values.items()):
                    raise ValueError('Exact Sheets remote readback differs from the frozen projection.')
            for header, suffix in operation.get('append_notes', {}).items():
                if str(suffix) not in str(actual.get(header, '')):
                    raise ValueError('Exact Sheets remote note readback is missing its frozen suffix.')
            mutated = set(operation.get('on_insert', {}))
            mutated.update(operation.get('values', {}))
            mutated.update(operation.get('append_notes', {}))
            guard_only = {header: value for header, value
                          in operation.get('expected', {}).items()
                          if header not in mutated}
            if any(header not in actual for header in guard_only):
                raise ValueError('Exact Sheets remote guard readback is incomplete.')
            if any(not _equivalent(header, actual.get(header, ''), value)
                   for header, value in guard_only.items()):
                raise ValueError('Exact Sheets remote guard differs from the frozen projection.')
            observed_row = {
                'tab': tab, 'row_id': evidence['row_id'],
                'identity': copy.deepcopy(evidence['identity']),
                'fields': list(evidence['fields']),
                'sent': copy.deepcopy(evidence['sent']),
                'actual': {header: actual.get(header, '')
                           for header in evidence['fields']},
            }
            # Preserve the byte-for-byte acknowledgement contract for v1
            # plans that may already be durably confirmed.  Version 2 is the
            # explicit format that carries guard values in its receipt proof.
            if exact_plan.get('record_fingerprint_version', 1) == 2:
                observed_row['remote_guards'] = {
                    header: copy.deepcopy(actual[header])
                    for header in sorted(guard_only)}
            observed.append(observed_row)
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
            row.update(observed.get('remote_guards', {}))
            rows.setdefault(operation['tab'], []).append(row)
        return record_fingerprints(
            exact_plan['operations'], rows,
            include_guard_only=exact_plan.get('record_fingerprint_version', 1) == 2)

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

    @staticmethod
    def _require_observation_read_guard(exact_plan, callback):
        """Reject an observation read unless its post-read guard is callable."""
        if exact_plan.get('delivery_mode', 'write_once') != 'observation_only':
            return
        if not callable(callback):
            raise ValueError(
                'Exact Sheets observation requires a post-read Company guard.')

    @classmethod
    def _post_observation_read_guard(cls, exact_plan, callback):
        """Revalidate external controls after a read and before confirmation."""
        cls._require_observation_read_guard(exact_plan, callback)
        if exact_plan.get('delivery_mode', 'write_once') != 'observation_only':
            return
        callback()

    def _readback_and_confirm_chunk(self, exact_plan, inbox, *, cycle_id,
                                    company_id, plan_digest, receipt_id,
                                    intent_id, remote_projection_digest,
                                    remote_cursor,
                                    post_observation_read_guard=None):
        """Perform the remote read and consume its chunk evidence internally."""
        self._require_observation_read_guard(
            exact_plan, post_observation_read_guard)
        before_read = self._durable_exact_plan(
            inbox, cycle_id=cycle_id, company_id=company_id,
            plan_digest=plan_digest, receipt_id=receipt_id,
            intent_id=intent_id)
        stop = remote_cursor + len(exact_plan['operations'])
        durable_operations = before_read.get('operations', [])[remote_cursor:stop]
        durable_rows = before_read.get('rows', [])[remote_cursor:stop]
        if (durable_operations != exact_plan.get('operations')
                or len(durable_rows) != len(durable_operations)
                or exact_plan.get('projection_digest') != _digest(durable_operations)
                or before_read.get('delivery_mode')
                != exact_plan.get('delivery_mode', 'write_once')):
            raise ValueError('Exact Sheets durable chunk scope changed before remote read.')
        # Row metadata supplied by the caller is deliberately not trusted here.
        # Rebuild the chunk from the durable local application and frozen remote
        # projection so readback and acknowledgement cannot be redirected.
        durable_chunk = {
            'operations': copy.deepcopy(durable_operations),
            'rows': copy.deepcopy(durable_rows),
            'projection_digest': _digest(durable_operations),
            'delivery_mode': before_read.get('delivery_mode', 'write_once'),
            'record_fingerprint_version': before_read.get(
                'record_fingerprint_version', 1),
        }
        readback = self.readback_exact_scope(
            durable_chunk, receipt_id=receipt_id, intent_id=intent_id,
            intent_projection_digest=durable_chunk['projection_digest'])
        self._post_observation_read_guard(
            durable_chunk, post_observation_read_guard)
        after_read = self._durable_exact_plan(
            inbox, cycle_id=cycle_id, company_id=company_id,
            plan_digest=plan_digest, receipt_id=receipt_id,
            intent_id=intent_id)
        if encode(after_read) != encode(before_read):
            raise ValueError('Exact Sheets durable scope changed during remote read.')
        stamp = timestamp()
        with inbox.lock, inbox.connection:
            remote = inbox.connection.execute(
                'SELECT local_plan_digest,projection_digest,receipt_id,intent_id,'
                'remote_cursor,state,first_attempt_claimed,projection,'
                'delivery_mode,observed_at FROM exact_remote_plans '
                'WHERE cycle=? AND company=?', (cycle_id, company_id)).fetchone()
            expected = (plan_digest, remote_projection_digest, receipt_id, intent_id)
            if remote is None or tuple(remote[:4]) != expected:
                raise ValueError('Exact remote chunk does not match its frozen intent.')
            frozen = json.loads(remote[7])
            if (remote_cursor + len(exact_plan['operations']) > len(frozen)
                    or frozen[remote_cursor:remote_cursor + len(exact_plan['operations'])]
                    != exact_plan['operations']
                    or _digest(frozen) != remote_projection_digest):
                raise ValueError('Exact remote projection changed during chunk readback.')
            chunk = inbox.connection.execute(
                'SELECT count,digest,state FROM exact_sync_chunks '
                'WHERE cycle=? AND company=? AND cursor=?',
                (cycle_id, company_id, remote_cursor)).fetchone()
            if chunk is None or chunk[1] != exact_plan['projection_digest']:
                raise ValueError('Exact remote chunk confirmation evidence is missing.')
            if chunk[0] != len(exact_plan['operations']):
                raise ValueError('Exact remote chunk count changed during confirmation.')
            next_cursor = remote_cursor + chunk[0]
            if chunk[2] == 'CONFIRMED' and remote[4] == next_cursor:
                return readback
            delivery_ready = (remote[8] == 'write_once' and bool(remote[6])) or (
                remote[8] == 'observation_only' and not remote[6] and remote[9])
            if (remote[4] != remote_cursor or remote[5] != 'SYNC_PENDING'
                    or remote[8] != exact_plan.get('delivery_mode', 'write_once')
                    or not delivery_ready or chunk[2] != 'PENDING'):
                raise ValueError('Exact remote chunk confirmation cursor/state is invalid.')
            inbox.connection.execute(
                "UPDATE exact_sync_chunks SET state='CONFIRMED' "
                'WHERE cycle=? AND company=? AND cursor=?',
                (cycle_id, company_id, remote_cursor))
            updated = inbox.connection.execute(
                "UPDATE exact_remote_plans SET remote_cursor=?,updated_at=? "
                "WHERE cycle=? AND company=? AND state='SYNC_PENDING' "
                'AND remote_cursor=?',
                (next_cursor, stamp, cycle_id, company_id, remote_cursor)).rowcount
            if updated != 1:
                raise ValueError('Exact remote chunk cursor changed during confirmation.')
        return readback

    def _readback_and_confirm_full(self, *, inbox, cycle_id, company_id,
                                   plan_digest, receipt_id, intent_id,
                                   post_observation_read_guard=None):
        """Perform full remote readback and atomically confirm its receipt."""
        # This entrypoint is also used directly by recovery tests and callers;
        # reject a missing observation guard before even rebuilding the durable
        # plan, so no remote read can precede the fail-closed decision.
        remote_state = inbox.exact_remote_state(cycle_id, company_id)
        if (isinstance(remote_state, Mapping)
                and remote_state.get('delivery_mode') == 'observation_only'
                and not callable(post_observation_read_guard)):
            raise ValueError(
                'Exact Sheets observation requires a post-read Company guard.')
        exact_plan = self._durable_exact_plan(
            inbox, cycle_id=cycle_id, company_id=company_id,
            plan_digest=plan_digest, receipt_id=receipt_id,
            intent_id=intent_id)
        self._require_observation_read_guard(
            exact_plan, post_observation_read_guard)
        readback = self.readback_exact_scope(
            exact_plan, receipt_id=receipt_id, intent_id=intent_id,
            intent_projection_digest=exact_plan['projection_digest'])
        self._post_observation_read_guard(
            exact_plan, post_observation_read_guard)
        after_read = self._durable_exact_plan(
            inbox, cycle_id=cycle_id, company_id=company_id,
            plan_digest=plan_digest, receipt_id=receipt_id,
            intent_id=intent_id)
        if encode(after_read) != encode(exact_plan):
            raise ValueError('Exact Sheets durable scope changed during remote read.')
        acknowledgement_id = readback['acknowledgement_id']
        stamp = timestamp()
        with inbox.lock, inbox.connection:
            remote = inbox.connection.execute(
                'SELECT local_plan_digest,projection_digest,receipt_id,intent_id,'
                'remote_cursor,state,first_attempt_claimed,acknowledgement_id,projection,'
                'delivery_mode,observed_at '
                'FROM exact_remote_plans WHERE cycle=? AND company=?',
                (cycle_id, company_id)).fetchone()
            expected = (plan_digest, exact_plan['projection_digest'],
                        receipt_id, intent_id)
            if remote is None or tuple(remote[:4]) != expected:
                raise ValueError('Exact remote confirmation does not match frozen intent.')
            frozen = json.loads(remote[8])
            if (frozen != exact_plan['operations']
                    or _digest(frozen) != exact_plan['projection_digest']):
                raise ValueError('Exact remote projection changed during full readback.')
            delivery_ready = (remote[9] == 'write_once' and bool(remote[6])) or (
                remote[9] == 'observation_only' and not remote[6] and remote[10])
            if (remote[5] not in {'SYNC_PENDING', 'SYNC_CONFIRMED'}
                    or remote[4] != len(exact_plan['operations'])
                    or remote[9] != exact_plan.get('delivery_mode', 'write_once')
                    or not delivery_ready):
                raise ValueError('Exact remote confirmation cursor/state is invalid.')
            if remote[7] is not None and remote[7] != acknowledgement_id:
                raise ValueError('Exact remote acknowledgement changed after confirmation.')
            receipt = inbox.connection.execute(
                'SELECT binding,state,acknowledgement_id FROM publication_receipts '
                'WHERE receipt_id=?', (receipt_id,)).fetchone()
            if receipt is None:
                raise ValueError('Exact remote confirmation receipt is missing.')
            observed_records = self._exact_readback_records(exact_plan, readback)
            stored_records = inbox.connection.execute(
                'SELECT records FROM publication_receipts WHERE receipt_id=?',
                (receipt_id,)).fetchone()
            if stored_records is None or publication_receipts._records(
                    observed_records) != json.loads(stored_records[0]):
                raise ValueError('Exact remote readback does not match its receipt.')
            if receipt[1] != publication_receipts.SYNC_CONFIRMED:
                if receipt[1] != publication_receipts.SYNC_PENDING:
                    raise ValueError('Exact remote receipt is not pending confirmation.')
                updated_receipt = inbox.connection.execute(
                    'UPDATE publication_receipts SET state=?,acknowledgement_id=?,updated_at=? '
                    'WHERE receipt_id=? AND state=?',
                    (publication_receipts.SYNC_CONFIRMED, acknowledgement_id, stamp,
                     receipt_id, publication_receipts.SYNC_PENDING)).rowcount
                if updated_receipt != 1:
                    raise ValueError('Exact remote receipt changed during confirmation.')
            elif receipt[2] != acknowledgement_id:
                raise ValueError('Exact remote receipt acknowledgement changed.')
            total = len(json.loads(remote[8]))
            chunks = inbox.connection.execute(
                'SELECT cursor,count,state FROM exact_sync_chunks '
                'WHERE cycle=? AND company=? ORDER BY cursor',
                (cycle_id, company_id)).fetchall()
            covered = 0
            for chunk_cursor, count, state in chunks:
                if chunk_cursor != covered or state != 'CONFIRMED':
                    break
                covered += count
            if remote[4] != total or covered != total:
                raise ValueError('Exact remote confirmation cursor/state is invalid.')
            updated = inbox.connection.execute(
                "UPDATE exact_remote_plans SET state='SYNC_CONFIRMED',"
                'acknowledgement_id=?,updated_at=? WHERE cycle=? AND company=?',
                (acknowledgement_id, stamp, cycle_id, company_id)).rowcount
            if updated != 1:
                raise ValueError('Exact remote plan disappeared during confirmation.')
        inbox.require_exact_remote_confirmed(
            cycle_id, company_id, local_plan_digest=plan_digest,
            projection_digest=exact_plan['projection_digest'],
            receipt_id=receipt_id, intent_id=intent_id,
            acknowledgement_id=acknowledgement_id)
        return readback

    def publish_exact_scope(self, exact_plan, *, inbox, cycle_id, company_id,
                            plan_digest, receipt_id, intent_id,
                            remote_projection_digest=None, remote_cursor=0,
                            max_operations=100,
                            max_bytes=500_000,
                            post_observation_read_guard=None):
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
        delivery_mode = exact_plan.get('delivery_mode', 'write_once')
        if (delivery_mode == 'observation_only'
                and not callable(post_observation_read_guard)):
            raise ValueError(
                'Exact Sheets observation requires a post-read Company guard.')
        size = len(encode(operations).encode('utf-8'))
        if len(operations) > max_operations or size > max_bytes:
            raise ValueError('Exact Sheets frozen projection exceeds the remote bound.')
        # Avoid blocking readback-only recovery on a newer local edit: the
        # acknowledgement path deliberately preserves it.  A never-attempted
        # intent is checked both before and immediately after its atomic claim.
        remote_state = inbox.exact_remote_state(cycle_id, company_id)
        if (not isinstance(remote_state, Mapping)
                or remote_state.get('delivery_mode', 'write_once') != delivery_mode):
            raise ValueError('Exact Sheets delivery mode differs from its durable intent.')
        prior_chunk = inbox.exact_chunk(cycle_id, company_id, remote_cursor)
        if prior_chunk is not None and prior_chunk.get('state') == 'CONFIRMED':
            if (prior_chunk.get('count') != len(operations)
                    or prior_chunk.get('digest') != exact_plan['projection_digest']
                    or not isinstance(remote_state, Mapping)
                    or remote_state.get('remote_cursor') < remote_cursor + len(operations)):
                raise ValueError('Exact Sheets confirmed chunk binding is invalid.')
            readback = self._readback_and_confirm_chunk(
                exact_plan, inbox, cycle_id=cycle_id, company_id=company_id,
                plan_digest=plan_digest, receipt_id=receipt_id,
                intent_id=intent_id,
                remote_projection_digest=remote_projection_digest,
                remote_cursor=remote_cursor,
                post_observation_read_guard=post_observation_read_guard)
            return {'commit': None, 'readback': readback, 'first_attempt': False,
                    'acknowledgement_id': readback['acknowledgement_id']}
        if not isinstance(remote_state, Mapping) or not remote_state.get(
                'first_attempt_claimed'):
            self._revalidate_exact_rows(exact_plan)
        result = None
        if delivery_mode == 'observation_only':
            claim = inbox.begin_exact_remote_observation(
                cycle_id, company_id, local_plan_digest=plan_digest,
                projection_digest=remote_projection_digest,
                receipt_id=receipt_id, intent_id=intent_id, cursor=remote_cursor,
                count=len(operations), chunk_digest=exact_plan['projection_digest'],
                timestamp=timestamp())
            if (not isinstance(claim, Mapping)
                    or type(claim.get('first_observation')) is not bool):
                raise ValueError('Exact Sheets durable observation is invalid.')
        else:
            claim = inbox.claim_exact_remote_attempt(
                cycle_id, company_id, local_plan_digest=plan_digest,
                projection_digest=remote_projection_digest,
                receipt_id=receipt_id, intent_id=intent_id, cursor=remote_cursor,
                count=len(operations), chunk_digest=exact_plan['projection_digest'],
                timestamp=timestamp())
            if (not isinstance(claim, Mapping)
                    or type(claim.get('first_attempt')) is not bool):
                raise ValueError('Exact Sheets durable intent claim is invalid.')
        if delivery_mode == 'write_once' and claim['first_attempt']:
            self._revalidate_exact_rows(exact_plan)
            result = self.remote.commit(copy.deepcopy(operations))
        readback = self._readback_and_confirm_chunk(
            exact_plan, inbox, cycle_id=cycle_id, company_id=company_id,
            plan_digest=plan_digest, receipt_id=receipt_id,
            intent_id=intent_id,
            remote_projection_digest=remote_projection_digest,
            remote_cursor=remote_cursor,
            post_observation_read_guard=post_observation_read_guard)
        return {'commit': result, 'readback': readback,
                'first_attempt': claim.get('first_attempt', False),
                'observation_only': delivery_mode == 'observation_only',
                'acknowledgement_id': readback['acknowledgement_id']}

    def _durable_exact_plan(self, inbox, *, cycle_id, company_id, plan_digest,
                            receipt_id, intent_id):
        """Rebuild the exact scope exclusively from durable trusted records."""
        inbox = self._require_exact_inbox(inbox)
        cycle_id = _required_id(cycle_id, 'cycle ID')
        company_id = _required_id(company_id, 'Company ID')
        plan_digest = _required_id(plan_digest, 'plan digest')
        receipt_id = _required_id(receipt_id, 'receipt ID')
        intent_id = _required_id(intent_id, 'intent ID')
        with inbox.lock:
            remote = inbox.connection.execute(
                'SELECT local_plan_digest,projection,projection_digest,'
                'receipt_id,intent_id,delivery_mode FROM exact_remote_plans '
                'WHERE cycle=? AND company=?', (cycle_id, company_id)).fetchone()
            delivery = inbox.connection.execute(
                'SELECT delivery_mode,plan_digest,state,evidence '
                'FROM exact_legacy_delivery_evidence '
                'WHERE cycle=? AND company=?',
                (cycle_id, company_id)).fetchone()
            frozen = inbox.connection.execute(
                'SELECT p.payload,l.plan_digest,l.state FROM sync_plans p '
                'JOIN exact_plan_local_state l '
                'ON l.cycle=p.cycle AND l.company=p.company '
                'WHERE p.cycle=? AND p.company=?',
                (cycle_id, company_id)).fetchone()
        if remote is None or (remote[0], remote[3], remote[4]) != (
                plan_digest, receipt_id, intent_id):
            raise ValueError('Exact Sheets durable remote binding is unavailable.')
        try:
            projection = json.loads(remote[1])
        except (TypeError, ValueError) as error:
            raise ValueError('Exact Sheets durable projection is invalid.') from error
        if not isinstance(projection, list) or _digest(projection) != remote[2]:
            raise ValueError('Exact Sheets durable projection is invalid.')
        if frozen is None or frozen[1:] != (plan_digest, 'LOCAL_VERIFIED'):
            raise ValueError('Exact Sheets durable local plan is unavailable.')
        try:
            plan = json.loads(frozen[0])
        except (TypeError, ValueError) as error:
            raise ValueError('Exact Sheets durable local plan is invalid.') from error
        from .exact_cycle_planner import _exact_plan_digest
        if (not isinstance(plan, Mapping)
                or plan.get('plan_digest') != plan_digest
                or _exact_plan_digest(plan) != plan_digest
                or not isinstance(plan.get('local_operations'), list)):
            raise ValueError('Exact Sheets durable local plan is invalid.')
        stored_projection = plan.get('remote_projection', plan.get('operations'))
        if stored_projection != projection:
            raise ValueError('Exact Sheets durable projection conflicts with its local plan.')
        delivery_mode = remote[5]
        if delivery_mode not in {'write_once', 'observation_only'}:
            raise ValueError('Exact Sheets durable delivery mode is invalid.')
        if delivery_mode == 'observation_only':
            if (delivery is None
                    or tuple(delivery[:3]) != (
                        'observation_only', plan_digest, 'BOUND')):
                raise ValueError('Exact Sheets observation evidence is unavailable.')
        elif delivery is not None and delivery[0] != 'write_once':
            raise ValueError('Exact Sheets delivery evidence conflicts with its mode.')
        if not self.local.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='exact_local_applications'").fetchone():
            raise ValueError('Exact Sheets durable row scope is unavailable.')
        parent = self.local.db.execute(
            'SELECT plan_digest,row_scope,state FROM exact_local_applications '
            'WHERE cycle=? AND company=?', (cycle_id, company_id)).fetchone()
        if parent is None or parent[0] != plan_digest or parent[2] != 'VERIFIED':
            raise ValueError('Exact Sheets durable row scope is unavailable.')
        try:
            row_scope = json.loads(parent[1])
        except (TypeError, ValueError) as error:
            raise ValueError('Exact Sheets durable row scope is invalid.') from error
        normalized = self._normalize_exact_scope(row_scope)
        if len(normalized) != len(projection):
            raise ValueError('Exact Sheets durable scope changed after registration.')

        def final_identity(operation):
            identity = dict(operation.get('identity', {}))
            for values in (operation.get('on_insert', {}), operation.get('values', {})):
                for key in tuple(identity):
                    if key in values:
                        identity[key] = values[key]
            return identity

        rows = []
        for item, operation in zip(normalized, projection):
            candidates = [candidate for candidate in plan['local_operations']
                          if candidate.get('tab') == item['tab']
                          and final_identity(candidate) == item['identity']]
            if len(candidates) != 1 or operation.get('tab') != item['tab']:
                raise ValueError('Exact Sheets durable row evidence is ambiguous.')
            local_operation = candidates[0]
            frozen_values = dict(local_operation.get('expected', {}))
            frozen_values.update(local_operation.get('on_insert', {}))
            frozen_values.update(local_operation.get('values', {}))
            if any(header not in frozen_values for header in item['fields']):
                raise ValueError('Exact Sheets durable row evidence is incomplete.')
            rows.append({**copy.deepcopy(item),
                         'sent': {header: copy.deepcopy(frozen_values[header])
                                  for header in item['fields']},
                         'operation': copy.deepcopy(operation)})
        exact_plan = {'operations': copy.deepcopy(projection), 'rows': rows,
                      'projection_digest': remote[2],
                      'delivery_mode': delivery_mode,
                      'record_fingerprint_version': plan.get(
                          'record_fingerprint_version', 1)}
        self._validate_exact_plan(exact_plan)
        if delivery_mode == 'observation_only':
            # Observation has no write claim to define a point of no return;
            # local selected values and manual/source guards must therefore
            # remain exact on both sides of every remote read.
            self._revalidate_exact_rows(exact_plan)
            try:
                delivery_evidence = json.loads(delivery[3])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    'Exact Sheets observation evidence is invalid.') from error
            from .exact_legacy_migration import validate_legacy_delivery_evidence
            validate_legacy_delivery_evidence(
                self.local, exact_plan['operations'], delivery_evidence)
        return exact_plan

    def confirm_exact_scope(self, *, inbox, cycle_id, company_id,
                            plan_digest, receipt_id, intent_id,
                            post_observation_read_guard=None):
        """Read back the complete scope and durably confirm it as one operation."""
        # These are ordinary exact-cycle APIs.  A retained publication needs a
        # distinct reservation-bound confirmer; otherwise a caller could use
        # this public path to consume its dirty cells or receipt evidence.
        self._refuse_retained_publication_hold()
        exact_plan = self._durable_exact_plan(
            inbox, cycle_id=cycle_id, company_id=company_id,
            plan_digest=plan_digest, receipt_id=receipt_id,
            intent_id=intent_id)
        remote_state = inbox.exact_remote_state(cycle_id, company_id)
        if (not isinstance(remote_state, Mapping)
                or remote_state.get('local_plan_digest') != plan_digest
                or remote_state.get('projection_digest') != exact_plan['projection_digest']
                or remote_state.get('receipt_id') != receipt_id
                or remote_state.get('intent_id') != intent_id
                or remote_state.get('remote_cursor') != len(exact_plan['operations'])):
            raise ValueError('Exact Sheets complete remote journal is unavailable.')
        return self._readback_and_confirm_full(
            inbox=inbox, cycle_id=cycle_id, company_id=company_id,
            plan_digest=plan_digest, receipt_id=receipt_id,
            intent_id=intent_id,
            post_observation_read_guard=post_observation_read_guard)

    def confirm_and_acknowledge_exact_scope(self, *, inbox, cycle_id,
                                            company_id, plan_digest, receipt_id,
                                            intent_id,
                                            post_observation_read_guard=None):
        """Fresh-read, durably confirm, then acknowledge only the exact scope."""
        self._refuse_retained_publication_hold()
        return self._acknowledge_exact_readback(
            inbox=inbox, cycle_id=cycle_id, company_id=company_id,
            plan_digest=plan_digest, receipt_id=receipt_id,
            intent_id=intent_id,
            post_observation_read_guard=post_observation_read_guard)

    def _acknowledge_exact_readback(self, *, inbox, cycle_id, company_id,
                                    plan_digest, receipt_id, intent_id,
                                    post_observation_read_guard=None):
        """Fresh-read and consume only canonical durable exact evidence."""
        exact_plan = self._durable_exact_plan(
            inbox, cycle_id=cycle_id, company_id=company_id,
            plan_digest=plan_digest, receipt_id=receipt_id,
            intent_id=intent_id)
        readback = self._readback_and_confirm_full(
            inbox=inbox, cycle_id=cycle_id, company_id=company_id,
            plan_digest=plan_digest, receipt_id=receipt_id,
            intent_id=intent_id,
            post_observation_read_guard=post_observation_read_guard)
        acknowledgement_id = readback['acknowledgement_id']
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
                        'apply_id': apply_id, 'acknowledgement_id': acknowledgement_id,
                        'readback': readback}
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
                'apply_id': apply_id, 'acknowledgement_id': acknowledgement_id,
                'readback': readback}

    def publish_batch(self, limit=None, *, row_scope=None, guards=()):
        """Grow successful small-payload batches, retaining the encoded byte cap.

        Scoped review calls keep their caller's row bound. Only an explicitly
        typed pre-write size rejection can be retried here; ambiguous writes
        retain their durable receipts and propagate for keyed reconciliation.
        """
        adaptive = limit is None and row_scope is None
        selected_limit = self._publish_limit if adaptive else (500 if limit is None else limit)
        guards = tuple(guards)
        started = time.monotonic()
        while True:
            try:
                result = self._publish_batch(selected_limit, row_scope=row_scope, guards=guards)
                break
            except BatchPayloadTooLarge:
                if not adaptive or selected_limit <= 1:
                    raise
                selected_limit = max(1, selected_limit // 2)
                self._publish_limit = selected_limit
        if adaptive:
            elapsed = time.monotonic() - started
            if elapsed > 45:
                self._publish_limit = max(1, selected_limit // 2)
            elif result.get('published_rows', 0) >= selected_limit and elapsed < 30:
                self._publish_limit = min(2000, selected_limit * 2)
        return result

    def _publish_batch(self, limit, *, row_scope=None, guards=()):
        """Publish queued fields, optionally restricted to explicit local rows/fields."""
        self._refuse_retained_publication_hold()
        plans = self._operations(limit, row_scope=row_scope)
        if not plans:
            return {'published_rows': 0}
        operations = [*guards, *(p[4] for p in plans)]
        guarded_companies = {}
        if row_scope is None:
            for tab, rid, fields, sent, op in plans:
                owner = self._company_context(tab, rid, sent)
                if owner is None or owner[2] is None:
                    continue
                company_id, company, base = owner
                if company_id in guarded_companies:
                    continue
                identity = identity_for('Companies', base)
                expected = {h: base.get(h, '') for h in COMPANY_CONTROLS
                            if h in self.remote.schemas['Companies']}
                guard = {'tab': 'Companies', 'identity': identity, 'values': {}, 'expected': expected}
                guarded_companies[company_id] = guard
            operations = [*guarded_companies.values(), *operations]
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
        # Record attempted values before sending, so a later pull can distinguish
        # a lost acknowledgement from an unrelated manual choice matching an AI result.
        with self.local.transaction():
            for tab, rid, fields, sent, op in plans:
                attempted = {h: sent.get(h, '') for h in fields}
                self.local.db.execute('INSERT INTO delivery_attempts VALUES (?,?,?) ON CONFLICT(tab,row_id) DO UPDATE SET data=excluded.data',
                                      (tab, rid, encode(attempted)))
        try:
            self._refuse_retained_publication_hold()
            result = self.remote.commit(operations)
        except BatchPayloadTooLarge:
            # Encoding failed before any network write. These are not lost
            # acknowledgements and must not later be mistaken for our own echo.
            with self.local.transaction():
                for tab, rid, _, _, _ in plans:
                    self.local.db.execute('DELETE FROM delivery_attempts WHERE tab=? AND row_id=?', (tab, rid))
            raise
        except ReviewFieldsChangedError:
            # The rejection happened before submission. An attempted No/Yes
            # therefore cannot establish that a Sheet value is our own echo.
            # Discard these receipts so the fresh pull protects manual choices,
            # even when the user's selection happens to match our planned value.
            with self.local.transaction():
                for tab, rid, _, _, _ in plans:
                    self.local.db.execute('DELETE FROM delivery_attempts WHERE tab=? AND row_id=?', (tab, rid))
            raise
        except MissingIdentityError as error:
            # An existing company can be removed while a long scrape is still
            # running. A typed pre-write failure proves no batch was submitted.
            # Preserve and pause that record instead of reinserting it or
            # retrying the same invalid identity forever. Exact scoped review
            # publication retains its existing failure/reconciliation behavior.
            missing_ids = {p[1] for p in plans if p[0] == 'Companies'
                           and p[4]['identity'] == error.identity and not p[4]['append_if_missing']}
            missing_ids.update(rid for rid, guard in guarded_companies.items() if guard['identity'] == error.identity)
            with self.local.transaction():
                for tab, rid, _, _, _ in plans:
                    self.local.db.execute('DELETE FROM delivery_attempts WHERE tab=? AND row_id=?', (tab, rid))
            if error.tab != 'Companies' or not missing_ids or row_scope is not None or guards:
                raise
            with self.local.transaction():
                for rid in missing_ids:
                    tab = 'Companies'
                    self.local.conflict(tab, rid, '__missing__',
                        'Previously synchronized row is missing remotely; it will not be reinserted automatically.')
                    current = self.local.row(tab, rid)
                    current['Company Status'] = 'Paused'
                    self.local._put(tab, rid, current)
                    self.local.event('remote_missing_company', tab, rid, {'identity': error.identity})
            return {'published_rows': 0, 'held_missing_rows': len(missing_ids)}
        except PreflightWriteError:
            # Formula/schema/identity validation and failed prerequisite reads
            # prove no write was sent, just like changed review-field guards.
            with self.local.transaction():
                for tab, rid, _, _, _ in plans:
                    self.local.db.execute('DELETE FROM delivery_attempts WHERE tab=? AND row_id=?', (tab, rid))
            raise
        except Exception:
            # A timeout may follow a successful remote write. Do not clear any
            # delivery state; the same identities/values are safe to reconcile.
            raise
        committed = dict(getattr(self.remote, '_committed_rows', {}))
        committed_indexes = {tab: IdentityIndex(enumerate(rows)) for tab, rows in committed.items()}
        # A replay may be a no-op and return no touched rows. Resolve by stable
        # identity, then read back only missing rows, outside the local lock.
        def find_actual(tab, sent):
            target = identity_for(tab, sent)
            index = committed_indexes.get(tab)
            matches = index.matches(target) if index is not None else []
            if len(matches) > 1:
                raise RepositoryError(f'{tab}: ambiguous publication acknowledgement.')
            return matches[0][1] if matches else None
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
                committed_indexes.setdefault(tab, IdentityIndex(())).put(len(committed[tab]) - 1, row)
        published = 0
        with self.local.transaction():
            for tab, rid, fields, sent, op in plans:
                base = self.local.baseline(tab, rid) or {}
                current = self.local.row(tab, rid)
                # A repository review lock can skip a row without failing the batch.
                actual = find_actual(tab, sent)
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
