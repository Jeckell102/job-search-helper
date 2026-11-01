"""Offline concurrency and writeback tests; no live data or network access."""
import fcntl
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from job_search_helper.review_runtime import Runtime,atomic_json,publication_lock,LOGS
from job_search_helper.review_writeback import sync_clear_rejects,writeback
from job_search_helper.repository import MemoryRepository

def job(key="j1",source="h1",score=10,description=None):
    row={"job_key":key,"source_hash":source,"job_title":"Field Solutions Engineer","score":score,"row_number":2,"company":"Never expose this employer"}
    if description is not None: row["job_description"]=description
    return row

def publish(queue,first=(),second=()):
    with publication_lock(queue,exclusive=True):
        for name,rows in (("first-pass.jsonl",first),("second-pass.jsonl",second)):
            atomic_json(queue/name,list(rows),lines=True)
        hashes={name:hashlib.sha256((queue/name).read_bytes()).hexdigest() for name in ("first-pass.jsonl","second-pass.jsonl")}
        atomic_json(queue/"summary.json",{"generated_at":"fixture","file_sha256":hashes})

def response(item,stage,decision):
    base={k:item[k] for k in ("job_key","source_hash","claim_token","input_version")}
    base["reason"]="Specific model assessment fixture"
    if stage==1: base["decision"]=decision
    elif stage==2:
        base.update(triage_decision=decision,description_complete=decision!="NEEDS_INFO",evidence_source="fixture",evidence_locator="fixture/description",policy_conflicts=[])
        if decision=="ESCALATE": base["evidence_packet"]={"core_responsibilities":["Deploy and integrate customer systems"]}
    else: base.update(decision=decision,fit_level="Strong" if decision=="Accept" else None,policy_conflicts=[])
    return base

class ConcurrentReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.queue=Path(self.temp.name)/"queue"; publish(self.queue)
        self.rt=Runtime(self.queue); self.addCleanup(self.rt.close)
    def start(self,stage):
        self.rt.sync(); return self.rt.start(stage)["run_id"]
    def test_three_stages_can_own_runs_simultaneously(self):
        owners=[]; errors=[]; barrier=threading.Barrier(3)
        def begin(stage):
            rt=Runtime(self.queue)
            try:
                barrier.wait(); owners.append(rt.start(stage)["run_id"])
            except BaseException as e: errors.append(e)
            finally: rt.close()
        threads=[threading.Thread(target=begin,args=(i,)) for i in (1,2,3)]
        for t in threads: t.start()
        for t in threads: t.join(10)
        self.assertFalse(errors); self.assertEqual(len(owners),3)
    def test_submit_retry_is_idempotent(self):
        publish(self.queue,[job()]); owner=self.start(1)
        item=self.rt.next(1,owner)["items"][0]; answer=response(item,1,"RESCUE")
        self.assertEqual(self.rt.submit(1,owner,[answer])["saved"],1)
        repeated=self.rt.submit(1,owner,[answer])
        self.assertEqual(repeated["saved"],0); self.assertEqual(repeated["reused"],1)
        self.assertEqual(self.rt.status(1)["passes"]["1"]["done"],1)
    def test_legacy_writeback_progress_is_not_an_assessment_conflict(self):
        legacy={"job_key":"j1","source_hash":"h1","decision":"Accept","fit_level":"Strong","reason":"Specific existing assessment","writeback_status":"Pending"}
        atomic_json(self.queue/LOGS[3],[legacy],lines=True); self.rt.sync()
        updated=dict(legacy,writeback_status="Written",writeback_detail="Verified")
        with self.rt.transaction():
            self.rt.db.execute("UPDATE decisions SET payload=? WHERE stage=3",(json.dumps(updated),))
        self.rt.sync()
        self.assertEqual(self.rt.db.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0],0)
        saved=json.loads(self.rt.db.execute("SELECT payload FROM decisions WHERE stage=3").fetchone()[0])
        self.assertEqual(saved["writeback_status"],"Written")
    def test_second_owner_of_same_pass_gets_independent_run(self):
        owner=self.start(2)
        other=self.rt.start(2)["run_id"]
        self.assertNotEqual(owner,other)
        self.assertEqual(self.rt.start(2,owner)["run_id"],owner)
    def test_handoffs_only_after_committed_upstream_results(self):
        publish(self.queue,[job()]); a=self.start(1); b=self.start(2); c=self.start(3)
        self.assertEqual(self.rt.next(2,b)["items"],[])
        item=self.rt.next(1,a)["items"][0]
        self.assertNotIn("company",item)
        self.rt.submit(1,a,[response(item,1,"RESCUE")])
        item2=self.rt.next(2,b)["items"][0]
        self.assertEqual(self.rt.next(3,c)["items"],[])
        self.rt.submit(2,b,[response(item2,2,"ESCALATE")])
        item3=self.rt.next(3,c)["items"][0]
        self.assertNotIn("company",item3); self.assertIn("evidence_packet",item3)
        self.assertEqual(self.rt.status(1)["passes"]["1"]["done"],1)
    def test_clear_reject_does_not_reach_third_pass(self):
        publish(self.queue,[],[job(description="Description")]); a=self.start(2); b=self.start(3)
        item=self.rt.next(2,a)["items"][0]; self.rt.submit(2,a,[response(item,2,"CLEAR_REJECT")])
        self.assertEqual(self.rt.next(3,b)["items"],[])
    def test_finish_rechecks_added_jobs_instead_of_one_batch(self):
        publish(self.queue,[job(str(i),str(i)) for i in range(6)])
        owner=self.start(1)
        for _ in range(3):
            batch=self.rt.next(1,owner,2)["items"]
            self.assertEqual(len(batch),2)
            self.rt.submit(1,owner,[response(item,1,"PASS") for item in batch])
        publish(self.queue,[job(str(i),str(i)) for i in range(7)])
        self.assertEqual(self.rt.finish(1,owner)["state"],"CONTINUE")
        batch=self.rt.next(1,owner)["items"]; self.assertEqual(len(batch),1)
        self.rt.submit(1,owner,[response(batch[0],1,"PASS")])
        self.assertEqual(self.rt.finish(1,owner)["state"],"WRITEBACK_PENDING")
        self.assertEqual(self.rt.status(1)["passes"]["1"]["pending_writeback"],7)
    def test_empty_consumer_waits_for_active_upstream(self):
        a=self.start(1); b=self.start(2)
        self.assertEqual(self.rt.finish(2,b)["state"],"WAITING_UPSTREAM")
        self.rt.finish(1,a)
        self.assertEqual(self.rt.finish(2,b)["state"],"DRAINED")
    def test_changed_hash_invalidates_old_claim(self):
        publish(self.queue,[job()]); owner=self.start(1); item=self.rt.next(1,owner)["items"][0]
        publish(self.queue,[job(source="h2")])
        with self.assertRaises(RuntimeError): self.rt.submit(1,owner,[response(item,1,"PASS")])
        self.assertEqual(self.rt.next(1,owner)["items"][0]["source_hash"],"h2")
    def test_generation_mismatch_is_not_empty_queue(self):
        publish(self.queue,[job()]); self.start(1); (self.queue/"first-pass.jsonl").write_text("")
        with self.assertRaises(RuntimeError): self.rt.sync()
    def test_legacy_decisions_preserved_and_reused(self):
        publish(self.queue,[job()]); path=self.queue/LOGS[1]
        atomic_json(path,[{"job_key":"j1","source_hash":"h1","decision":"RESCUE","reason":"Existing result"}],lines=True)
        before=path.read_bytes(); owner=self.start(1)
        self.assertEqual(self.rt.next(1,owner)["items"],[])
        self.assertEqual(self.rt.status(2)["passes"]["2"]["ready"],1)
        self.assertEqual(path.read_bytes(),before)
    def test_conflicting_duplicate_legacy_decisions_are_quarantined(self):
        publish(self.queue,[job()]); path=self.queue/LOGS[1]
        atomic_json(path,[{"job_key":"j1","source_hash":"h1","decision":x,"reason":"Fixture"} for x in ("RESCUE","PASS")],lines=True)
        owner=self.start(1)
        self.assertEqual(self.rt.next(1,owner)["items"],[])
        self.assertEqual(self.rt.status(1)["passes"]["1"]["conflicts"],1)
    def test_expired_claim_cannot_write_over_new_owner(self):
        now=[0]; rt=Runtime(self.queue,clock=lambda:now[0],lease_seconds=10); self.addCleanup(rt.close)
        publish(self.queue,[job()]); rt.sync(); a=rt.start(1)["run_id"]; old=rt.next(1,a)["items"][0]
        now[0]=11; b=rt.start(1)["run_id"]; new=rt.next(1,b)["items"][0]
        self.assertNotEqual(old["claim_token"],new["claim_token"])
        with self.assertRaises(RuntimeError): rt.submit(1,a,[response(old,1,"PASS")])
    def test_withdrawn_item_can_return_without_losing_others(self):
        publish(self.queue,[job()]); self.rt.sync(); publish(self.queue); self.rt.sync()
        publish(self.queue,[job()]); self.rt.sync()
        self.assertEqual(self.rt.status(1)["passes"]["1"]["ready"],1)

class WritebackTests(ConcurrentReviewTests):
    def test_second_pass_clear_reject_bulk_sync_is_verified(self):
        description="Primary production test and inspection work."
        publish(self.queue,[],[job(description=description)])
        owner=self.start(2); item=self.rt.next(2,owner)["items"][0]
        self.rt.submit(2,owner,[response(item,2,"CLEAR_REJECT")])
        repo=MemoryRepository({"Job History":[{"Company":"Fixture","Job Title":"Test Engineer","Official Job URL":"https://example.com/jobs/one","Job Key":"j1","Source Hash":"h1","Added to Opportunities?":"Pending","Review Status":"Needs Review","Review Started At":"","Decision":"","Description Hash":"","Job Status":"Open and verified","Reconsideration Count":0,"Reconsideration Status":"Eligible","Review Notes":"Personal note","Location":"Cleveland, Ohio, United States","Salary / Range":"$150,000 annual base"}],"Opportunities":[]})
        result=sync_clear_rejects(self.rt,owner,25,repo=repo)
        self.assertEqual(result["counts"],{"Written":1},result)
        row=repo.read("Job History")[0]
        self.assertEqual((row["Review Status"],row["Decision"],row["Fit Level"],row["Added to Opportunities?"]),("Reviewed","Reject","","No"))
        self.assertEqual(row["Description Hash"],"h1")
        self.assertIn("[second-pass",row["Review Notes"])

    def prepare(self):
        description="Deploy and integrate customer hardware and software."
        publish(self.queue,[],[job(score=25,description=description)])
        a=self.start(2); item=self.rt.next(2,a)["items"][0]; self.rt.submit(2,a,[response(item,2,"ESCALATE")])
        b=self.start(3); item=self.rt.next(3,b)["items"][0]; answer=response(item,3,"Accept")
        answer["location_check"]={"status":"verified_us","source_value":"Cleveland, Ohio, United States","evidence":"Posting specifies Cleveland, Ohio, United States"}
        self.rt.submit(3,b,[answer])
        repo=MemoryRepository({"Job History":[{"Company":"Fixture","Job Title":"Field Solutions Engineer","Official Job URL":"https://example.com/jobs/one","Job Key":"j1","Source Hash":"h1","Added to Opportunities?":"Pending","Review Status":"Needs Review","Job Status":"Open and verified","Reconsideration Count":0,"Reconsideration Status":"Eligible","Review Notes":"Personal note","Current Snapshot":"do-not-touch","Location":"Cleveland, Ohio, United States","Salary / Range":"$150,000 annual base","Last Checked":"2026-09-27"}],"Opportunities":[],"Job Evidence":[{"Job Key":"j1","Source Hash":"h1","Job Description":description}]})
        return b,repo
    def test_writeback_is_verified_and_idempotent(self):
        owner,repo=self.prepare(); result=writeback(self.rt,owner,"j1","h1",repo=repo)
        self.assertEqual(result["writeback_status"],"Written",result)
        self.assertEqual(repo.read("Job History")[0]["Current Snapshot"],"do-not-touch")
        self.assertEqual(repo.read("Job History")[0]["Added to Opportunities?"],"Yes")
        self.assertEqual(len(repo.read("Opportunities")),1)
        self.assertEqual(repo.read("Opportunities")[0]["Notes"],"")
        writeback(self.rt,owner,"j1","h1",repo=repo)
        self.assertEqual(repo.read("Job History")[0]["Review Notes"].count("[third-pass"),1)
        self.assertEqual(len(repo.read("Opportunities")),1)
    def test_existing_opportunity_personal_notes_are_unchanged(self):
        owner,repo=self.prepare()
        notes="Contact knows my background.\n\nPersonal follow-up: confirm team travel."
        repo=MemoryRepository({**repo.tables,"Opportunities":[{
            "Company":"Fixture","Job Title":"Earlier title","Job URL":"https://example.com/jobs/one",
            "Fit Review":"Potential Fit","Notes":notes,"Application Status":"Applied",
            "Date Applied":"2026-09-20","Date Found":"2026-09-18"}]})
        result=writeback(self.rt,owner,"j1","h1",repo=repo)
        self.assertEqual(result["writeback_status"],"Written",result)
        row=repo.read("Opportunities")[0]
        self.assertEqual(row["Notes"],notes)
        self.assertEqual(row["Fit Review"],"Strong Potential Fit")
        self.assertEqual(row["Application Status"],"Applied")
        self.assertEqual(row["Date Applied"],"2026-09-20")
        self.assertEqual(row["Date Found"],"2026-09-18")
        writeback(self.rt,owner,"j1","h1",repo=repo)
        self.assertEqual(repo.read("Opportunities")[0]["Notes"],notes)
        self.assertEqual(len(repo.read("Opportunities")),1)
    def test_unverified_old_intent_cannot_replay_personal_notes_write(self):
        owner,repo=self.prepare()
        with patch.object(repo,"commit",side_effect=RuntimeError("Offline write failed")):
            self.assertEqual(writeback(self.rt,owner,"j1","h1",repo=repo)["writeback_status"],"Pending")
        # Simulate a saved pre-fix intent in this test's temporary runtime only.
        with self.rt.transaction():
            saved=self.rt.db.execute("SELECT payload FROM writeback WHERE job_key=? AND source_hash=?",("j1","h1")).fetchone()
            intent=json.loads(saved[0])
            for operation in intent["operations"]:
                if operation["tab"]=="Opportunities": operation["append_notes"]={"Notes":"Old AI review note"}
            self.rt.db.execute("UPDATE writeback SET payload=? WHERE job_key=? AND source_hash=?",(json.dumps(intent),"j1","h1"))
        before=repo.tables
        with patch.object(repo,"commit",wraps=repo.commit) as commit:
            result=writeback(self.rt,owner,"j1","h1",repo=repo)
            commit.assert_not_called()
        self.assertEqual(result["writeback_status"],"Conflict",result)
        self.assertIn("personal Opportunities Notes",result["detail"])
        self.assertEqual(repo.tables,before)
    def test_manual_no_is_not_overwritten(self):
        owner,repo=self.prepare()
        repo.commit([{"tab":"Job History","identity":{"Job Key":"j1"},"values":{"Added to Opportunities?":"No"}}])
        result=writeback(self.rt,owner,"j1","h1",repo=repo)
        self.assertEqual(result["writeback_status"],"Conflict")
        self.assertEqual(repo.read("Job History")[0]["Added to Opportunities?"],"No")
        self.assertEqual(repo.read("Opportunities"),[])
    def test_scraper_writer_lock_stages_instead_of_racing(self):
        owner,repo=self.prepare(); lock=self.queue.parent/"writer.lock"
        with lock.open("a") as handle:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=writeback(self.rt,owner,"j1","h1",repo=repo)
            self.assertEqual(result["writeback_status"],"Pending")
            self.assertEqual(repo.read("Opportunities"),[])
    def test_uncertain_write_reconciles_without_duplicate(self):
        owner,repo=self.prepare(); commit=repo.commit
        def uncertain(operations):
            commit(operations); raise RuntimeError("Network response lost after successful write")
        with patch.object(repo,"commit",side_effect=uncertain):
            self.assertEqual(writeback(self.rt,owner,"j1","h1",repo=repo)["writeback_status"],"Pending")
        self.assertEqual(writeback(self.rt,owner,"j1","h1",repo=repo)["writeback_status"],"Written")
        self.assertEqual(len(repo.read("Opportunities")),1)
        self.assertEqual(repo.read("Job History")[0]["Review Notes"].count("[third-pass"),1)

if __name__=="__main__": unittest.main()
