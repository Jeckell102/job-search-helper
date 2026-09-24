import json
import tempfile
import unittest
from pathlib import Path

from job_search_helper.ats import Inventory
from job_search_helper.core import excluded_title, unpack_snapshot
from job_search_helper.engine import Engine, State
from job_search_helper.repository import MemoryRepository


def company():
    return {"Company":"Demo Co","Company ID":"COMP-1","Company Status":"Active","ATS / Source":"Greenhouse","Official Careers URL":"https://boards.greenhouse.io/demo"}


def posting(title="Solutions Engineer", description="VERSION ONE"):
    return {"company_id":"COMP-1","company":"Demo Co","ats":"Greenhouse","posting_id":"1","req_id":"1","url":"https://boards.greenhouse.io/demo/jobs/1","title":title,"location":"Remote","work_arrangement":"Remote","compensation":"$150,000-$190,000","description":description,"department":"Solutions","created_at":"","updated_at":"1","is_listed":True}


class DirectSheetWorkflowTests(unittest.TestCase):
    def make(self, p=None):
        c=company(); p=p or posting()
        repo=MemoryRepository({"Companies":[c],"Job History":[],"Opportunities":[],"Scan Cycles":[]})
        state=State()
        engine=Engine(repo,state,fetcher=lambda *args: Inventory(status='complete',jobs=[p],reason='ok',source_url=c['Official Careers URL']))
        return c,p,repo,state,engine

    def test_title_rules(self):
        self.assertTrue(excluded_title("Systems Engineer"))
        self.assertTrue(excluded_title("Senior Staff Engineer, Survivability Materials"))
        self.assertTrue(excluded_title("Electrical Engineer"))
        self.assertTrue(excluded_title("Staff Solutions Engineer"))
        self.assertFalse(excluded_title("Field Applications Engineer"))

    def test_new_job_goes_to_sheet_review_queue(self):
        c,p,repo,state,engine=self.make()
        cycle=engine.start_cycle([c['Company ID']]); engine.resume(cycle)
        row=repo.read('Job History')[0]
        self.assertEqual(row['Review Status'],'Needs Review')
        self.assertEqual(state.reviews(cycle),[])
        state.close()

    def test_in_progress_row_is_skipped_by_scraper(self):
        c,p,repo,state,engine=self.make()
        engine._stage_posting({'id':'CYC'},c,p)
        claim=engine.claim_next_review()
        old=unpack_snapshot(repo.read('Job History')[0]['Current Snapshot'])['pending']['description']
        engine._stage_posting({'id':'CYC'},c,posting(description='VERSION TWO'))
        row=repo.read('Job History')[0]
        self.assertEqual(row['Review Status'],'In Progress')
        self.assertEqual(unpack_snapshot(row['Current Snapshot'])['pending']['description'],old)
        state.close()

    def test_accept_writes_history_and_opportunity(self):
        c,p,repo,state,engine=self.make()
        engine._stage_posting({'id':'CYC'},c,p)
        claim=engine.claim_next_review()
        engine.apply_ai_decision(claim,{"decision":"accept","fit_level":"Strong","narrative":"Strong integration fit.","base_max_usd":190000,"material_change":False,"evaluation_stage":"full_review","reviewer":"test"})
        row=repo.read('Job History')[0]
        self.assertEqual((row['Review Status'],row['Decision'],row['Fit Level']),('Reviewed','Accept','Strong'))
        self.assertEqual(len(repo.read('Opportunities')),1)
        state.close()

    def test_local_state_scrubs_jobs_and_can_purge_legacy_reviews(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'state.db'; state=State(path)
            cycle={'id':'C','status':'In Progress','companies':{'COMP-1':{'company':'Demo','stage':'inventory','jobs':[posting()]}}}
            state.save_cycle(cycle)
            state.put_review('C','K',{'job_key':'K','posting':posting()})
            self.assertNotIn('jobs',state.cycle('C')['companies']['COMP-1'])
            state.purge_reviews(); self.assertEqual(state.reviews('C'),[])
            state.close()

if __name__ == '__main__': unittest.main()
