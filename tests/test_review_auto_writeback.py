"""End-to-end delivery of persisted review decisions without a live Sheet."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.repository import MemoryRepository
from job_search_helper.review_runtime import LOGS, Runtime, atomic_json, main
from job_search_helper.review_writeback import sync_pending, writeback
from test_concurrent_review import job, publish, response


class ReviewDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.queue=Path(self.temp.name)/"queue"
        publish(self.queue)
        self.runtime=Runtime(self.queue); self.addCleanup(self.runtime.close)

    def repository(self,keys):
        return MemoryRepository({"Job History":[{
            "Company":"Fixture", "Job Title":"Field Solutions Engineer",
            "Official Job URL":f"https://example.com/jobs/{key}",
            "Job Key":key, "Source Hash":"h1", "Added to Opportunities?":"Pending",
            "Review Status":"Needs Review", "Job Status":"Open and verified",
            "Reconsideration Count":0, "Reconsideration Status":"Eligible",
            "Review Notes":"Personal history note", "Current Snapshot":"unchanged",
            "Location":"Cleveland, Ohio, United States", "Salary / Range":"$150,000 annual base",
            "Last Checked":"2026-09-28", "Work Arrangement":"Hybrid",
        } for key in keys], "Opportunities":[]})

    def claim(self,stage,keys):
        publish(self.queue,second=[job(key=key,description="Deploy and integrate customer hardware and software.") for key in keys])
        self.runtime.sync()
        owner2=self.runtime.start(2)["run_id"]
        items=self.runtime.next(2,owner2,len(keys))["items"]
        if stage==2: return owner2,items
        self.runtime.submit(2,owner2,[response(item,2,"ESCALATE") for item in items])
        owner3=self.runtime.start(3)["run_id"]
        return owner3,self.runtime.next(3,owner3,len(keys))["items"]

    def assess(self,owner,items,decisions):
        answers=[]
        for item,decision in zip(items,decisions):
            answer=response(item,3,decision)
            if decision=="Accept":
                answer["location_check"]={"status":"verified_us", "source_value":"Cleveland, Ohio, United States", "evidence":"Explicit posting location"}
            answers.append(answer)
        self.runtime.submit(3,owner,answers)

    def cli(self,args,repo):
        output=io.StringIO()
        with patch("job_search_helper.runner._load_environment"), patch("job_search_helper.cli.get_repository",return_value=repo), redirect_stdout(output):
            code=main([*args,"--queue-dir",str(self.queue)])
        self.assertEqual(code,0,output.getvalue())
        return json.loads(output.getvalue())

    def test_legacy_reject_and_needs_info_are_delivered_and_counted(self):
        publish(self.queue,second=[job(key=key) for key in ("no","manual")])
        atomic_json(self.queue/LOGS[2],[
            {"job_key":"no","source_hash":"h1","triage_decision":"CLEAR_REJECT","reason":"Complete assessment rejects this role"},
            {"job_key":"manual","source_hash":"h1","triage_decision":"NEEDS_INFO","reason":"Missing source description"},
        ],lines=True)
        self.runtime.sync(); owner=self.runtime.start(2)["run_id"]
        self.assertEqual(self.runtime.status(2)["passes"]["2"]["pending_writeback"],2)
        repo=self.repository(["no","manual"])
        result=sync_pending(self.runtime,2,owner,repo=repo)
        self.assertEqual(result["counts"],{"Written":2})
        rows={r["Job Key"]:r for r in repo.read("Job History")}
        self.assertEqual((rows["no"]["Added to Opportunities?"],rows["no"]["Review Status"]),("No","Reviewed"))
        self.assertEqual((rows["manual"]["Added to Opportunities?"],rows["manual"]["Review Status"]),("Manual Review","Manual Review"))
        self.assertEqual(self.runtime.finish(2,owner)["state"],"DRAINED_WITH_EXCEPTIONS")

    def test_third_pass_mixed_batch_writes_once_and_verifies_opportunity(self):
        owner,items=self.claim(3,["accept","reject","manual"])
        self.assess(owner,items,["Accept","Reject","Needs Info"])
        repo=self.repository(["accept","reject","manual"])
        with patch.object(repo,"commit",wraps=repo.commit) as commit:
            result=sync_pending(self.runtime,3,owner,repo=repo)
        self.assertEqual(result["counts"],{"Written":3}); self.assertEqual(commit.call_count,1)
        rows={r["Job Key"]:r for r in repo.read("Job History")}
        for item,decision in zip(items,["Yes","No","Yes"]):
            self.assertEqual(rows[item["job_key"]]["Added to Opportunities?"],decision)
            self.assertEqual(rows[item["job_key"]]["Current Snapshot"],"unchanged")
        self.assertEqual(len(repo.read("Opportunities")),2)
        self.assertEqual(repo.read("Opportunities")[0]["Notes"],"")
        self.assertEqual(sync_pending(self.runtime,3,owner,repo=repo)["selected"],0)

    def test_older_saved_third_manual_intent_retries_as_opportunity(self):
        owner,items=self.claim(3,["manual"])
        self.assess(owner,items,["Needs Info"])
        repo=self.repository(["manual"])
        with patch.object(repo,"commit",side_effect=RuntimeError("Connection unavailable")):
            self.assertEqual(sync_pending(self.runtime,3,owner,repo=repo)["counts"],{"Pending":1})
        saved=self.runtime.db.execute("SELECT payload FROM writeback WHERE job_key='manual'").fetchone()
        intent=json.loads(saved[0]); intent.pop("requires_opportunity"); intent.pop("pass")
        intent["history_values"].update({"Added to Opportunities?":"Pending","Review Status":"Manual Review"})
        intent["operations"]=intent["operations"][:1]
        intent["operations"][0]["values"]=intent["history_values"]
        intent["opportunity_values"]={}
        with self.runtime.transaction():
            self.runtime.db.execute("UPDATE writeback SET payload=? WHERE job_key='manual'",(json.dumps(intent),))
        self.assertEqual(sync_pending(self.runtime,3,owner,repo=repo)["counts"],{"Written":1})
        row=repo.read("Job History")[0]
        self.assertEqual((row["Added to Opportunities?"],row["Review Status"]),("Yes","Reviewed"))
        self.assertEqual(len(repo.read("Opportunities")),1)

    def test_manual_review_choice_blocks_saved_rejection(self):
        owner,items=self.claim(2,["manual"])
        self.runtime.submit(2,owner,[response(items[0],2,"CLEAR_REJECT")])
        repo=self.repository(["manual"])
        repo.commit([{"tab":"Job History","identity":{"Job Key":"manual"},"values":{"Added to Opportunities?":"Manual Review"}}])
        before=repo.read("Job History")
        self.assertEqual(sync_pending(self.runtime,2,owner,repo=repo)["counts"],{"Conflict":1})
        self.assertEqual(repo.read("Job History"),before)

    def test_stale_source_and_manual_choice_do_not_block_other_jobs(self):
        owner,items=self.claim(2,["stale","manual","valid"])
        self.runtime.submit(2,owner,[response(item,2,"CLEAR_REJECT") for item in items])
        repo=self.repository(["stale","manual","valid"])
        repo.commit([{"tab":"Job History","identity":{"Job Key":"stale"},"values":{"Source Hash":"new"}},
                     {"tab":"Job History","identity":{"Job Key":"manual"},"values":{"Added to Opportunities?":"Yes"}}])
        result=sync_pending(self.runtime,2,owner,repo=repo)
        self.assertEqual(result["counts"],{"Conflict":2,"Written":1})
        rows={r["Job Key"]:r for r in repo.read("Job History")}
        self.assertEqual(rows["valid"]["Added to Opportunities?"],"No")
        self.assertEqual(rows["manual"]["Added to Opportunities?"],"Yes")
        self.assertEqual(rows["stale"]["Added to Opportunities?"],"Pending")

    def test_uncertain_batch_response_is_reconciled_by_readback(self):
        owner,items=self.claim(3,["accept"]); self.assess(owner,items,["Accept"])
        repo=self.repository(["accept"]); commit=repo.commit
        def uncertain(operations):
            commit(operations); raise RuntimeError("Response lost")
        with patch.object(repo,"commit",side_effect=uncertain):
            self.assertEqual(sync_pending(self.runtime,3,owner,repo=repo)["counts"],{"Written":1})
        self.assertEqual(sync_pending(self.runtime,3,owner,repo=repo)["selected"],0)
        self.assertEqual(len(repo.read("Opportunities")),1)

    def test_saved_intent_conflict_does_not_block_unrelated_retry(self):
        owner,items=self.claim(2,["changed","valid"])
        self.runtime.submit(2,owner,[response(item,2,"CLEAR_REJECT") for item in items])
        repo=self.repository(["changed","valid"])
        with patch.object(repo,"commit",side_effect=RuntimeError("Connection unavailable")):
            self.assertEqual(sync_pending(self.runtime,2,owner,repo=repo)["counts"],{"Pending":2})
        repo.commit([{"tab":"Job History","identity":{"Job Key":"changed"},"values":{"Review Notes":"New personal edit"}}])
        result=sync_pending(self.runtime,2,owner,repo=repo)
        self.assertEqual(result["counts"],{"Conflict":1,"Written":1})
        self.assertEqual(repo.read("Job History")[0]["Review Notes"],"New personal edit")

    def test_cli_submit_delivers_only_submitted_batch(self):
        owner,items=self.claim(2,["old","new"])
        self.runtime.submit(2,owner,[response(items[0],2,"CLEAR_REJECT")])
        path=Path(self.temp.name)/"answers.jsonl"
        atomic_json(path,[response(items[1],2,"CLEAR_REJECT")],lines=True)
        repo=self.repository(["old","new"])
        result=self.cli(["submit","--pass","2","--run-id",owner,"--file",str(path)],repo)
        self.assertEqual(result["writeback"]["counts"],{"Written":1})
        self.assertEqual(result["next_action"],"WRITEBACK_PENDING")
        rows={r["Job Key"]:r for r in repo.read("Job History")}
        self.assertEqual(rows[items[0]["job_key"]]["Added to Opportunities?"],"Pending")
        self.assertEqual(rows[items[1]["job_key"]]["Added to Opportunities?"],"No")

    def test_cli_third_pass_submit_automatically_delivers(self):
        owner,items=self.claim(3,["reject"])
        path=Path(self.temp.name)/"answers.jsonl"; atomic_json(path,[response(items[0],3,"Reject")],lines=True)
        repo=self.repository(["reject"])
        result=self.cli(["submit","--pass","3","--run-id",owner,"--file",str(path)],repo)
        self.assertEqual(result["writeback"]["counts"],{"Written":1})
        self.assertEqual(result["next_action"],"NEXT_BATCH")
        self.assertEqual(repo.read("Job History")[0]["Added to Opportunities?"],"No")

    def test_local_only_submit_stages_and_explicit_batch_retry_delivers(self):
        owner,items=self.claim(2,["no"])
        path=Path(self.temp.name)/"answers.jsonl"; atomic_json(path,[response(items[0],2,"CLEAR_REJECT")],lines=True)
        repo=self.repository(["no"])
        result=self.cli(["submit","--pass","2","--run-id",owner,"--file",str(path),"--local-only"],repo)
        self.assertEqual(result["next_action"],"WRITEBACK_PENDING")
        self.assertEqual(repo.read("Job History")[0]["Added to Opportunities?"],"Pending")
        self.assertEqual(self.runtime.finish(2,owner)["state"],"WRITEBACK_PENDING")
        result=self.cli(["writeback","--pass","2","--run-id",owner],repo)
        self.assertEqual(result["counts"],{"Written":1})

    def test_finish_retries_bounded_backlog_before_completion(self):
        owner,items=self.claim(3,["one","two"]); self.assess(owner,items,["Reject","Reject"])
        repo=self.repository(["one","two"])
        with patch("job_search_helper.review_runtime.live_refresh"):
            result=self.cli(["finish","--pass","3","--run-id",owner,"--limit","1"],repo)
        self.assertEqual(result["writeback"]["counts"],{"Written":1})
        self.assertEqual(result["state"],"WRITEBACK_PENDING")

    def test_conflicting_legacy_assessments_are_not_written_or_hidden(self):
        publish(self.queue,second=[job()])
        atomic_json(self.queue/LOGS[2],[{"job_key":"j1","source_hash":"h1","triage_decision":decision,"reason":"Assessment"} for decision in ("CLEAR_REJECT","NEEDS_INFO")],lines=True)
        self.runtime.sync(); owner=self.runtime.start(2)["run_id"]
        repo=self.repository(["j1"])
        self.assertEqual(sync_pending(self.runtime,2,owner,repo=repo)["selected"],0)
        self.assertEqual(repo.read("Job History")[0]["Added to Opportunities?"],"Pending")
        self.assertGreater(self.runtime.status(2)["passes"]["2"]["deferred"],0)

    def test_reject_preserves_only_already_dismissed_opportunity(self):
        for status,fit,expected in [("Not Interested","Unlikely Fit","Written"),("Applied","Unlikely Fit","Conflict"),("Not Interested","Potential Fit","Conflict")]:
            with self.subTest(status=status,fit=fit):
                key=status+fit
                owner,items=self.claim(2,[key])
                self.runtime.submit(2,owner,[response(items[0],2,"CLEAR_REJECT")])
                repo=self.repository([key])
                repo=MemoryRepository({**repo.tables,"Opportunities":[{"Company":"Fixture","Job Title":"Old title","Job URL":f"https://example.com/jobs/{key}","Application Status":status,"Fit Review":fit,"Notes":"Preserve me"}]})
                before=repo.read("Opportunities")
                result=sync_pending(self.runtime,2,owner,repo=repo)
                self.assertEqual(result["counts"],{expected:1})
                self.assertEqual(repo.read("Opportunities"),before)
                self.runtime.pause(2,owner)

    def test_first_pass_legacy_pass_writes_title_only_no_and_rescue_stays_pending(self):
        publish(self.queue,first=[job(key=key) for key in ("pass","rescue")])
        atomic_json(self.queue/LOGS[1],[{"job_key":key,"source_hash":"h1","decision":decision,"reason":"Title screen result"} for key,decision in (("pass","PASS"),("rescue","RESCUE"))],lines=True)
        self.runtime.sync(); owner=self.runtime.start(1)["run_id"]
        repo=self.repository(["pass","rescue"])
        result=sync_pending(self.runtime,1,owner,repo=repo)
        self.assertEqual(result["counts"],{"Written":1})
        rows={r["Job Key"]:r for r in repo.read("Job History")}
        self.assertEqual(rows["pass"]["Added to Opportunities?"],"No")
        self.assertEqual(rows["pass"]["Description Hash"],"")
        self.assertEqual(rows["pass"]["Review Status"],"Reviewed")
        self.assertIn("Title-only review",rows["pass"]["Rejection Reason"])
        self.assertIn("[first-pass",rows["pass"]["Review Notes"])
        self.assertEqual(rows["rescue"]["Added to Opportunities?"],"Pending")

    def test_existing_no_is_terminal_preserved_without_claiming_our_write(self):
        owner,items=self.claim(2,["no"])
        self.runtime.submit(2,owner,[response(items[0],2,"CLEAR_REJECT")])
        repo=self.repository(["no"])
        repo.commit([{"tab":"Job History","identity":{"Job Key":"no"},"values":{"Added to Opportunities?":"No"}}])
        before=repo.tables
        result=sync_pending(self.runtime,2,owner,repo=repo)
        self.assertEqual(result["counts"],{"Preserved":1})
        self.assertEqual(repo.tables,before)
        self.assertEqual(self.runtime.status(2)["passes"]["2"]["pending_writeback"],0)

    def test_single_writeback_cannot_bypass_legacy_assessment_conflict(self):
        publish(self.queue,second=[job()])
        atomic_json(self.queue/LOGS[2],[{"job_key":"j1","source_hash":"h1","triage_decision":decision,"reason":"Assessment"} for decision in ("CLEAR_REJECT","NEEDS_INFO")],lines=True)
        self.runtime.sync(); owner=self.runtime.start(2)["run_id"]
        repo=self.repository(["j1"])
        self.assertEqual(writeback(self.runtime,2,owner,"j1","h1",repo=repo)["writeback_status"],"Conflict")
        self.assertEqual(repo.read("Job History")[0]["Added to Opportunities?"],"Pending")

    def test_dismissed_opportunity_edit_between_plan_and_commit_blocks_history_write(self):
        owner,items=self.claim(2,["no"])
        self.runtime.submit(2,owner,[response(items[0],2,"CLEAR_REJECT")])
        repo=self.repository(["no"])
        repo=MemoryRepository({**repo.tables,"Opportunities":[{"Company":"Fixture","Job URL":"https://example.com/jobs/no","Application Status":"Not Interested","Fit Review":"Unlikely Fit","Notes":"Preserve me"}]})
        commit=repo.commit
        def concurrently_changed(operations):
            changed=repo.read("Opportunities"); changed[0]["Application Status"]="Applied"
            repo._sheets["Opportunities"]=MemoryRepository({"Opportunities":changed})._sheets["Opportunities"]
            return commit(operations)
        with patch.object(repo,"commit",side_effect=concurrently_changed):
            result=sync_pending(self.runtime,2,owner,repo=repo)
        self.assertEqual(result["counts"],{"Pending":1})
        self.assertEqual(repo.read("Job History")[0]["Added to Opportunities?"],"Pending")
        self.assertEqual(repo.read("Opportunities")[0]["Application Status"],"Applied")

    def test_saved_reject_intent_rechecks_new_active_opportunity(self):
        owner,items=self.claim(2,["no"])
        self.runtime.submit(2,owner,[response(items[0],2,"CLEAR_REJECT")])
        repo=self.repository(["no"])
        with patch.object(repo,"commit",side_effect=RuntimeError("Connection unavailable")):
            self.assertEqual(sync_pending(self.runtime,2,owner,repo=repo)["counts"],{"Pending":1})
        repo=MemoryRepository({**repo.tables,"Opportunities":[{"Company":"Fixture","Job URL":"https://example.com/jobs/no","Application Status":"Applied","Fit Review":"Potential Fit"}]})
        self.assertEqual(sync_pending(self.runtime,2,owner,repo=repo)["counts"],{"Conflict":1})
        self.assertEqual(repo.read("Job History")[0]["Added to Opportunities?"],"Pending")
        self.assertEqual(writeback(self.runtime,2,owner,"no","h1",repo=repo)["writeback_status"],"Conflict")
        self.assertEqual(repo.read("Job History")[0]["Added to Opportunities?"],"Pending")

    def test_retry_after_failed_readback_verifies_our_no_as_written(self):
        owner,items=self.claim(2,["no"])
        self.runtime.submit(2,owner,[response(items[0],2,"CLEAR_REJECT")])
        repo=self.repository(["no"]); read=repo.read_columns; history_reads=0
        def readback_fails(tab,headers):
            nonlocal history_reads
            if tab=="Job History":
                history_reads+=1
                if history_reads==2: raise RuntimeError("Readback connection failed")
            return read(tab,headers)
        with patch.object(repo,"read_columns",side_effect=readback_fails):
            self.assertEqual(sync_pending(self.runtime,2,owner,repo=repo)["counts"],{"Pending":1})
        self.assertEqual(repo.read("Job History")[0]["Added to Opportunities?"],"No")
        with patch.object(repo,"commit",wraps=repo.commit) as commit:
            self.assertEqual(sync_pending(self.runtime,2,owner,repo=repo)["counts"],{"Written":1})
            commit.assert_not_called()

if __name__=="__main__": unittest.main()
