"""Published questions corrections preserve the Opportunity and human inputs."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from job_search_helper.review_question_correction import (EVENT,correction_snapshot,correct_published_questions)
from job_search_helper.review_runtime import assessment_signature,digest
from job_search_helper.review_writeback import sync_pending,requires_opportunity
from job_search_helper.review_publication import publication_counts
import test_review_publication as fixtures


class PublishedQuestionsCorrectionTests(unittest.TestCase):
    setUpBase=fixtures.ReviewPublicationTests.setUp
    claim=fixtures.ReviewPublicationTests.claim
    assess=fixtures.ReviewPublicationTests.assess
    repository=fixtures.ReviewPublicationTests.repository
    stores=fixtures.ReviewPublicationTests.stores
    save=fixtures.ReviewPublicationTests.save
    deliver=fixtures.ReviewPublicationTests.deliver

    def setUp(self):
        self.setUpBase(); self.stores(['questions'])
        self.environment=patch('job_search_helper.runner._load_environment'); self.environment.start(); self.addCleanup(self.environment.stop)
        self.owner,items=self.save(3,['questions'],[getattr(self,'initial_decision','Needs Info')]); self.item=items[0]
        self.assertEqual(self.deliver(3,self.owner)['counts'],{'Written':1})
        # Publishing removes jobs from normal eligibility and can clear task owner.
        with self.runtime.transaction(): self.runtime.db.execute("UPDATE tasks SET active=0,owner=NULL WHERE stage=3")
        self.lock=Path(self.temp.name)/'correction-writer.lock'
        snap=self.inspect()
        self.request={'job_key':'questions','source_hash':'h1','input_version':self.item['input_version'],
            **{'expected_'+field+'_signature':snap[field+'_signature'] for field in ['assessment','intent','publication','live']},
            'correction_id':'verified-clearance-labels-1','correction_reason':'Official field labels now establish mandatory Secret clearance.',
            'assessment':{'job_key':'questions','source_hash':'h1','decision':'Reject','fit_level':None,
                'reason':'Official posting explicitly requires ability to obtain Secret security clearance.',
                'evidence_source':'Exact official posting','evidence_locator':'https://example.com/jobs/questions; Must Be Able to Obtain: Secret','policy_conflicts':[]}}

    def inspect(self):
        return correction_snapshot(self.runtime,self.owner,'questions','h1',repo=self.local,remote=self.remote)

    def prepare(self,request=None):
        return correct_published_questions(self.runtime,self.owner,request or self.request,repo=self.local,remote=self.remote,lock_path=self.lock)

    def saved(self):
        return json.loads(self.runtime.db.execute("SELECT payload FROM decisions WHERE stage=3 AND job_key='questions'").fetchone()[0])

    def events(self):
        return [json.loads(row[0]) for row in self.runtime.db.execute('SELECT detail FROM events WHERE event=?',(EVENT,))]

    def write(self):
        return sync_pending(self.runtime,3,self.owner,repo=self.local,identities={('questions','h1')},lock_path=Path(self.temp.name)/'local-write.lock')

    def test_preparation_is_audited_preserves_review_time_and_has_no_sheet_writes(self):
        old=self.saved(); remote_before=self.remote.read('Job History'); opp_before=self.remote.read('Opportunities')
        self.assertEqual(self.prepare()['corrected'],1)
        self.assertEqual(self.remote.read('Job History'),remote_before); self.assertEqual(self.remote.read('Opportunities'),opp_before)
        new=self.saved(); self.assertEqual(new['decision'],'Reject'); self.assertEqual(new['reviewed_at'],old['reviewed_at']); self.assertEqual(new['run_id'],old['run_id'])
        self.assertIn('corrected_at',new); self.assertEqual(self.runtime.run_status(3,self.owner)['saved_assessments'],1)
        audit=self.events()[0]; self.assertEqual(audit['prior']['assessment'],old); self.assertEqual(audit['prior']['publication']['state'],'Written')
        self.assertIn('remote_opportunity',audit['prior']['live']); self.assertTrue(requires_opportunity(audit['intent']))
        self.assertFalse(audit['intent']['operations'][1]['append_if_missing'])
        self.assertEqual(self.prepare()['reused'],1); self.assertEqual(len(self.events()),1)

    def test_delivery_keeps_opportunity_and_personal_fields(self):
        # Capture current human fields before preparing an explicitly fenced request.
        self.service.set_cell('Opportunities',1,'Application Status','Applied'); self.service.set_cell('Opportunities',1,'Date Applied','2026-10-01'); self.service.set_cell('Opportunities',1,'Notes','My note'); self.service.set_cell('Opportunities',1,'Fit Review','Potential Fit')
        from job_search_helper.sheets_sync import SheetsSynchronizer
        SheetsSynchronizer(self.local,self.remote).merge_remote('Opportunities',[(2,self.remote.read_row('Opportunities',2))],complete_snapshot=False)
        self.local.commit([{'tab':'Opportunities','identity':{'Company':'Fixture','Job URL':'https://example.com/jobs/questions'},'values':{'Fit Review':'Potential Fit'}}])
        snap=self.inspect(); self.request['expected_live_signature']=snap['live_signature']
        self.prepare(); self.assertEqual(self.write()['counts'],{'Written':1})
        self.assertEqual(self.deliver(3,self.owner)['counts'],{'Written':1})
        history=self.remote.read('Job History')[0]; opp=self.remote.read('Opportunities')[0]
        self.assertEqual(history['Added to Opportunities?'],'Yes'); self.assertEqual(history['Review Status'],'Reviewed')
        self.assertIn('requires ability',history['Rejection Reason']); self.assertEqual(history['Fit Level'],'')
        self.assertEqual((opp['Application Status'],opp['Date Applied'],opp['Notes'],opp['Fit Review']),('Applied','2026-10-01','My note','Potential Fit'))
        self.assertIn('Resolved:',opp['Review Questions']); self.assertNotIn('[third-pass correction',opp['Review Questions'])
        self.assertEqual(len(self.remote.read('Opportunities')),1)

    def test_idempotent_after_reject_and_verified_publication(self):
        self.prepare(); self.write(); self.deliver(3,self.owner)
        receipt=dict(self.runtime.db.execute('SELECT * FROM review_publications WHERE stage=3').fetchone())
        self.assertEqual(self.prepare()['reused'],1)
        self.assertEqual(dict(self.runtime.db.execute('SELECT * FROM review_publications WHERE stage=3').fetchone()),receipt)
        self.assertEqual(len(self.events()),1); self.assertEqual(self.write()['selected'],0)
        self.assertEqual(self.remote.read('Opportunities')[0]['Review Questions'].count('Resolved:'),1)

    def test_changed_source_refuses_without_mutation(self):
        self.local.commit([{'tab':'Job History','identity':{'Job Key':'questions'},'values':{'Source Hash':'changed'}}])
        before=self.saved()
        with self.assertRaises(ValueError): self.prepare()
        self.assertEqual(self.saved(),before); self.assertEqual(self.events(),[])

    def test_intervening_human_opportunity_edit_blocks_preparation(self):
        self.service.set_cell('Opportunities',1,'Notes','New human note')
        with self.assertRaises(ValueError): self.prepare()
        self.assertEqual(self.events(),[]); self.assertEqual(self.remote.read('Opportunities')[0]['Notes'],'New human note')

    def test_human_edit_after_preparation_blocks_publication(self):
        self.prepare(); self.write(); self.service.set_cell('Opportunities',1,'Application Status','Interviewing')
        self.assertEqual(self.deliver(3,self.owner)['counts'],{'Conflict':1})
        self.assertEqual(self.remote.read('Opportunities')[0]['Application Status'],'Interviewing')
        self.assertEqual(self.remote.read('Job History')[0]['Rejection Reason'],'')

    def test_missing_existing_opportunity_never_creates_one(self):
        self.prepare(); self.write()
        self.service.sheet('Opportunities')['data'][0]['rowData'].pop(1)
        self.assertEqual(self.deliver(3,self.owner)['counts'],{'Conflict':1})
        self.assertEqual(self.remote.read('Opportunities'),[])

    def test_partial_remote_response_safely_retries_without_duplicate_notes(self):
        self.prepare(); self.write(); commit=self.remote.commit; tripped=False
        def lost_once(operations):
            nonlocal tripped
            if not tripped:
                tripped=True
                commit([operation for operation in operations if operation['tab']=='Job History'])
                raise RuntimeError('lost response after partial History delivery')
            return commit(operations)
        with patch.object(self.remote,'commit',side_effect=lost_once): self.assertEqual(self.deliver(3,self.owner)['counts'],{'Pending':1})
        self.assertEqual(self.deliver(3,self.owner)['counts'],{'Written':1})
        self.assertEqual(self.remote.read('Opportunities')[0]['Review Questions'].count('Resolved:'),1)
        self.assertEqual(self.remote.read('Job History')[0]['Review Notes'].count('[third-pass correction'),1)

    def test_reconsideration_increments_once_even_with_replay(self):
        self.local.commit([{'tab':'Job History','identity':{'Job Key':'questions'},'values':{'Description Hash':'old-source','Reconsideration Count':1}}])
        snap=self.inspect(); self.request['expected_live_signature']=snap['live_signature']
        self.prepare(); self.write()
        row=self.local.read('Job History')[0]; self.assertEqual(row['Reconsideration Count'],2); self.assertEqual(row['Reconsideration Status'],'Frozen after 2')
        self.assertEqual(self.prepare()['reused'],1); self.assertEqual(self.local.read('Job History')[0]['Reconsideration Count'],2)

    def test_wrong_signatures_or_other_run_are_refused(self):
        bad=copy.deepcopy(self.request); bad['expected_intent_signature']='stale'
        with self.assertRaises(ValueError): self.prepare(bad)
        other=self.runtime.start(3)['run_id']
        with self.assertRaises(ValueError): correct_published_questions(self.runtime,other,self.request,repo=self.local,remote=self.remote,lock_path=self.lock)
        self.assertEqual(self.events(),[])


class PublishedAcceptCorrectionTests(unittest.TestCase):
    initial_decision='Accept'
    setUp=PublishedQuestionsCorrectionTests.setUp
    setUpBase=PublishedQuestionsCorrectionTests.setUpBase
    claim=PublishedQuestionsCorrectionTests.claim
    assess=PublishedQuestionsCorrectionTests.assess
    repository=PublishedQuestionsCorrectionTests.repository
    stores=PublishedQuestionsCorrectionTests.stores
    save=PublishedQuestionsCorrectionTests.save
    deliver=PublishedQuestionsCorrectionTests.deliver
    inspect=PublishedQuestionsCorrectionTests.inspect
    prepare=PublishedQuestionsCorrectionTests.prepare
    saved=PublishedQuestionsCorrectionTests.saved
    events=PublishedQuestionsCorrectionTests.events
    write=PublishedQuestionsCorrectionTests.write

    def test_own_accept_can_be_corrected_without_changing_existing_fit_label(self):
        original=self.saved(); fit=self.remote.read('Opportunities')[0]['Fit Review']
        stored=self.runtime.db.execute('SELECT payload FROM writeback').fetchone()
        intent=json.loads(stored[0]); intent.pop('pass',None); intent.pop('requires_opportunity',None)
        with self.runtime.transaction(): self.runtime.db.execute('UPDATE writeback SET payload=?',(json.dumps(intent),))
        self.request['expected_intent_signature']=digest(intent)
        self.prepare(); self.write(); self.assertEqual(self.deliver(3,self.owner)['counts'],{'Written':1})
        new=self.saved(); self.assertEqual((new['decision'],new['fit_level']),('Reject',None))
        self.assertEqual(new['reviewed_at'],original['reviewed_at']); self.assertEqual(new['run_id'],original['run_id'])
        opp=self.remote.read('Opportunities')[0]
        self.assertEqual(opp['Fit Review'],fit); self.assertEqual(len(self.remote.read('Opportunities')),1)
        self.assertEqual(self.remote.read('Job History')[0]['Added to Opportunities?'],'Yes')
        audit=self.events()[0]; self.assertEqual(audit['prior']['assessment']['decision'],'Accept'); self.assertEqual(audit['prior']['assessment']['fit_level'],'Strong')
        self.assertEqual(self.prepare()['reused'],1)

    def test_a_written_own_receipt_cannot_be_invented(self):
        with self.runtime.transaction(): self.runtime.db.execute("UPDATE review_publications SET state='Pending'")
        with self.assertRaises(ValueError): self.prepare()
        self.assertEqual(self.events(),[]); self.assertEqual(self.saved()['decision'],'Accept')

    def test_human_fit_review_change_blocks_correction_publication(self):
        self.prepare(); self.write(); self.service.set_cell('Opportunities',1,'Fit Review','Unlikely Fit')
        self.assertEqual(self.deliver(3,self.owner)['counts'],{'Conflict':1})
        self.assertEqual(self.remote.read('Opportunities')[0]['Fit Review'],'Unlikely Fit')
        self.assertEqual(self.remote.read('Job History')[0]['Rejection Reason'],'')
