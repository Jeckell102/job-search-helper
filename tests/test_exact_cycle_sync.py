"""Offline proof for the selected-plan publisher; no Google or global sync."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from job_search_helper.exact_cycle_sync import (publish_exact_cycle as _publish_exact_cycle, _chunk_digest,
                                                 _digest, _fallback_receipt, _readback)
from job_search_helper.publication_receipts import record_fingerprints
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.publication_receipts import SYNC_CONFIRMED, SYNC_PENDING
from job_search_helper.repository import MemoryRepository, SCHEMAS, UncertainWriteError
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.exact_cycle_receipt import derive_receipt
from job_search_helper.exact_cycle_planner import _receipt as planner_receipt
from job_search_helper.exact_recovery_terminal import _expected_receipt as terminal_receipt


def job(key, **changes):
    row = {
        'Job Key': key, 'Company': 'Acme', 'Job Title': 'Product Manager',
        'Official Job URL': 'https://jobs.example.test/' + key,
        'Source Hash': 'source-' + key, 'Added to Opportunities?': 'Pending',
        'Review Status': 'Needs Review', 'Job Status': 'Open and verified',
        'Location': 'Ohio', 'Last Checked': 'before',
    }
    row.update(changes)
    return row


CAREERS_URL = 'https://jobs.example.test/acme'
PAYLOAD = {'jobs': [], 'fetched_at': '2026-11-19T00:00:00Z'}


def sealed_plan(operations, final=None, payload=None, company_id='COMP-EXACT', *,
                profile='full', schemas=SCHEMAS):
    payload = payload or PAYLOAD
    evidence = {
        'company_id': company_id, 'requested_url': CAREERS_URL,
        'official_careers_url': CAREERS_URL, 'company_status': 'Active',
        'claimed_by': '', 'claim_token': '',
    }
    result = {
        'operations': operations, 'final': final or {'stage': 'complete'},
        'requested_url': CAREERS_URL, 'control_evidence': evidence,
        'control_evidence_version': 1, 'control_evidence_digest': _digest(evidence),
        'inventory_payload_digest': _digest(payload),
        'plan_records_digest': _digest(record_fingerprints(operations)),
    }
    schema_evidence = {tab: list(headers) for tab, headers in sorted(schemas.items())}
    result.update({
        'publication_projection_version': 1,
        'publication_profile': profile,
        'publication_schema_digest': _digest(schema_evidence),
        'local_operations_digest': _digest(operations),
        'local_finalization_digest': _digest({
            'operations': operations, 'final': result['final'],
        }),
        'remote_operations_digest': _digest(operations),
    })
    result['remote_projection_digest'] = _digest({
        'profile': profile,
        'schema_digest': result['publication_schema_digest'],
        'operations': operations,
    })
    result['final_projection'] = {key: result['final'][key] for key in sorted(result['final'])}
    result['final_projection_digest'] = _digest(result['final_projection'])
    result['plan_digest'] = _digest({key: result.get(key) for key in (
        'operations', 'final', 'requested_url', 'control_evidence',
        'control_evidence_version', 'control_evidence_digest',
        'inventory_payload_digest', 'plan_records_digest',
        'final_projection', 'final_projection_digest',
        'publication_projection_version', 'publication_profile',
        'publication_schema_digest', 'local_operations_digest',
        'local_finalization_digest', 'remote_operations_digest',
        'remote_projection_digest',
    )})
    return result


def plan(key, value):
    return sealed_plan([{
        'tab': 'Job History', 'identity': {'Job Key': key},
        'expected': {'Last Checked': 'before'}, 'values': {'Last Checked': value},
    }])


def cycle_state(cycle, company='COMP-EXACT'):
    return {'id': cycle, 'started_at': '2026-11-19T00:00:00+00:00',
            'status': 'In Progress', 'companies': {company: {
                'stage': 'inventory', 'durable_inventory': True, 'locally_processed': True,
            }}}


def publish_exact_cycle(inbox, cycle_id, remote, *, state, **kwargs):
    """Default fixture selection is explicit, matching production API use."""
    kwargs.setdefault('company_ids', list(state.cycle(cycle_id)['companies']))
    kwargs.setdefault('company_guard', remote.company_guard)
    return _publish_exact_cycle(inbox, cycle_id, remote, state=state, **kwargs)


class RecordingRemote(MemoryRepository):
    def __init__(self, rows, *, tab='Job History', schemas=None, companies=None,
                 local_companies=None):
        if companies is None:
            companies = [{'Company ID': 'COMP-EXACT', 'Company': 'Acme',
                          'Company Status': 'Active', 'Official Careers URL': CAREERS_URL}]
        super().__init__({
            tab: rows,
            'Companies': companies,
        }, schemas=schemas)
        if local_companies is None:
            local_companies = companies
        self.local = MemoryRepository({'Companies': local_companies}, schemas=SCHEMAS)
        self.commits = []

    def company_guard(self, company_id, requested_url):
        from job_search_helper.exact_cycle_sync import _company_guard
        return _company_guard(self.local, self, company_id, requested_url)

    def commit(self, operations):
        self.commits.append(operations)
        return super().commit(operations)


class UncertainRemote(RecordingRemote):
    def commit(self, operations):
        self.commits.append(operations)
        raise UncertainWriteError('simulated lost acknowledgement')


class SelectedReadOnlyRemote(RecordingRemote):
    def read(self, tab):
        raise AssertionError('whole-tab read is forbidden')

    def read_many(self, tabs):
        raise AssertionError('whole-workbook read is forbidden')


class FailingSaveState:
    """A crash/failure boundary after remote confirmation but before delete."""
    def __init__(self, wrapped):
        self.wrapped = wrapped

    def cycle(self, cycle_id):
        return self.wrapped.cycle(cycle_id)

    def save_cycle(self, cycle):
        raise OSError('simulated local checkpoint failure')


class FirstSaveFailsState:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.calls = 0

    def cycle(self, cycle_id):
        return self.wrapped.cycle(cycle_id)

    def save_cycle(self, cycle):
        self.calls += 1
        if self.calls == 1:
            raise OSError('first final checkpoint failed')
        return self.wrapped.save_cycle(cycle)


class ExactCyclePublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.inbox = InventoryInbox(Path(self.temp.name) / 'inventories.sqlite3', 'fixture')
        self.addCleanup(self.inbox.close)
        self.state = State(Path(self.temp.name) / 'state.db')
        self.addCleanup(self.state.close)

    def add_plan(self, cycle, company, key, value):
        current = self.state.cycle(cycle) or {
            'id': cycle, 'started_at': '2026-11-19T00:00:00+00:00',
            'status': 'In Progress', 'companies': {},
        }
        current['companies'].setdefault(company, {
            'stage': 'inventory', 'durable_inventory': True, 'locally_processed': True,
        })
        self.state.save_cycle(current)
        self.inbox.save(cycle, company, dict(PAYLOAD))
        self.save_applied_plan(cycle, company, plan(key, value))

    def save_applied_plan(self, cycle, company, frozen):
        """Model a plan whose full local operation stream is durable."""
        self.inbox.save_plan(cycle, company, frozen)
        self.inbox.advance(cycle, {company: len(frozen['operations'])},
                           expected={company: 0})

    def receipt_count(self):
        return self.inbox.connection.execute(
            'SELECT count(*) FROM publication_receipts'
        ).fetchone()[0]

    def test_compact_profile_holds_until_local_commit_journal_exists(self):
        schemas = {tab: list(headers) for tab, headers in COMPACT_SCHEMAS.items()}
        frozen = sealed_plan(
            plan('job-exact', 'after-exact')['operations'],
            profile=COMPACT_PROFILE, schemas=schemas,
        )
        self.inbox.save('CYC-COMPACT', 'COMP-EXACT', dict(PAYLOAD))
        self.save_applied_plan('CYC-COMPACT', 'COMP-EXACT', frozen)
        self.state.save_cycle(cycle_state('CYC-COMPACT'))
        compact_job = {key: value for key, value in job('job-exact').items()
                       if key in schemas['Job History']}
        remote_company = {'Company ID': 'COMP-EXACT', 'Company': 'Acme',
                          'Company Status': 'Active', 'Official Careers URL': CAREERS_URL}
        local_company = dict(remote_company, **{
            'Claimed By': '', 'Claim Token': '', 'Scan State': 'Queued',
            'Automatic Retry?': 'Yes',
        })
        remote = RecordingRemote([compact_job], schemas=schemas,
                                 companies=[remote_company], local_companies=[local_company])

        report = publish_exact_cycle(self.inbox, 'CYC-COMPACT', remote, state=self.state)

        self.assertEqual(report['held'], [{
            'company_id': 'COMP-EXACT',
            'reason': 'non_full_plan_requires_durable_local_commit_journal',
        }])
        self.assertEqual(remote.commits, [])
        self.assertEqual(self.receipt_count(), 0)

    def test_missing_trusted_local_guard_fails_closed_before_receipt_or_remote_access(self):
        self.add_plan('CYC-NO-GUARD', 'COMP-EXACT', 'job-exact', 'after-exact')
        remote = RecordingRemote([job('job-exact')])
        before = self.receipt_count()

        with self.assertRaisesRegex(ValueError, 'trusted local Company controls'):
            _publish_exact_cycle(self.inbox, 'CYC-NO-GUARD', remote,
                                 company_ids=['COMP-EXACT'], state=self.state)

        self.assertEqual(self.receipt_count(), before)
        self.assertEqual(remote.commits, [])

    def test_projection_seal_fields_fail_closed_before_controls_receipts_or_remote(self):
        cases = (
            ('version', lambda frozen: frozen.__setitem__(
                'publication_projection_version', 2),
             'publication_projection_version_invalid'),
            ('profile', lambda frozen: frozen.__setitem__(
                'publication_profile', 'future-v9'),
             'publication_profile_invalid'),
            ('schema', lambda frozen: frozen.__setitem__(
                'publication_schema_digest', 'changed'),
             'publication_schema_digest_invalid'),
            ('local-operations', lambda frozen: frozen.__setitem__(
                'local_operations_digest', 'changed'),
             'local_operations_digest_invalid'),
            ('local-finalization', lambda frozen: frozen.__setitem__(
                'local_finalization_digest', 'changed'),
             'local_finalization_digest_invalid'),
            ('remote-operations', lambda frozen: frozen.__setitem__(
                'remote_operations_digest', 'changed'),
             'remote_operations_digest_invalid'),
            ('remote-projection', lambda frozen: frozen.__setitem__(
                'remote_projection_digest', 'changed'),
             'remote_projection_digest_invalid'),
        )
        for number, (label, mutate, reason) in enumerate(cases):
            with self.subTest(label=label):
                cycle = f'CYC-SEAL-{number}'
                frozen = plan(f'job-seal-{number}', 'after')
                mutate(frozen)
                self.inbox.save(cycle, 'COMP-EXACT', dict(PAYLOAD))
                self.save_applied_plan(cycle, 'COMP-EXACT', frozen)
                self.state.save_cycle(cycle_state(cycle))
                remote = RecordingRemote([job(f'job-seal-{number}')])
                guard = MagicMock(side_effect=AssertionError('control guard must not run'))
                receipts_before = self.receipt_count()

                report = _publish_exact_cycle(
                    self.inbox, cycle, remote, company_ids=['COMP-EXACT'],
                    state=self.state, company_guard=guard,
                )

                self.assertEqual(report['held'], [{
                    'company_id': 'COMP-EXACT', 'reason': reason,
                }])
                guard.assert_not_called()
                self.assertEqual(remote.commits, [])
                self.assertEqual(self.receipt_count(), receipts_before)

    def test_current_remote_schema_must_match_the_full_plan_seal(self):
        cycle = 'CYC-SCHEMA-DRIFT'
        frozen = plan('job-schema-drift', 'after')
        self.inbox.save(cycle, 'COMP-EXACT', dict(PAYLOAD))
        self.save_applied_plan(cycle, 'COMP-EXACT', frozen)
        self.state.save_cycle(cycle_state(cycle))
        changed_schemas = {tab: list(headers) for tab, headers in SCHEMAS.items()}
        changed_schemas['Job History'] = changed_schemas['Job History'][:-1]
        remote = RecordingRemote([job('job-schema-drift')], schemas=changed_schemas)
        guard = MagicMock(side_effect=AssertionError('control guard must not run'))

        report = _publish_exact_cycle(
            self.inbox, cycle, remote, company_ids=['COMP-EXACT'],
            state=self.state, company_guard=guard,
        )

        self.assertEqual(report['held'], [{
            'company_id': 'COMP-EXACT', 'reason': 'publication_schema_digest_invalid',
        }])
        guard.assert_not_called()
        self.assertEqual(remote.commits, [])

    def test_local_claim_change_after_planning_holds_without_commit_or_receipt(self):
        self.add_plan('CYC-LOCAL-CLAIM', 'COMP-EXACT', 'job-exact', 'after-exact')
        remote = RecordingRemote([job('job-exact')])
        remote.local.commit([{
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-EXACT'},
            'values': {'Claimed By': 'another-worker', 'Claim Token': 'new-claim'},
        }])
        before = self.receipt_count()

        report = publish_exact_cycle(self.inbox, 'CYC-LOCAL-CLAIM', remote, state=self.state)

        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT',
                                           'reason': 'local_company_claimed'}])
        self.assertEqual(remote.commits, [])
        self.assertEqual(self.receipt_count(), before)

    def test_local_manual_hold_after_planning_holds_without_commit_or_receipt(self):
        self.add_plan('CYC-LOCAL-HOLD', 'COMP-EXACT', 'job-exact', 'after-exact')
        remote = RecordingRemote([job('job-exact')])
        remote.local.commit([{
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-EXACT'},
            'values': {'Automatic Retry?': 'No', 'Scan State': 'Blocked / Manual Review'},
        }])
        before = self.receipt_count()

        report = publish_exact_cycle(self.inbox, 'CYC-LOCAL-HOLD', remote, state=self.state)

        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT',
                                           'reason': 'local_company_manual_hold'}])
        self.assertEqual(remote.commits, [])
        self.assertEqual(self.receipt_count(), before)

    def test_local_status_or_url_change_after_planning_holds_without_commit_or_receipt(self):
        baseline = {'Company ID': 'COMP-EXACT', 'Company': 'Acme',
                    'Company Status': 'Active', 'Official Careers URL': CAREERS_URL}
        cases = (
            (dict(baseline, **{'Company Status': 'Paused'}), 'local_company_not_active'),
            (dict(baseline, **{'Official Careers URL': CAREERS_URL + '/changed'}),
             'local_company_board_changed'),
        )
        for number, (changed, reason) in enumerate(cases):
            with self.subTest(reason=reason):
                cycle = f'CYC-LOCAL-DRIFT-{number}'
                self.add_plan(cycle, 'COMP-EXACT', f'job-local-{number}', 'after')
                remote = RecordingRemote([job(f'job-local-{number}')], companies=[changed],
                                         local_companies=[changed])
                before = self.receipt_count()

                report = publish_exact_cycle(self.inbox, cycle, remote, state=self.state)

                self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT',
                                                   'reason': reason}])
                self.assertEqual(remote.commits, [])
                self.assertEqual(self.receipt_count(), before)

    def test_local_remote_status_or_url_drift_holds_without_commit_or_receipt(self):
        baseline = {'Company ID': 'COMP-EXACT', 'Company': 'Acme',
                    'Company Status': 'Active', 'Official Careers URL': CAREERS_URL}
        cases = (
            dict(baseline, **{'Company Status': 'Paused'}),
            dict(baseline, **{'Official Careers URL': CAREERS_URL + '/changed'}),
        )
        for number, remote_company in enumerate(cases):
            with self.subTest(remote_company=remote_company):
                cycle = f'CYC-REMOTE-DRIFT-{number}'
                self.add_plan(cycle, 'COMP-EXACT', f'job-{number}', 'after')
                remote = RecordingRemote([job(f'job-{number}')], companies=[remote_company],
                                         local_companies=[baseline])
                before = self.receipt_count()

                report = publish_exact_cycle(self.inbox, cycle, remote, state=self.state)

                self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT',
                    'reason': 'local_remote_company_controls_changed'}])
                self.assertEqual(remote.commits, [])
                self.assertEqual(self.receipt_count(), before)

    def test_missing_or_ambiguous_company_holds_without_commit_or_receipt(self):
        baseline = {'Company ID': 'COMP-EXACT', 'Company': 'Acme',
                    'Company Status': 'Active', 'Official Careers URL': CAREERS_URL}
        cases = (
            ([], [baseline]),
            ([baseline], [baseline, dict(baseline)]),
            ([baseline, dict(baseline)], [baseline]),
        )
        for number, (remote_companies, local_companies) in enumerate(cases):
            with self.subTest(number=number):
                cycle = f'CYC-COMPANY-IDENTITY-{number}'
                self.add_plan(cycle, 'COMP-EXACT', f'job-id-{number}', 'after')
                remote = RecordingRemote([job(f'job-id-{number}')],
                                         companies=remote_companies,
                                         local_companies=local_companies)
                before = self.receipt_count()

                report = publish_exact_cycle(self.inbox, cycle, remote, state=self.state)

                self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT',
                                                   'reason': 'company_missing_or_ambiguous'}])
                self.assertEqual(remote.commits, [])
                self.assertEqual(self.receipt_count(), before)

    def test_selected_plan_commits_and_confirms_only_after_exact_readback(self):
        self.add_plan('CYC-EXACT', 'COMP-EXACT', 'job-exact', 'after-exact')
        self.add_plan('CYC-OTHER', 'COMP-OTHER', 'job-other', 'after-other')
        remote = RecordingRemote([job('job-exact'), job('job-other')])
        other_before = self.inbox.get('CYC-OTHER', 'COMP-OTHER'), self.inbox.plan('CYC-OTHER', 'COMP-OTHER')

        report = publish_exact_cycle(self.inbox, 'CYC-EXACT', remote, state=self.state)

        self.assertEqual(report, {'cycle_id': 'CYC-EXACT', 'confirmed': ['COMP-EXACT'], 'held': [], 'skipped': []})
        self.assertEqual(remote.read('Job History')[0]['Last Checked'], 'after-exact')
        self.assertEqual(remote.read('Job History')[1]['Last Checked'], 'before')
        self.assertEqual(len(remote.commits), 1)
        self.assertEqual(remote.commits[0], plan('job-exact', 'after-exact')['operations'])
        self.assertEqual(self.inbox.pending('CYC-EXACT', include_blocked=True), [])
        self.assertEqual((self.inbox.get('CYC-OTHER', 'COMP-OTHER'),
                          self.inbox.plan('CYC-OTHER', 'COMP-OTHER')), other_before)

    def test_uncertain_ack_keeps_frozen_plan_and_pending_receipt(self):
        self.add_plan('CYC-EXACT', 'COMP-EXACT', 'job-exact', 'after-exact')
        remote = UncertainRemote([job('job-exact')])

        report = publish_exact_cycle(self.inbox, 'CYC-EXACT', remote, state=self.state)

        self.assertEqual(report['confirmed'], [])
        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT', 'reason': 'uncertain_write'}])
        self.assertEqual(self.inbox.pending('CYC-EXACT', include_blocked=True), ['COMP-EXACT'])
        frozen, cursor = self.inbox.plan('CYC-EXACT', 'COMP-EXACT')
        self.assertEqual(frozen, plan('job-exact', 'after-exact'))
        self.assertEqual(cursor, 1)
        receipt = self.inbox.find_receipt('COMP-EXACT',
                                          __import__('job_search_helper.publication_receipts', fromlist=['record_fingerprints'])
                                          .record_fingerprints(frozen['operations']))
        self.assertEqual(self.inbox.receipt({'binding': receipt['binding']})['state'], SYNC_PENDING)

    def test_existing_pending_receipt_never_replays_when_readback_is_not_exact(self):
        self.add_plan('CYC-EXACT', 'COMP-EXACT', 'job-exact', 'after-exact')
        remote = RecordingRemote([job('job-exact', **{'Last Checked': 'manual-change'})])
        # First attempt records SYNC_PENDING but the expected-value guard has
        # not been sent. A later named recovery reads back and holds, never
        # overwrites the manual value.
        frozen, _ = self.inbox.plan('CYC-EXACT', 'COMP-EXACT')
        from job_search_helper.exact_cycle_sync import _fallback_receipt
        receipt = _fallback_receipt(self.state.cycle('CYC-EXACT'), 'COMP-EXACT', frozen,
                                    self.inbox.get('CYC-EXACT', 'COMP-EXACT')[0])
        self.inbox.ensure_receipt(receipt)
        self.inbox.mark_receipt_pending(receipt, timestamp='2026-11-19T00:00:01Z')

        report = publish_exact_cycle(self.inbox, 'CYC-EXACT', remote, state=self.state)

        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT', 'reason': 'pending_readback_mismatch'}])
        self.assertEqual(remote.commits, [])
        self.assertEqual(remote.read('Job History')[0]['Last Checked'], 'manual-change')
        self.assertEqual(self.inbox.plan('CYC-EXACT', 'COMP-EXACT')[1], 1)

    def test_compact_opportunity_id_is_the_exact_remote_identity(self):
        schemas = {tab: list(headers) for tab, headers in SCHEMAS.items()}
        schemas['Opportunities'].append('Opportunity ID')
        opportunity = {
            'Opportunity ID': 'OPP-EXACT', 'Company': 'Acme', 'Job Title': 'Product Manager',
            'Job URL': 'https://jobs.example.test/opportunity', 'Salary / Range': '',
        }
        frozen = sealed_plan([{
                'tab': 'Opportunities', 'identity': {'Opportunity ID': 'OPP-EXACT'},
                'expected': {'Salary / Range': ''}, 'values': {'Salary / Range': '$120,000-$140,000'},
            }], schemas=schemas)
        self.inbox.save('CYC-EXACT', 'COMP-EXACT', {'jobs': [], 'fetched_at': '2026-11-19T00:00:00Z'})
        self.state.save_cycle(cycle_state('CYC-EXACT'))
        self.save_applied_plan('CYC-EXACT', 'COMP-EXACT', frozen)
        remote = RecordingRemote([opportunity], tab='Opportunities', schemas=schemas)

        report = publish_exact_cycle(self.inbox, 'CYC-EXACT', remote, state=self.state)

        self.assertEqual(report['confirmed'], ['COMP-EXACT'])
        self.assertEqual(remote.commits[0][0]['identity'], {'Opportunity ID': 'OPP-EXACT'})
        self.assertEqual(remote.read('Opportunities')[0]['Salary / Range'], '$120,000-$140,000')

    def test_multi_chunk_plan_advances_checkpoint_before_inbox_delete(self):
        operations = [plan(f'job-{number}', f'after-{number}')['operations'][0]
                      for number in range(101)]
        frozen = sealed_plan(operations)
        self.inbox.save('CYC-EXACT', 'COMP-EXACT', {'jobs': [], 'fetched_at': '2026-11-19T00:00:00Z'})
        self.save_applied_plan('CYC-EXACT', 'COMP-EXACT', frozen)
        self.state.save_cycle(cycle_state('CYC-EXACT'))
        remote = RecordingRemote([job(f'job-{number}') for number in range(101)])

        report = publish_exact_cycle(self.inbox, 'CYC-EXACT', remote, state=self.state)

        self.assertEqual(report['confirmed'], ['COMP-EXACT'])
        self.assertEqual([len(chunk) for chunk in remote.commits], [100, 1])
        self.assertEqual(self.state.cycle('CYC-EXACT')['companies']['COMP-EXACT']['stage'], 'complete')
        self.assertEqual(self.inbox.pending('CYC-EXACT', include_blocked=True), [])

    def test_blocked_inventory_is_excluded_without_remote_or_receipt_work(self):
        self.add_plan('CYC-EXACT', 'COMP-EXACT', 'job-exact', 'after-exact')
        self.inbox.block('CYC-EXACT', 'COMP-EXACT')
        remote = RecordingRemote([job('job-exact')])

        report = publish_exact_cycle(self.inbox, 'CYC-EXACT', remote, state=self.state)

        self.assertEqual(report['confirmed'], [])
        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT', 'reason': 'durable_inventory_blocked'}])
        self.assertEqual(report['skipped'], [])
        self.assertEqual(remote.commits, [])
        self.assertEqual(self.inbox.pending('CYC-EXACT', include_blocked=True), ['COMP-EXACT'])

    def test_unplanned_inventory_is_reported_but_never_published(self):
        self.inbox.save('CYC-UNPLANNED', 'COMP-EXACT', {'jobs': [], 'fetched_at': '2026-11-19T00:00:00Z'})
        self.state.save_cycle(cycle_state('CYC-UNPLANNED'))
        remote = RecordingRemote([job('job-exact')])

        report = publish_exact_cycle(self.inbox, 'CYC-UNPLANNED', remote, state=self.state)

        self.assertEqual(report['skipped'], [{'company_id': 'COMP-EXACT', 'reason': 'no_frozen_plan'}])
        self.assertEqual(remote.commits, [])
        self.assertEqual(self.inbox.pending('CYC-UNPLANNED', include_blocked=True), ['COMP-EXACT'])

    def test_duplicate_identity_plan_is_held_before_remote_access(self):
        operation = plan('job-exact', 'after-exact')['operations'][0]
        duplicate = sealed_plan([operation, dict(operation)])
        self.inbox.save('CYC-EXACT', 'COMP-EXACT', {'jobs': [], 'fetched_at': '2026-11-19T00:00:00Z'})
        self.save_applied_plan('CYC-EXACT', 'COMP-EXACT', duplicate)
        self.state.save_cycle(cycle_state('CYC-EXACT'))
        remote = RecordingRemote([job('job-exact')])

        report = publish_exact_cycle(self.inbox, 'CYC-EXACT', remote, state=self.state)

        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT',
                                           'reason': 'duplicate_identity_without_atomic_group'}])
        self.assertEqual(remote.commits, [])

    def test_readback_uses_only_selected_columns_and_rows(self):
        operation = plan('job-exact', 'after-exact')['operations']
        remote = SelectedReadOnlyRemote([job('job-exact', **{'Last Checked': 'after-exact'})])

        self.assertEqual(_readback(remote, operation), record_fingerprints(operation))

    def test_noncomplete_final_is_checkpointed_and_blocked_not_acknowledged(self):
        self.add_plan('CYC-EXACT', 'COMP-EXACT', 'job-exact', 'after-exact')
        frozen, _ = self.inbox.plan('CYC-EXACT', 'COMP-EXACT')
        frozen = sealed_plan(frozen['operations'], {'stage': 'blocked'})
        self.inbox.discard_plan('CYC-EXACT', 'COMP-EXACT')
        self.save_applied_plan('CYC-EXACT', 'COMP-EXACT', frozen)
        remote = RecordingRemote([job('job-exact')])

        report = publish_exact_cycle(self.inbox, 'CYC-EXACT', remote, state=self.state)

        self.assertEqual(report['confirmed'], ['COMP-EXACT'])
        self.assertEqual(self.state.cycle('CYC-EXACT')['companies']['COMP-EXACT']['stage'], 'blocked')
        self.assertEqual(self.inbox.get('CYC-EXACT', 'COMP-EXACT')[1], True)

    def test_chunk_digest_and_cursor_cas_refuse_changed_recovery_state(self):
        self.add_plan('CYC-EXACT', 'COMP-EXACT', 'job-exact', 'after-exact')
        self.inbox.begin_exact_chunk('CYC-EXACT', 'COMP-EXACT', 0, 1, 'digest-a')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.inbox.begin_exact_chunk('CYC-EXACT', 'COMP-EXACT', 0, 1, 'digest-b')
        with self.assertRaisesRegex(ValueError, 'cursor changed'):
            self.inbox.advance('CYC-EXACT', {'COMP-EXACT': 1}, expected={'COMP-EXACT': 0})

    def test_invalid_cursor_holds_before_receipt_or_remote_access(self):
        self.add_plan('CYC-CURSOR', 'COMP-EXACT', 'job-exact', 'after-exact')
        with self.inbox.connection:
            self.inbox.connection.execute('UPDATE sync_plans SET cursor=-1 WHERE cycle=? AND company=?',
                                          ('CYC-CURSOR', 'COMP-EXACT'))
        remote = RecordingRemote([job('job-exact')])

        report = publish_exact_cycle(self.inbox, 'CYC-CURSOR', remote, state=self.state)

        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT', 'reason': 'invalid_plan_cursor'}])
        self.assertEqual(remote.commits, [])
        self.assertIsNone(self.inbox.find_receipt('COMP-EXACT', record_fingerprints(plan('job-exact', 'after-exact')['operations'])))

    def test_missing_or_changed_control_evidence_holds_prewrite(self):
        self.add_plan('CYC-CONTROL', 'COMP-EXACT', 'job-exact', 'after-exact')
        frozen, _ = self.inbox.plan('CYC-CONTROL', 'COMP-EXACT')
        frozen.pop('control_evidence_version')
        self.inbox.discard_plan('CYC-CONTROL', 'COMP-EXACT')
        self.save_applied_plan('CYC-CONTROL', 'COMP-EXACT', frozen)
        remote = RecordingRemote([job('job-exact')])

        report = publish_exact_cycle(self.inbox, 'CYC-CONTROL', remote, state=self.state)

        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT', 'reason': 'sealed_plan_digest_invalid'}])
        self.assertEqual(remote.commits, [])

    def test_terminal_or_noninventory_checkpoint_holds_even_if_inbox_is_ready(self):
        self.add_plan('CYC-STAGE', 'COMP-EXACT', 'job-exact', 'after-exact')
        checkpoint = self.state.cycle('CYC-STAGE')
        checkpoint['companies']['COMP-EXACT']['stage'] = 'complete'
        self.state.save_cycle(checkpoint)
        before_receipts = self.inbox.connection.execute('SELECT count(*) FROM publication_receipts').fetchone()[0]

        report = publish_exact_cycle(self.inbox, 'CYC-STAGE', RecordingRemote([job('job-exact')]), state=self.state)

        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT', 'reason': 'state_checkpoint_not_recoverable'}])
        self.assertEqual(self.inbox.connection.execute('SELECT count(*) FROM publication_receipts').fetchone()[0],
                         before_receipts)

    def test_final_identity_collision_is_held_before_remote_access(self):
        first = plan('job-a', 'after-a')['operations'][0]
        second = plan('job-b', 'after-b')['operations'][0]
        first['values']['Job Key'] = 'job-final'
        second['values']['Job Key'] = 'job-final'
        self.inbox.save('CYC-FINAL-ID', 'COMP-EXACT', dict(PAYLOAD))
        self.save_applied_plan('CYC-FINAL-ID', 'COMP-EXACT', sealed_plan([first, second]))
        self.state.save_cycle(cycle_state('CYC-FINAL-ID'))
        remote = RecordingRemote([job('job-a'), job('job-b')])

        report = publish_exact_cycle(self.inbox, 'CYC-FINAL-ID', remote, state=self.state)

        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT',
                                           'reason': 'duplicate_identity_without_atomic_group'}])
        self.assertEqual(remote.commits, [])

    def test_wrong_cycle_receipt_is_not_reused_by_matching_record(self):
        self.add_plan('CYC-RECEIPT', 'COMP-EXACT', 'job-exact', 'after-exact')
        frozen, _ = self.inbox.plan('CYC-RECEIPT', 'COMP-EXACT')
        cycle = self.state.cycle('CYC-RECEIPT')
        wrong = _fallback_receipt(cycle, 'COMP-EXACT', frozen, dict(PAYLOAD))
        wrong['binding']['request_id'] = 'CYC-OTHER'
        self.inbox.ensure_receipt(wrong)

        report = publish_exact_cycle(self.inbox, 'CYC-RECEIPT', RecordingRemote([job('job-exact')]), state=self.state)

        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT', 'reason': 'legacy_receipt_binding_mismatch'}])

    def test_failed_first_state_save_cannot_leak_into_second_company_checkpoint(self):
        cycle = 'CYC-TWO'
        for company, key in (('COMP-ONE', 'job-one'), ('COMP-TWO', 'job-two')):
            self.inbox.save(cycle, company, dict(PAYLOAD))
            self.save_applied_plan(cycle, company, sealed_plan(
                plan(key, 'after')['operations'], company_id=company))
        self.state.save_cycle({'id': cycle, 'started_at': '2026-11-19T00:00:00+00:00', 'status': 'In Progress',
                               'companies': {company: {'stage': 'inventory', 'durable_inventory': True,
                                                       'locally_processed': True}
                                             for company in ('COMP-ONE', 'COMP-TWO')}})
        companies = [{'Company ID': company, 'Company Status': 'Active', 'Official Careers URL': CAREERS_URL}
                     for company in ('COMP-ONE', 'COMP-TWO')]
        state = FirstSaveFailsState(self.state)

        report = publish_exact_cycle(self.inbox, cycle,
                                     RecordingRemote([job('job-one'), job('job-two')], companies=companies), state=state)

        self.assertEqual(report['held'], [{'company_id': 'COMP-ONE', 'reason': 'OSError'}])
        self.assertEqual(report['confirmed'], ['COMP-TWO'])
        saved = self.state.cycle(cycle)['companies']
        self.assertEqual(saved['COMP-ONE']['stage'], 'inventory')
        self.assertEqual(saved['COMP-TWO']['stage'], 'complete')
        self.assertIsNotNone(self.inbox.plan(cycle, 'COMP-ONE'))

    def test_explicit_selection_never_inspects_or_mutates_unselected_company(self):
        cycle = 'CYC-SELECTED'
        for company, key in (('COMP-ONE', 'job-one'), ('COMP-TWO', 'job-two')):
            self.inbox.save(cycle, company, dict(PAYLOAD))
            self.save_applied_plan(cycle, company, sealed_plan(
                plan(key, 'after')['operations'], company_id=company))
        self.state.save_cycle({'id': cycle, 'started_at': '2026-11-19T00:00:00+00:00', 'status': 'In Progress',
                               'companies': {company: {'stage': 'inventory', 'durable_inventory': True,
                                                       'locally_processed': True}
                                             for company in ('COMP-ONE', 'COMP-TWO')}})
        remote = RecordingRemote([job('job-one'), job('job-two')], companies=[
            {'Company ID': company, 'Company Status': 'Active', 'Official Careers URL': CAREERS_URL}
            for company in ('COMP-ONE', 'COMP-TWO')])
        other_before = self.inbox.get(cycle, 'COMP-TWO'), self.inbox.plan(cycle, 'COMP-TWO')

        report = _publish_exact_cycle(self.inbox, cycle, remote, company_ids=['COMP-ONE'],
                                      state=self.state, company_guard=remote.company_guard)

        self.assertEqual(report['confirmed'], ['COMP-ONE'])
        self.assertEqual((self.inbox.get(cycle, 'COMP-TWO'), self.inbox.plan(cycle, 'COMP-TWO')), other_before)
        self.assertEqual(self.state.cycle(cycle)['companies']['COMP-TWO']['stage'], 'inventory')
        self.assertEqual([operation['identity']['Job Key'] for operation in remote.commits[0]], ['job-one'])

    def test_invalid_explicit_selections_reject_before_access(self):
        self.add_plan('CYC-SELECTION', 'COMP-EXACT', 'job-exact', 'after-exact')
        remote = RecordingRemote([job('job-exact')])
        for selection in ([], ['COMP-EXACT', 'COMP-EXACT'], ['COMP-%s' % number for number in range(26)]):
            with self.subTest(selection=selection):
                with self.assertRaisesRegex(ValueError, 'selection'):
                    _publish_exact_cycle(self.inbox, 'CYC-SELECTION', remote,
                                         company_ids=selection, state=self.state,
                                         company_guard=remote.company_guard)
        self.assertEqual(remote.commits, [])

    def test_seeded_cursors_validate_prefix_then_publish_only_remaining_tail(self):
        """Retained cursors 1/19/67 never replay their acknowledged prefix."""
        for cursor in (1, 19, 67):
            with self.subTest(cursor=cursor):
                cycle = f'CYC-SEED-{cursor}'
                operations = [plan(f'job-{cursor}-{number}', f'after-{cursor}-{number}')['operations'][0]
                              for number in range(70)]
                self.inbox.save(cycle, 'COMP-EXACT', {'jobs': [], 'fetched_at': '2026-11-19T00:00:00Z'})
                self.save_applied_plan(cycle, 'COMP-EXACT', sealed_plan(operations))
                self.state.save_cycle(cycle_state(cycle))
                remote = RecordingRemote([
                    job(f'job-{cursor}-{number}', **{'Last Checked': f'after-{cursor}-{number}' if number < cursor else 'before'})
                    for number in range(70)])

                report = publish_exact_cycle(self.inbox, cycle, remote, state=self.state)

                self.assertEqual(report['confirmed'], ['COMP-EXACT'])
                self.assertEqual(len(remote.commits), 1)
                self.assertEqual([item['identity']['Job Key'] for item in remote.commits[0]],
                                 [f'job-{cursor}-{number}' for number in range(70)])

    def test_seeded_cursor_prefix_mismatch_holds_before_any_tail_write(self):
        operations = [plan(f'job-{number}', f'after-{number}')['operations'][0]
                      for number in range(20)]
        self.inbox.save('CYC-PREFIX', 'COMP-EXACT', {'jobs': [], 'fetched_at': '2026-11-19T00:00:00Z'})
        self.save_applied_plan('CYC-PREFIX', 'COMP-EXACT', sealed_plan(operations))
        self.state.save_cycle(cycle_state('CYC-PREFIX'))
        remote = RecordingRemote([
            job(f'job-{number}', **{'Last Checked': 'manual-change' if number == 3
                                    else (f'after-{number}' if number < 19 else 'before')})
            for number in range(20)])

        report = publish_exact_cycle(self.inbox, 'CYC-PREFIX', remote, state=self.state)

        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT',
                                           'reason': 'RepositoryError'}])
        self.assertEqual(len(remote.commits), 1)
        self.assertEqual(self.inbox.plan('CYC-PREFIX', 'COMP-EXACT')[1], 20)

    def test_lost_ack_restart_reads_matching_pending_chunk_without_replay(self):
        self.add_plan('CYC-LOST-ACK', 'COMP-EXACT', 'job-exact', 'after-exact')
        frozen, _ = self.inbox.plan('CYC-LOST-ACK', 'COMP-EXACT')
        payload, _ = self.inbox.get('CYC-LOST-ACK', 'COMP-EXACT')
        receipt = _fallback_receipt(self.state.cycle('CYC-LOST-ACK'), 'COMP-EXACT', frozen, payload)
        self.inbox.ensure_receipt(receipt)
        self.inbox.mark_receipt_pending(receipt, timestamp='2026-11-19T00:00:01Z')
        chunk = frozen['operations']
        self.inbox.begin_exact_chunk('CYC-LOST-ACK', 'COMP-EXACT', 0, len(chunk), _chunk_digest(chunk))
        remote = RecordingRemote([job('job-exact', **{'Last Checked': 'after-exact'})])

        report = publish_exact_cycle(self.inbox, 'CYC-LOST-ACK', remote, state=self.state)

        self.assertEqual(report['confirmed'], ['COMP-EXACT'])
        self.assertEqual(remote.commits, [])
        self.assertEqual(self.inbox.pending('CYC-LOST-ACK', include_blocked=True), [])

    def test_local_receipt_with_already_visible_full_plan_confirms_without_replay(self):
        self.add_plan('CYC-LOCAL-VISIBLE', 'COMP-EXACT', 'job-exact', 'after-exact')
        remote = RecordingRemote([job('job-exact', **{'Last Checked': 'after-exact'})])

        report = publish_exact_cycle(self.inbox, 'CYC-LOCAL-VISIBLE', remote, state=self.state)

        self.assertEqual(report['confirmed'], ['COMP-EXACT'])
        self.assertEqual(remote.commits, [])
        self.assertEqual(self.inbox.pending('CYC-LOCAL-VISIBLE', include_blocked=True), [])

    def test_confirmed_receipt_with_stale_cursor_and_changed_remote_holds_without_replay(self):
        self.add_plan('CYC-CONFIRMED-STALE', 'COMP-EXACT', 'job-exact', 'after-exact')
        frozen, _ = self.inbox.plan('CYC-CONFIRMED-STALE', 'COMP-EXACT')
        receipt = _fallback_receipt(self.state.cycle('CYC-CONFIRMED-STALE'), 'COMP-EXACT', frozen, dict(PAYLOAD))
        self.inbox.ensure_receipt(receipt)
        with self.inbox.connection:
            self.inbox.connection.execute('UPDATE publication_receipts SET state=?', (SYNC_CONFIRMED,))
        remote = RecordingRemote([job('job-exact', **{'Last Checked': 'manual-change'})])

        report = publish_exact_cycle(self.inbox, 'CYC-CONFIRMED-STALE', remote, state=self.state)

        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT',
                                           'reason': 'confirmed_receipt_not_at_exact_end'}])
        self.assertEqual(remote.commits, [])
        self.assertIsNotNone(self.inbox.plan('CYC-CONFIRMED-STALE', 'COMP-EXACT'))

    def test_shared_receipt_contract_is_timestamp_independent_for_incomplete_dates(self):
        cycle = {'id': 'CYC-NO-DATES', 'companies': {'COMP-EXACT': {
            'stage': 'inventory', 'durable_inventory': True, 'locally_processed': True,
        }}}
        payload = {'jobs': []}
        frozen = plan('job-exact', 'after-exact')
        shared = derive_receipt(cycle, 'COMP-EXACT', payload, frozen, 'first-stamp')

        self.assertEqual(shared['schedule']['enqueued_at'], 'CYC-NO-DATES')
        self.assertEqual(shared['binding'], planner_receipt(cycle, 'COMP-EXACT', payload, frozen, 'later-stamp')['binding'])
        self.assertEqual(shared['schedule'], terminal_receipt(cycle, 'COMP-EXACT', payload, frozen)['schedule'])

    def test_post_state_save_ack_failure_recovers_without_replay(self):
        self.add_plan('CYC-POST-SAVE', 'COMP-EXACT', 'job-exact', 'after-exact')
        remote = RecordingRemote([job('job-exact')])
        with patch.object(self.inbox, 'acknowledge', side_effect=OSError('simulated cleanup crash')):
            first = publish_exact_cycle(self.inbox, 'CYC-POST-SAVE', remote, state=self.state)
        self.assertEqual(first['held'], [{'company_id': 'COMP-EXACT', 'reason': 'OSError'}])
        self.assertEqual(self.state.cycle('CYC-POST-SAVE')['companies']['COMP-EXACT']['stage'], 'complete')
        self.assertIsNotNone(self.inbox.plan('CYC-POST-SAVE', 'COMP-EXACT'))
        commits = len(remote.commits)

        second = publish_exact_cycle(self.inbox, 'CYC-POST-SAVE', remote, state=self.state)

        self.assertEqual(second['confirmed'], ['COMP-EXACT'])
        self.assertEqual(len(remote.commits), commits)
        self.assertEqual(self.inbox.pending('CYC-POST-SAVE', include_blocked=True), [])

    def test_post_state_save_recovery_refuses_changed_final_or_readback(self):
        self.add_plan('CYC-POST-REFUSE', 'COMP-EXACT', 'job-exact', 'after-exact')
        frozen, _ = self.inbox.plan('CYC-POST-REFUSE', 'COMP-EXACT')
        frozen = sealed_plan(frozen['operations'], {'stage': 'complete', 'sealed_final_marker': 'expected'})
        self.inbox.discard_plan('CYC-POST-REFUSE', 'COMP-EXACT')
        self.save_applied_plan('CYC-POST-REFUSE', 'COMP-EXACT', frozen)
        remote = RecordingRemote([job('job-exact')])
        with patch.object(self.inbox, 'acknowledge', side_effect=OSError('simulated cleanup crash')):
            publish_exact_cycle(self.inbox, 'CYC-POST-REFUSE', remote, state=self.state)
        checkpoint = self.state.cycle('CYC-POST-REFUSE')
        checkpoint['companies']['COMP-EXACT']['sealed_final_marker'] = 'manual-change'
        self.state.save_cycle(checkpoint)
        commits = len(remote.commits)

        report = publish_exact_cycle(self.inbox, 'CYC-POST-REFUSE', remote, state=self.state)

        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT',
                                           'reason': 'state_checkpoint_not_recoverable'}])
        self.assertEqual(len(remote.commits), commits)
        self.assertIsNotNone(self.inbox.plan('CYC-POST-REFUSE', 'COMP-EXACT'))

    def test_chunk_journal_digest_mismatch_holds_without_replay(self):
        self.add_plan('CYC-DIGEST', 'COMP-EXACT', 'job-exact', 'after-exact')
        self.inbox.begin_exact_chunk('CYC-DIGEST', 'COMP-EXACT', 0, 1, 'incorrect-digest')
        remote = RecordingRemote([job('job-exact')])

        report = publish_exact_cycle(self.inbox, 'CYC-DIGEST', remote, state=self.state)

        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT', 'reason': 'chunk_journal_mismatch'}])
        self.assertEqual(remote.commits, [])

    def test_remote_publication_never_advances_local_apply_cursor(self):
        self.add_plan('CYC-CAS', 'COMP-EXACT', 'job-exact', 'after-exact')
        remote = RecordingRemote([job('job-exact')])

        with patch.object(self.inbox, 'advance', side_effect=AssertionError(
                'remote publication must not advance local cursor')):
            report = publish_exact_cycle(self.inbox, 'CYC-CAS', remote, state=self.state)

        self.assertEqual(report['confirmed'], ['COMP-EXACT'])
        self.assertEqual(len(remote.commits), 1)
        self.assertEqual(self.inbox.pending('CYC-CAS', include_blocked=True), [])

    def test_state_save_failure_keeps_exact_plan_after_confirmed_remote_readback(self):
        self.add_plan('CYC-SAVE-FAIL', 'COMP-EXACT', 'job-exact', 'after-exact')
        remote = RecordingRemote([job('job-exact')])

        report = publish_exact_cycle(self.inbox, 'CYC-SAVE-FAIL', remote,
                                     state=FailingSaveState(self.state))

        self.assertEqual(report['held'], [{'company_id': 'COMP-EXACT', 'reason': 'OSError'}])
        self.assertEqual(len(remote.commits), 1)
        self.assertIsNotNone(self.inbox.plan('CYC-SAVE-FAIL', 'COMP-EXACT'))
        self.assertEqual(self.inbox.pending('CYC-SAVE-FAIL', include_blocked=True), ['COMP-EXACT'])
        frozen, _ = self.inbox.plan('CYC-SAVE-FAIL', 'COMP-EXACT')
        receipt = self.inbox.find_receipt('COMP-EXACT', record_fingerprints(frozen['operations']))
        self.assertEqual(self.inbox.receipt({'binding': receipt['binding']})['state'], SYNC_CONFIRMED)


if __name__ == '__main__':
    unittest.main()
