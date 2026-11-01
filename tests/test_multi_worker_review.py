"""Offline safety tests for independent reviewers sharing one pass and outbox."""
from contextlib import contextmanager
import fcntl
import json
import multiprocessing
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from job_search_helper.review_runtime import Runtime, main
from job_search_helper.review_writeback import sync_pending, writeback, sheet_writer_lock
from job_search_helper.repository import MemoryRepository
from test_concurrent_review import job, publish, response


def process_worker(queue,barrier,reports):
    rt=Runtime(queue)
    try:
        owner=rt.start(2)["run_id"]
        barrier.wait(15)
        batch=rt.next(2,owner,10)["items"]
        barrier.wait(15)
        result=rt.submit(2,owner,[response(item,2,"ESCALATE") for item in batch])
        reports.put({"owner":owner,"keys":[item["job_key"] for item in batch],"saved":result["saved"]})
    except BaseException as exc:
        reports.put({"error":repr(exc)}); barrier.abort()
    finally: rt.close()


class MultiWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.queue=Path(self.temp.name)/"queue"
        publish(self.queue,second=[job(key=f"j{i:03}",description="Deploy customer systems") for i in range(50)])
        self.rt=Runtime(self.queue); self.addCleanup(self.rt.close); self.rt.sync()

    def test_five_separate_processes_claim_disjoint_batches(self):
        ctx=multiprocessing.get_context("spawn"); barrier=ctx.Barrier(5); reports=ctx.Queue()
        workers=[ctx.Process(target=process_worker,args=(self.queue,barrier,reports)) for _ in range(5)]
        try:
            for worker in workers: worker.start()
            results=[reports.get(timeout=25) for _ in workers]
            for worker in workers: worker.join(10)
            self.assertTrue(all(worker.exitcode==0 for worker in workers))
            self.assertFalse([r for r in results if "error" in r],results)
            keys=[key for result in results for key in result["keys"]]
            self.assertEqual(len({r["owner"] for r in results}),5)
            self.assertEqual(len(keys),50); self.assertEqual(len(set(keys)),50)
            self.assertEqual(sum(r["saved"] for r in results),50)
        finally:
            for worker in workers:
                if worker.is_alive(): worker.terminate(); worker.join(5)
            reports.close(); reports.join_thread()

    def test_five_simultaneous_workers_claim_and_submit_fifty_distinct_jobs(self):
        barrier=threading.Barrier(5); reports=[]; errors=[]
        def work():
            rt=Runtime(self.queue)
            try:
                owner=rt.start(2)["run_id"]; batches=[]
                for _ in range(2):
                    barrier.wait(10)
                    batch=rt.next(2,owner,5)["items"]
                    batches.extend(item["job_key"] for item in batch)
                    barrier.wait(10)
                    rt.submit(2,owner,[response(item,2,"ESCALATE") for item in batch])
                reports.append((owner,batches))
            except BaseException as exc:
                errors.append(exc); barrier.abort()
            finally: rt.close()
        workers=[threading.Thread(target=work) for _ in range(5)]
        for thread in workers: thread.start()
        for thread in workers: thread.join(20)
        self.assertFalse(any(t.is_alive() for t in workers)); self.assertFalse(errors,errors)
        self.assertEqual(len({owner for owner,_ in reports}),5)
        keys=[key for _,batch in reports for key in batch]
        self.assertEqual(len(keys),50); self.assertEqual(len(set(keys)),50)
        self.assertEqual(self.rt.status(2)["passes"]["2"]["done"],50)
        self.assertEqual(self.rt.status(3)["passes"]["3"]["ready"],50)
        for owner,_ in reports:
            self.assertEqual(self.rt.finish(2,owner)["state"],"DRAINED")
            checkpoint=json.loads(self.rt.checkpoint_path(2,owner).read_text())
            self.assertEqual(checkpoint["run_id"],owner)

    def test_new_run_and_resume_do_not_release_another_workers_batch(self):
        a=self.rt.start(2)["run_id"]; first=self.rt.next(2,a,5)["items"]
        b=self.rt.start(2)["run_id"]; second=self.rt.next(2,b,5)["items"]
        self.rt.start(2,b)
        resumed=self.rt.next(2,a,5)["items"]
        self.assertEqual(first,resumed)
        self.assertFalse({x["job_key"] for x in first}&{x["job_key"] for x in second})
        self.assertEqual(self.rt.status(2)["passes"]["2"]["claimed"],10)
        with self.assertRaises(RuntimeError): self.rt.submit(2,b,[response(first[0],2,"ESCALATE")])

    def test_pause_releases_only_this_workers_jobs_and_fences_old_results(self):
        a=self.rt.start(2)["run_id"]; old=self.rt.next(2,a,5)["items"]
        b=self.rt.start(2)["run_id"]; live=self.rt.next(2,b,5)["items"]
        self.rt.pause(2,a)
        self.assertEqual(self.rt.next(2,b,5)["items"],live)
        c=self.rt.start(2)["run_id"]; recovered=self.rt.next(2,c,5)["items"]
        self.assertEqual({x["job_key"] for x in old},{x["job_key"] for x in recovered})
        self.rt.start(2,a)
        with self.assertRaises(RuntimeError): self.rt.submit(2,a,[response(old[0],2,"ESCALATE")])
        self.rt.submit(2,b,[response(item,2,"ESCALATE") for item in live])

    def test_worker_crash_expiry_reclaims_jobs_and_rejects_late_submit(self):
        now=[100]; rt=Runtime(self.queue,clock=lambda:now[0],lease_seconds=10); self.addCleanup(rt.close)
        a=rt.start(2)["run_id"]; old=rt.next(2,a,5)["items"]
        now[0]=105; b=rt.start(2)["run_id"]; held=rt.next(2,b,5)["items"]
        now[0]=111; c=rt.start(2)["run_id"]; new=rt.next(2,c,5)["items"]
        self.assertEqual({x["job_key"] for x in old},{x["job_key"] for x in new})
        self.assertNotEqual(old[0]["claim_token"],new[0]["claim_token"])
        self.assertEqual(rt.next(2,b,5)["items"],held)
        rt.start(2,a)
        with self.assertRaises(RuntimeError): rt.submit(2,a,[response(old[0],2,"ESCALATE")])

    def test_heartbeat_extends_only_its_live_claims(self):
        now=[100]; rt=Runtime(self.queue,clock=lambda:now[0],lease_seconds=10); self.addCleanup(rt.close)
        a=rt.start(2)["run_id"]; rt.next(2,a,5)
        b=rt.start(2)["run_id"]; rt.next(2,b,5)
        now[0]=105; self.assertEqual(rt.heartbeat(2,a)["renewed_claims"],5)
        leases=dict(rt.db.execute("SELECT owner,MIN(lease_until) FROM tasks WHERE state='claimed' GROUP BY owner"))
        self.assertEqual(leases[a],115); self.assertEqual(leases[b],110)
        now[0]=116
        with self.assertRaises(RuntimeError): rt.heartbeat(2,a)

    def test_finish_waits_for_other_workers_and_only_drains_itself(self):
        publish(self.queue,second=[job(description="Full description")]); self.rt.sync()
        a=self.rt.start(2)["run_id"]; b=self.rt.start(2)["run_id"]
        item=self.rt.next(2,a)["items"][0]
        self.assertEqual(self.rt.next(2,b)["items"],[])
        self.assertEqual(self.rt.finish(2,b)["state"],"WAITING_WORKERS")
        self.rt.submit(2,a,[response(item,2,"ESCALATE")])
        self.assertEqual(self.rt.finish(2,b)["state"],"DRAINED")
        self.assertEqual([r["run_id"] for r in self.rt.status(2)["passes"]["2"]["active_runs"]],[a])
        self.assertEqual(self.rt.finish(2,a)["state"],"DRAINED")

    def test_downstream_waits_for_all_upstream_workers(self):
        publish(self.queue); self.rt.sync()
        a=self.rt.start(2)["run_id"]; b=self.rt.start(2)["run_id"]; c=self.rt.start(3)["run_id"]
        self.rt.finish(2,a)
        self.assertEqual(self.rt.finish(3,c)["state"],"WAITING_UPSTREAM")
        self.rt.finish(2,b)
        self.assertEqual(self.rt.finish(3,c)["state"],"DRAINED")

    def test_legacy_run_and_claim_survive_additive_upgrade_and_new_worker(self):
        owner="legacy-run"
        with self.rt.transaction():
            self.rt.db.execute("INSERT INTO runs VALUES(?,?,?,?,?)",(2,owner,"active",self.rt.clock()+1800,self.rt.clock()))
        old=self.rt.next(2,owner,5)["items"]
        new=self.rt.start(2)["run_id"]; next_items=self.rt.next(2,new,5)["items"]
        self.rt.start(2,owner)
        self.assertEqual(self.rt.next(2,owner,5)["items"],old)
        self.assertFalse({r["job_key"] for r in old}&{r["job_key"] for r in next_items})
        self.rt.submit(2,owner,[response(item,2,"ESCALATE") for item in old])
        self.rt.pause(2,owner)
        self.rt.submit(2,new,[response(item,2,"ESCALATE") for item in next_items])

    def test_unknown_or_wrong_pass_resume_is_refused(self):
        with self.assertRaises(ValueError): self.rt.start(2,"made-up-run")
        owner=self.rt.start(1)["run_id"]
        with self.assertRaises(ValueError): self.rt.start(2,owner)

    def test_changed_source_invalidates_only_affected_claim(self):
        publish(self.queue,second=[job(key="a",description="Full"),job(key="b",description="Full")]); self.rt.sync()
        a=self.rt.start(2)["run_id"]; b=self.rt.start(2)["run_id"]
        first=self.rt.next(2,a,1)["items"][0]; second=self.rt.next(2,b,1)["items"][0]
        publish(self.queue,second=[job(key="a",source="changed",description="New full"),job(key="b",description="Full")])
        with self.assertRaises(RuntimeError): self.rt.submit(2,a,[response(first,2,"ESCALATE")])
        self.rt.submit(2,b,[response(second,2,"ESCALATE")])

    def test_checkpoint_is_per_run_and_resume_is_idempotent(self):
        a=self.rt.start(2)["run_id"]; item=self.rt.next(2,a,1)["items"][0]
        original=self.rt.checkpoint_path(2,a).read_bytes()
        b=self.rt.start(2)["run_id"]; self.rt.next(2,b,1)
        self.assertEqual(self.rt.checkpoint_path(2,a).read_bytes(),original)
        answer=response(item,2,"ESCALATE"); self.rt.submit(2,a,[answer])
        self.assertEqual(self.rt.submit(2,a,[answer])["reused"],1)
        self.assertEqual(self.rt.status(2,a)["run"]["saved_assessments"],1)
        self.assertEqual(self.rt.status(2,b)["run"]["saved_assessments"],0)
        self.assertEqual(self.rt.status(2,a)["run"]["outcomes"],{"ESCALATE":1})
        self.assertEqual(self.rt.status(2,a)["run"]["delivery"],{"Handoff":1})


class ConcurrentWriterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.queue=Path(self.temp.name)/"queue"
        publish(self.queue,second=[job(description="Complete mismatch")])
        self.rt=Runtime(self.queue); self.addCleanup(self.rt.close); self.rt.sync()
        self.a=self.rt.start(2)["run_id"]; self.b=self.rt.start(2)["run_id"]
        item=self.rt.next(2,self.a)["items"][0]
        self.rt.submit(2,self.a,[response(item,2,"CLEAR_REJECT")])
        self.repo=MemoryRepository({"Job History":[{"Company":"Fixture","Job Title":"Test Engineer","Official Job URL":"https://example.com/jobs/one","Job Key":"j1","Source Hash":"h1","Added to Opportunities?":"Pending","Review Status":"Needs Review","Job Status":"Open and verified","Reconsideration Count":0,"Review Notes":"Personal note"}],"Opportunities":[]})

    def test_writer_lock_covers_verified_status_commit_and_loser_does_not_regress(self):
        real_transaction=self.rt.transaction; checked=[]; rt2=Runtime(self.queue); self.addCleanup(rt2.close)
        @contextmanager
        def transaction():
            # Once the Sheet changes, every later transaction must remain under lock
            # until delivery state is persisted. Try the second writer at this edge.
            if self.repo.read("Job History")[0]["Added to Opportunities?"]=="No" and not checked:
                state=json.loads(self.rt.db.execute("SELECT payload FROM decisions WHERE stage=2").fetchone()[0])["writeback_status"]
                if state=="Pending":
                    checked.append(sync_pending(rt2,2,self.b,repo=self.repo))
            with real_transaction(): yield
        with patch.object(self.rt,"transaction",side_effect=transaction):
            result=sync_pending(self.rt,2,self.a,repo=self.repo)
        self.assertEqual(result["counts"],{"Written":1})
        self.assertEqual(checked[0]["state"],"WRITEBACK_DEFERRED")
        self.assertEqual(sync_pending(rt2,2,self.b,repo=self.repo)["selected"],0)
        self.assertEqual(json.loads(self.rt.db.execute("SELECT payload FROM decisions WHERE stage=2").fetchone()[0])["writeback_status"],"Written")
        self.assertEqual(self.repo.read("Job History")[0]["Review Notes"].count("[second-pass"),1)

    def test_contending_bulk_and_single_writers_do_not_change_saved_status(self):
        with sheet_writer_lock(self.queue.parent/"writer.lock"):
            before=self.rt.db.execute("SELECT payload FROM decisions").fetchone()[0]
            self.assertEqual(sync_pending(self.rt,2,self.b,repo=self.repo)["state"],"WRITEBACK_DEFERRED")
            self.assertEqual(writeback(self.rt,2,self.b,"j1","h1",repo=self.repo)["state"],"WRITEBACK_DEFERRED")
            self.assertEqual(self.rt.db.execute("SELECT payload FROM decisions").fetchone()[0],before)
        self.assertEqual(sync_pending(self.rt,2,self.a,repo=self.repo)["counts"],{"Written":1})

    def test_uncertain_delivery_retries_without_duplicate_notes(self):
        commit=self.repo.commit
        def uncertain(operations):
            commit(operations); raise RuntimeError("Response lost")
        with patch.object(self.repo,"commit",side_effect=uncertain):
            self.assertEqual(sync_pending(self.rt,2,self.a,repo=self.repo)["counts"],{"Written":1})
        self.assertEqual(sync_pending(self.rt,2,self.b,repo=self.repo)["selected"],0)
        self.assertEqual(self.repo.read("Job History")[0]["Review Notes"].count("[second-pass"),1)


if __name__=="__main__": unittest.main()
