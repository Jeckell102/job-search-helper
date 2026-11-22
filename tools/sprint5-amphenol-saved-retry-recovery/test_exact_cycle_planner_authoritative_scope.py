"""Regression: compact planner rows must not become fabricated blank guards."""
import copy
from contextlib import closing

from job_search_helper.batching import PlanningRepository
from job_search_helper.exact_cycle_planner import _freeze, _hydrate_authoritative_operation_scope
from job_search_helper.repository import SCHEMAS, _equivalent
from job_search_helper.sqlite_repository import SQLiteRepository


COMPANY = {
    'Company': 'Scope Co', 'Company ID': 'COMP-SCOPE', 'Company Status': 'Active',
    'Official Careers URL': 'https://scope.example/jobs', 'ATS / Source': 'Fixture',
}


class TargetedRepository:
    """Full authoritative records with the same partial-cache surface as SQLite."""
    def __init__(self):
        self.schemas = copy.deepcopy(SCHEMAS)
        self.full = {
            'Companies': [COMPANY],
            'Job History': [{
                'Company': 'Scope Co', 'Job Key': 'scope:1', 'Official Job URL': 'https://scope.example/jobs/1',
                'Job Title': 'Engineer', 'Source Hash': 'old', 'Salary / Range': '$135,000-$150,000',
                'Added to Opportunities?': 'Manual Review', 'Review Status': 'Reviewed', 'Decision': 'Reject',
                'Job Status': 'Open and verified',
            }],
            'Job Evidence': [{
                'Company': 'Scope Co', 'Job Key': 'scope:1', 'Source Hash': 'old',
                'Job Title': 'Engineer', 'Official Job URL': 'https://scope.example/jobs/1',
                'Job Description': 'Old full description',
            }],
            'Opportunities': [{
                'Company': 'Scope Co', 'Job URL': 'https://scope.example/jobs/1',
                'Job Title': 'Engineer', 'Salary / Range': '$135,000-$150,000',
            }],
            'Scan Cycles': [],
        }
        self.match_calls = []

    def read_cached_columns(self):
        return True

    def read(self, tab):
        # Planning may read Companies; hydration must not use broad job-table reads.
        if tab != 'Companies':
            raise AssertionError('broad table read: ' + tab)
        return copy.deepcopy(self.full[tab])

    def read_columns(self, tab, headers):
        return [(number, {header: row.get(header, '') for header in headers})
                for number, row in enumerate(self.full[tab])]

    def matches(self, tab, identity):
        self.match_calls.append((tab, copy.deepcopy(identity)))
        return [(number, copy.deepcopy(row)) for number, row in enumerate(self.full[tab])
                if all(_equivalent(header, row.get(header, ''), value) for header, value in identity.items())]


class DummyEngine:
    def __init__(self, repository):
        self.repo, self.state, self._notices = repository, object(), []

    def _verify_same_board(self, _, company):
        assert company['Company ID'] == 'COMP-SCOPE'

    def _stage_posting(self, *_):
        self.repo.commit([
            {'tab': 'Job History', 'identity': {'Job Key': 'scope:1'},
             'values': {'Source Hash': 'new', 'Salary / Range': '', 'Job Title': 'Engineer'},
             'expected': {'Added to Opportunities?': '', 'Salary / Range': '', 'Source Hash': 'old'}},
            {'tab': 'Job Evidence', 'identity': {'Job Key': 'scope:1', 'Source Hash': 'old'},
             'values': {'Captured At': 'new-capture'}, 'expected': {'Company': ''}},
            {'tab': 'Opportunities', 'identity': {'Company': 'Scope Co', 'Job URL': 'https://scope.example/jobs/1'},
             'values': {'Salary / Range': '', 'Job Title': 'Updated Engineer'},
             'expected': {'Salary / Range': ''}},
        ])

    def _finish_company(self, *_):
        return None


def test_exact_freeze_hydrates_only_targeted_full_rows_before_guard_and_noop_logic():
    base = TargetedRepository()
    planner = PlanningRepository(base)
    # Hydration must not rebuild every identity index after each of the three
    # targeted reads; that would make selected recovery scale with all Jobs.
    planner._reindex = lambda: (_ for _ in ()).throw(AssertionError('full reindex'))
    engine = DummyEngine(planner)
    cycle = {'companies': {'COMP-SCOPE': {'stage': 'queued'}}}
    payload = {'inventory_status': 'partial', 'requested_url': COMPANY['Official Careers URL'],
               'jobs': [{'title': 'Engineer'}]}

    plan = _freeze(engine, planner, cycle, 'COMP-SCOPE', payload, drop_noops=True)

    history = next(op for op in plan['operations'] if op['tab'] == 'Job History')
    evidence = next(op for op in plan['operations'] if op['tab'] == 'Job Evidence')
    opportunity = next(op for op in plan['operations'] if op['tab'] == 'Opportunities')
    assert history['expected']['Added to Opportunities?'] == 'Manual Review'
    assert history['expected']['Salary / Range'] == '$135,000-$150,000'
    assert 'Salary / Range' not in history['values']
    assert evidence['expected']['Company'] == 'Scope Co'
    assert opportunity['expected']['Salary / Range'] == '$135,000-$150,000'
    assert 'Salary / Range' not in opportunity['values']
    assert {tab for tab, _ in base.match_calls} == {'Job History', 'Job Evidence', 'Opportunities'}
    assert all(identity for _, identity in base.match_calls)


def test_loaded_manual_choice_drift_holds_instead_of_rebinding_to_current_row(tmp_path):
    """A visible planning value is a guard; only omitted compact columns hydrate."""
    history = {
        'Company': 'Scope Co', 'Job Key': 'scope:1', 'Official Job URL': 'https://scope.example/jobs/1',
        'Job Title': 'Engineer', 'Source Hash': 'old', 'Added to Opportunities?': 'Manual Review',
        'Review Status': 'Manual Review', 'Decision': '',
    }
    with closing(SQLiteRepository(tmp_path / 'jobs.sqlite3', 'fixture', initialize=True)) as jobs:
        jobs.import_rows('Companies', [(2, COMPANY)])
        jobs.import_rows('Job History', [(2, history)])
        planner = PlanningRepository(jobs)
        jobs.commit([{'tab': 'Job History', 'identity': {'Job Key': 'scope:1'},
                      'values': {'Added to Opportunities?': 'No'}}])

        class VisibleGuardEngine(DummyEngine):
            def _stage_posting(self, *_):
                self.repo.commit([{
                    'tab': 'Job History', 'identity': {'Job Key': 'scope:1'},
                    'values': {'Source Hash': 'new'},
                    'expected': {'Source Hash': 'old', 'Added to Opportunities?': 'Manual Review'},
                }])

        try:
            _freeze(VisibleGuardEngine(planner), planner,
                    {'companies': {'COMP-SCOPE': {'stage': 'queued'}}}, 'COMP-SCOPE',
                    {'inventory_status': 'partial', 'requested_url': COMPANY['Official Careers URL'],
                     'jobs': [{'title': 'Engineer'}]}, drop_noops=True)
        except ValueError as error:
            assert 'visible_drift' in str(error)
        else:
            raise AssertionError('visible manual choice drift was rebound instead of held')


def test_fully_loaded_company_row_is_never_treated_as_compact_omission():
    base = TargetedRepository()
    base.full['Companies'][0] = copy.deepcopy(base.full['Companies'][0])
    planner = PlanningRepository(base)
    base.full['Companies'][0]['Company Status'] = 'Paused'
    try:
        _hydrate_authoritative_operation_scope(
            planner,
            {'tab': 'Companies', 'identity': {'Company ID': 'COMP-SCOPE'},
             'expected': {'Company Status': 'Active'}},
            {},
        )
    except ValueError as error:
        assert 'visible_drift' in str(error)
    else:
        raise AssertionError('fully loaded Company state was rebound')
