"""Offline closure transitions, guarded delivery, and recovery; no live state."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.closed_jobs import MARKER, stage_closed_pending, publish_closed_pending
from job_search_helper.core import pack_snapshot
from job_search_helper.engine import Engine, State
from job_search_helper.repository import MemoryRepository, GoogleRepository, SCHEMAS, RepositoryError
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.sheet_profile import COMPACT_SCHEMAS, COMPACT_PROFILE
from sheets_fixture import RangeSheets


def job(key='closed', **changes):
    return dict({'Company':'Acme', 'Job Key':key,'Job Title':'Field Engineer',
        'Official Job URL':'https://jobs.example.com/'+key,'Source Hash':'source-'+key,
        'Job Status':'Closed','Added to Opportunities?':'Pending','Review Status':'Needs Review',
        'Review Notes':'Keep original notes','Last Evaluated':'old-review-date',
        'Decision':'Needs Info','Fit Level':'','Description Hash':'old-assessment',
        'Reconsideration Count':1,'Rejection Reason':'Prior reason'}, **changes)


class ClosedJobTests(unittest.TestCase):
    def test_cleanup_is_not_a_fit_decision_and_is_idempotent(self):
        repo=MemoryRepository({'Job History':[job()]})
        before=repo.read('Job History')[0]
        first=stage_closed_pending(repo); after=repo.read('Job History')[0]
        self.assertEqual(first['changed'],1)
        self.assertEqual(after['Added to Opportunities?'],'No')
        self.assertEqual(after['Review Status'],'Reviewed')
        for h,v in before.items():
            if h not in ('Added to Opportunities?','Review Status','Review Started At','Review Notes'):
                self.assertEqual(after[h],v,h)
        self.assertIn('Keep original notes',after['Review Notes'])
        self.assertEqual(after['Review Notes'].count(MARKER),1)
        self.assertEqual(stage_closed_pending(repo)['changed'],0)
        self.assertEqual(repo.read('Opportunities'),[])

    def test_uncertain_closure_manual_choices_and_live_claims_are_preserved(self):
        cases=[{'Job Status':'Unable to verify'},{'Job Status':'Open and verified'},
               *[{'Added to Opportunities?':v} for v in ('Yes','No','Manual Review','')],
               {'Review Status':'In Progress'},{'Review Status':'Manual Review'},
               {'Review Started At':'live-claim'}]
        for change in cases:
            with self.subTest(change=change):
                repo=MemoryRepository({'Job History':[job(**change)]});before=copy.deepcopy(repo.tables)
                self.assertEqual(stage_closed_pending(repo)['changed'],0)
                self.assertEqual(repo.tables,before)

    def test_existing_opportunity_and_user_application_fields_are_protected(self):
        opp={'Company':'Acme','Job URL':job()['Official Job URL'],'Application Status':'Applied',
             'Date Applied':'2026-10-01','Notes':'personal','Fit Review':'Strong Potential Fit'}
        repo=MemoryRepository({'Job History':[job()],'Opportunities':[opp]});before=copy.deepcopy(repo.tables)
        self.assertEqual(stage_closed_pending(repo)['changed'],0)
        self.assertEqual(repo.tables,before)

    def test_preview_and_batch_limit(self):
        repo=MemoryRepository({'Job History':[job(str(i)) for i in range(3)]});before=copy.deepcopy(repo.tables)
        report=stage_closed_pending(repo,limit=2,apply=False)
        self.assertEqual(report['planned'],2);self.assertEqual(report['changed'],0)
        self.assertEqual(repo.tables,before)
        report=stage_closed_pending(repo,limit=2)
        self.assertEqual(report['changed'],2);self.assertEqual(report['remaining'],1)

    def test_second_complete_absence_sets_no_in_same_closure_operation(self):
        source='https://boards.greenhouse.io/acme'
        company={'Company':'Acme','Company ID':'C-1','Official Careers URL':source}
        repo=MemoryRepository({'Companies':[company],'Job History':[job(**{
            'Job Status':'Unable to verify','Consecutive Missing Scans':1,
            'Current Snapshot':pack_snapshot({'v':1,'evaluations':[],'inventory_source':source})})]})
        state=State();self.addCleanup(state.close)
        engine=Engine(repo,state)
        engine._reconcile_absences({'id':'CYC-new','companies':{'C-1':{'source_url':source}}},company,[])
        row=repo.read('Job History')[0]
        self.assertEqual(row['Job Status'],'Closed');self.assertEqual(row['Added to Opportunities?'],'No')
        self.assertEqual(row['Decision'],'Needs Info');self.assertEqual(row['Last Evaluated'],'old-review-date')

    def test_first_absence_does_not_set_no(self):
        source='https://boards.greenhouse.io/acme';company={'Company':'Acme','Company ID':'C-1','Official Careers URL':source}
        repo=MemoryRepository({'Companies':[company],'Job History':[job(**{
            'Job Status':'Open and verified','Consecutive Missing Scans':0,
            'Current Snapshot':pack_snapshot({'v':1,'evaluations':[],'inventory_source':source})})]})
        state=State();self.addCleanup(state.close)
        Engine(repo,state)._reconcile_absences({'id':'CYC-one','companies':{'C-1':{'source_url':source}}},company,[])
        row=repo.read('Job History')[0]
        self.assertEqual(row['Job Status'],'Unable to verify');self.assertEqual(row['Added to Opportunities?'],'Pending')


class ClosedDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.local=SQLiteRepository(Path(self.temp.name)/'jobs.sqlite3','fixture',initialize=True)
        self.addCleanup(self.local.close)
        full=MemoryRepository({'Job History':[job(),job('unrelated',**{'Job Status':'Open and verified'})]})
        for tab in SCHEMAS:self.local.import_rows(tab,enumerate(full.read(tab),2))
        with self.local.transaction():
            self.local.set_meta('ready','yes');self.local.set_meta('sheets_profile',COMPACT_PROFILE)
        self.service=RangeSheets(full.tables,schemas=COMPACT_SCHEMAS)
        self.remote=GoogleRepository(self.service,'fixture',schemas=COMPACT_SCHEMAS,min_request_interval=0)

    def test_scoped_delivery_preserves_unrelated_changes_and_assessment_fields(self):
        self.local.commit([{'tab':'Job History','identity':{'Job Key':'unrelated'},'values':{'Last Checked':'future'}}])
        report=publish_closed_pending(self.local,self.remote)
        self.assertEqual(report['verified'],1);self.assertEqual(report['remaining'],0)
        rows={r['Job Key']:r for r in self.remote.read('Job History')}
        self.assertEqual(rows['closed']['Added to Opportunities?'],'No')
        self.assertNotEqual(rows['unrelated']['Last Checked'],'future')
        self.assertEqual(self.local.read('Job History')[0]['Decision'],'Needs Info')
        self.assertEqual(self.local.db.execute('select count(*) from manual_choices').fetchone()[0],0)
        self.assertEqual(publish_closed_pending(self.local,self.remote)['verified'],0)

    def test_failed_delivery_retries_same_cleanup_without_duplicate_notes(self):
        with patch.object(self.remote,'commit',side_effect=RuntimeError('offline')):
            first=publish_closed_pending(self.local,self.remote)
        self.assertEqual(first['verified'],0);self.assertEqual(first['remaining'],1)
        second=publish_closed_pending(self.local,self.remote)
        self.assertEqual(second['verified'],1)
        self.assertEqual(self.remote.read('Job History')[0]['Review Notes'].count(MARKER),1)

    def test_new_manual_yes_during_delivery_is_not_overwritten(self):
        original=self.remote.commit
        def race(operations):
            original([{'tab':'Job History','identity':{'Job Key':'closed'},'values':{'Added to Opportunities?':'Yes'}}])
            return original(operations)
        with patch.object(self.remote,'commit',side_effect=race):report=publish_closed_pending(self.local,self.remote)
        self.assertEqual(report['verified'],0)
        self.assertEqual(self.remote.read('Job History')[0]['Added to Opportunities?'],'Yes')

    def test_lost_write_response_is_verified_without_false_manual_no(self):
        original=self.remote.commit
        def lost(operations):
            original(operations)
            raise RuntimeError('response lost after successful write')
        with patch.object(self.remote,'commit',side_effect=lost):report=publish_closed_pending(self.local,self.remote)
        self.assertEqual(report['verified'],1)
        self.assertEqual(self.local.db.execute('select count(*) from manual_choices').fetchone()[0],0)
        self.assertEqual(self.local.db.execute('select count(*) from dirty').fetchone()[0],0)
        self.assertEqual(self.local.read('Job History')[0]['Decision'],'Needs Info')
