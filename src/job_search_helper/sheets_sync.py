"""Explicit field-level, three-way synchronization. Never replace a whole tab.

Network calls occur outside SQLite transactions. Dirty fields remain queued
until acknowledged, and a newer local edit cannot be cleared by an older ack.
Sheets has no conditional cell-write transaction: structural edits during a
publish are unsupported. Use filter views instead of physically sorting rows.
"""
from __future__ import annotations

from collections import defaultdict
import json
import time

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
        for row in self.local.read('Companies'):
            if row.get('Company') and not row.get('Company ID'):
                engine._assign_company_id(row)
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
