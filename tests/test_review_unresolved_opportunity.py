"""Third-pass questions are delivered as Opportunities without asserting fit."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.repository import MemoryRepository, GoogleRepository, SCHEMAS
from sheets_fixture import RangeSheets
from job_search_helper.review_runtime import Runtime
from job_search_helper.review_writeback import (plan, requires_opportunity,
    sync_pending, verified, writeback)
from test_concurrent_review import publish, response
import test_review_auto_writeback as writeback_fixtures
import test_review_publication as publication_fixtures


class UnresolvedOpportunityTests(unittest.TestCase):
    claim = writeback_fixtures.ReviewDeliveryTests.claim
    repository = writeback_fixtures.ReviewDeliveryTests.repository

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.queue=Path(self.temp.name)/'queue'; publish(self.queue)
        self.runtime=Runtime(self.queue); self.addCleanup(self.runtime.close)

    def save(self, stage=3):
        owner,items=self.claim(stage,['questions'])
        answer=response(items[0],stage,'Needs Info' if stage==3 else 'NEEDS_INFO')
        answer['reason']='Confirm whether U.S. EOR employment is available; clarify clearance obligation.'
        self.runtime.submit(stage,owner,[answer])
        return owner,items[0],answer

    def test_unknown_location_creates_truthful_opportunity_and_is_idempotent(self):
        owner,item,_=self.save(); repo=self.repository(['questions'])
        repo.commit([{'tab':'Job History','identity':{'Job Key':'questions'},'values':{'Location':'Any available EOR location',
            'Description Hash':'old','Reconsideration Count':1,'Rejection Reason':'Old reason'}}])
        self.assertEqual(sync_pending(self.runtime,3,owner,repo=repo)['counts'],{'Written':1})
        row=repo.read('Job History')[0]; opp=repo.read('Opportunities')[0]
        self.assertEqual((row['Added to Opportunities?'],row['Review Status'],row['Decision']),('Yes','Reviewed','Needs Info'))
        self.assertEqual((row['Fit Level'],row['Rejection Reason']),('',''))
        self.assertEqual((row['Description Hash'],row['Reconsideration Count']),('old',1))
        self.assertEqual((opp['Fit Review'],opp['Application Status'],opp['Date Applied']),('','Not Reviewed',''))
        self.assertIn('Confirm whether U.S. EOR',opp['Review Questions'])
        self.assertEqual(opp['Notes'],'')
        intent=json.loads(self.runtime.db.execute('SELECT payload FROM writeback').fetchone()[0])
        self.assertTrue(requires_opportunity(intent)); self.assertTrue(verified(repo,intent))
        self.assertEqual(sync_pending(self.runtime,3,owner,repo=repo)['selected'],0)
        self.assertEqual(len(repo.read('Opportunities')),1)
        repo.commit([{'tab':'Opportunities','identity':{'Company':'Fixture','Job URL':'https://example.com/jobs/questions'},'values':{'Review Questions':'lost'}}])
        self.assertFalse(verified(repo,intent))

    def test_existing_personal_fields_fit_and_questions_are_preserved(self):
        owner,_,_=self.save(); base=self.repository(['questions'])
        original={'Company':'Fixture','Job Title':'Old title','Job URL':'https://example.com/jobs/questions',
            'Fit Review':'Strong Potential Fit','Application Status':'Applied','Date Applied':'2026-10-01',
            'Date Found':'2026-09-01','Notes':'Personal note','Review Questions':'Earlier question'}
        repo=MemoryRepository({**base.tables,'Opportunities':[original]})
        self.assertEqual(sync_pending(self.runtime,3,owner,repo=repo)['counts'],{'Written':1})
        opp=repo.read('Opportunities')[0]
        for key in ['Fit Review','Application Status','Date Applied','Date Found','Notes']:
            self.assertEqual(opp[key],original[key])
        self.assertTrue(opp['Review Questions'].startswith('Earlier question\n\n'))
        intent=json.loads(self.runtime.db.execute('SELECT payload FROM writeback').fetchone()[0])
        old=repo.read('Job History')[0]; old.update({'Added to Opportunities?':'Pending','Review Status':'Needs Review'})
        result=json.loads(self.runtime.db.execute('SELECT payload FROM decisions WHERE stage=3').fetchone()[0])
        again=plan(self.runtime,repo,result,old,3,opportunity_matches=[opp])
        self.assertEqual(again['opportunity_values']['Review Questions'],opp['Review Questions'])
        result['reason']='A fresh same-source assessment asks a different question.'
        changed=plan(self.runtime,repo,result,old,3,opportunity_matches=[opp])
        changed_text=changed['opportunity_values']['Review Questions']
        self.assertTrue(changed_text.startswith(opp['Review Questions']+'\n\n'))
        self.assertIn(result['reason'],changed_text)
        self.assertEqual(changed_text.count(result['reason']),1)
        self.assertNotIn('[third-pass',changed_text)
        self.assertNotEqual(again['question_signature'],changed['question_signature'])
        updated={**opp,'Review Questions':changed_text}
        replay=plan(self.runtime,repo,result,old,3,opportunity_matches=[updated])
        self.assertEqual(replay['opportunity_values']['Review Questions'],changed_text)

    def test_lost_commit_response_is_verified_without_duplicate_opportunity(self):
        owner,_,_=self.save(); repo=self.repository(['questions']); commit=repo.commit
        def lost(operations):
            commit(operations); raise RuntimeError('Response lost')
        with patch.object(repo,'commit',side_effect=lost):
            self.assertEqual(sync_pending(self.runtime,3,owner,repo=repo)['counts'],{'Written':1})
        self.assertEqual(sync_pending(self.runtime,3,owner,repo=repo)['selected'],0)
        self.assertEqual(len(repo.read('Opportunities')),1)

    def test_single_writeback_path_requires_questions_readback(self):
        owner,item,_=self.save(); repo=self.repository(['questions'])
        self.assertEqual(writeback(self.runtime,3,owner,item['job_key'],item['source_hash'],repo=repo)['writeback_status'],'Written')
        self.assertEqual(len(repo.read('Opportunities')),1)

    def test_direct_sheet_delivery_and_second_pass_policy(self):
        owner,_,_=self.save(); base=self.repository(['questions'])
        service=RangeSheets(base.tables,schemas=SCHEMAS)
        remote=GoogleRepository(service,'fixture',schemas=SCHEMAS,min_request_interval=0)
        self.assertEqual(sync_pending(self.runtime,3,owner,repo=remote)['counts'],{'Written':1})
        self.assertIn('Confirm whether U.S. EOR',remote.read('Opportunities')[0]['Review Questions'])
        self.assertEqual(remote.read('Job History')[0]['Added to Opportunities?'],'Yes')

    def test_second_pass_stays_manual_without_opportunity(self):
        owner,_,_=self.save(2); repo=self.repository(['questions'])
        self.assertEqual(sync_pending(self.runtime,2,owner,repo=repo)['counts'],{'Written':1})
        row=repo.read('Job History')[0]
        self.assertEqual((row['Added to Opportunities?'],row['Review Status']),('Manual Review','Manual Review'))
        self.assertEqual(repo.read('Opportunities'),[])

    def test_pending_old_manual_intent_is_upgraded_with_normal_eligibility_guards(self):
        owner,_,answer=self.save(); repo=self.repository(['questions'])
        old=repo.read('Job History')[0]
        legacy=plan(self.runtime,repo,answer,old,3)
        legacy.pop('requires_opportunity'); legacy.pop('pass')
        legacy['history_values'].update({'Added to Opportunities?':'Manual Review','Review Status':'Manual Review'})
        legacy['operations']=legacy['operations'][:1]
        legacy['operations'][0]['values']=legacy['history_values']
        legacy['opportunity_values']={}
        with self.runtime.transaction():
            self.runtime.db.execute('INSERT INTO writeback VALUES(?,?,?)',(answer['job_key'],answer['source_hash'],json.dumps(legacy)))
        self.assertEqual(sync_pending(self.runtime,3,owner,repo=repo)['counts'],{'Written':1})
        self.assertEqual(len(repo.read('Opportunities')),1)

    def test_manual_conversion_requires_explicit_narrow_authorization(self):
        _,_,answer=self.save(); repo=self.repository(['questions']); old=repo.read('Job History')[0]
        old.update({'Added to Opportunities?':'Manual Review','Review Status':'Manual Review','Decision':'Needs Info'})
        with self.assertRaises(ValueError): plan(self.runtime,repo,answer,old,3)
        self.assertTrue(requires_opportunity(plan(self.runtime,repo,answer,old,3,authorized_manual_conversion=True)))
        old['Added to Opportunities?']='No'
        with self.assertRaises(ValueError): plan(self.runtime,repo,answer,old,3,authorized_manual_conversion=True)


class UnresolvedOpportunityPublicationTests(unittest.TestCase):
    setUp=publication_fixtures.ReviewPublicationTests.setUp
    claim=publication_fixtures.ReviewPublicationTests.claim
    assess=publication_fixtures.ReviewPublicationTests.assess
    repository=publication_fixtures.ReviewPublicationTests.repository
    stores=publication_fixtures.ReviewPublicationTests.stores
    save=publication_fixtures.ReviewPublicationTests.save
    deliver=publication_fixtures.ReviewPublicationTests.deliver

    def test_questions_publish_and_live_readback_are_required(self):
        self.stores(['questions']); owner,_=self.save(3,['questions'],['Needs Info'])
        result=self.deliver(3,owner)
        self.assertEqual(result['counts'],{'Written':1})
        opp=self.remote.read('Opportunities')[0]
        self.assertEqual(opp['Review Questions'],'Specific model assessment fixture')
        self.assertNotIn('[third-pass',opp['Review Questions'])
        self.assertEqual((opp['Fit Review'],opp['Notes']),('',''))
        self.assertEqual(self.remote.read('Job History')[0]['Added to Opportunities?'],'Yes')
        self.assertEqual(self.deliver(3,owner)['selected'],0)
        self.assertEqual(len(self.remote.read('Opportunities')),1)

    def test_missing_live_questions_cannot_get_written_receipt(self):
        self.stores(['questions']); owner,_=self.save(3,['questions'],['Needs Info'])
        commit=self.remote.commit
        def lose_questions(operations):
            result=commit(operations)
            if any(op.get('tab')=='Opportunities' for op in operations):
                self.service.set_cell('Opportunities',1,'Review Questions','')
            return result
        with patch.object(self.remote,'commit',side_effect=lose_questions):
            self.assertEqual(self.deliver(3,owner)['counts'],{'Pending':1})

    def test_lost_remote_response_is_reconciled_with_questions(self):
        self.stores(['questions']); owner,_=self.save(3,['questions'],['Needs Info'])
        commit=self.remote.commit
        def lost(operations):
            result=commit(operations)
            if any(op.get('tab')=='Opportunities' for op in operations): raise RuntimeError('response lost')
            return result
        with patch.object(self.remote,'commit',side_effect=lost):
            self.assertEqual(self.deliver(3,owner)['counts'],{'Written':1})
        self.assertEqual(len(self.remote.read('Opportunities')),1)
