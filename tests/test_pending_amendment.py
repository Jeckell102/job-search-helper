"""Offline tests for explicit, fenced correction of unwritten Needs Info."""
from contextlib import contextmanager,redirect_stdout,redirect_stderr
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.review_runtime import Runtime,assessment_signature,atomic_json,main
from job_search_helper.review_writeback import sheet_writer_lock,writeback
from job_search_helper.repository import MemoryRepository
from test_concurrent_review import job,publish,response


class PendingAmendmentTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.queue=Path(temporary.name)/"queue"
        self.posting=job(score=25,description="Deploy and integrate customer hardware and software.")
        publish(self.queue,[],[self.posting])
        self.rt=Runtime(self.queue); self.addCleanup(self.rt.close); self.rt.sync()
        upstream=self.rt.start(2)["run_id"]
        item=self.rt.next(2,upstream)["items"][0]
        self.rt.submit(2,upstream,[response(item,2,"ESCALATE")])
        self.owner=self.rt.start(3)["run_id"]
        self.item=self.rt.next(3,self.owner)["items"][0]
        prior=response(self.item,3,"Needs Info")
        prior.update(reason="Clarify whether mandatory CJIS screening is permitted.",policy_conflicts=["CJIS policy unclear"],evidence_source="fixture",evidence_locator="fixture/description")
        self.rt.submit(3,self.owner,[prior])
        self.before=self.saved()
        revised=response(self.item,3,"Accept")
        revised.update(reason="The user permits CJIS screening; deployment responsibilities fit.",evidence_source="fixture",evidence_locator="fixture/description",location_check={"status":"verified_us","source_value":"Cleveland, Ohio, United States","evidence":"Exact current History location is Cleveland, Ohio, United States."})
        self.request={"job_key":"j1","source_hash":"h1","input_version":self.item["input_version"],"expected_assessment_signature":assessment_signature(self.before),"revision_id":"user-cjis-clarification-1","revision_reason":"The user clarified the screening policy after this assessment was submitted.","user_clarification":"Allow CJIS background screening; exclude security clearances.","assessment":revised}

    def saved(self):
        row=self.rt.db.execute("SELECT payload FROM decisions WHERE stage=3 AND job_key='j1' AND source_hash='h1'").fetchone()
        return json.loads(row[0])

    def audit(self):
        return [json.loads(row[0]) for row in self.rt.db.execute("SELECT detail FROM events WHERE event='pending_assessment_amended' ORDER BY id")]

    def replace_saved(self,**changes):
        value=self.saved(); value.update(changes)
        with self.rt.transaction():
            self.rt.db.execute("UPDATE decisions SET payload=? WHERE stage=3 AND job_key='j1' AND source_hash='h1'",(json.dumps(value),))
        return value

    def amend(self,request=None,owner=None,stage=3):
        return self.rt.amend_pending(stage,owner or self.owner,request or self.request)

    def assert_refused(self,request=None,owner=None,stage=3):
        before=self.saved(); audit=self.audit()
        with self.assertRaises((ValueError,RuntimeError)):
            self.amend(request,owner,stage)
        self.assertEqual(self.saved(),before)
        self.assertEqual(self.audit(),audit)

    def test_allowed_amendment_preserves_complete_audit_and_export(self):
        result=self.amend()
        self.assertEqual((result["amended"],result["reused"]),(1,0))
        revised=self.saved(); self.assertEqual(revised["decision"],"Accept")
        self.assertEqual(revised["writeback_status"],"Pending")
        self.assertEqual(revised["run_id"],self.owner)
        audit=self.audit(); self.assertEqual(len(audit),1)
        self.assertEqual(audit[0]["prior"],self.before)
        self.assertEqual(audit[0]["revised"],revised)
        for field in ("revision_id","revision_reason","user_clarification","input_version","expected_assessment_signature"):
            self.assertEqual(audit[0][field],self.request[field])
        self.assertEqual(json.loads((self.rt.directory/"third-pass-decisions.jsonl").read_text()),revised)
        self.assertEqual(json.loads((self.rt.directory/"pass-3-checkpoint.json").read_text())["run_id"],self.owner)
        self.assertEqual(self.rt.db.execute("SELECT COUNT(*) FROM writeback").fetchone()[0],0)

    def test_same_revision_and_result_is_idempotent(self):
        self.amend(); first=self.saved(); audit=self.audit()
        result=self.amend()
        self.assertEqual((result["amended"],result["reused"]),(0,1))
        self.assertEqual(self.saved(),first); self.assertEqual(self.audit(),audit)

    def test_reused_revision_id_cannot_change_request_or_result(self):
        self.amend()
        altered=copy.deepcopy(self.request); altered["assessment"]["reason"]="A different assessment."
        self.assert_refused(altered)
        altered=copy.deepcopy(self.request); altered["user_clarification"]="Different claimed authorization."
        self.assert_refused(altered)

    def test_stale_expected_signature_is_refused(self):
        altered=copy.deepcopy(self.request); altered["expected_assessment_signature"]="0"*64
        self.assert_refused(altered)

    def test_changed_input_version_is_refused(self):
        publish(self.queue,[],[{**self.posting,"score":26}])
        self.assert_refused()

    def test_changed_source_or_withdrawn_task_is_refused(self):
        publish(self.queue,[],[{**self.posting,"source_hash":"h2"}])
        self.assert_refused()

    def test_mismatched_revised_identity_is_refused(self):
        altered=copy.deepcopy(self.request); altered["assessment"]["source_hash"]="h2"
        self.assert_refused(altered)

    def test_wrong_run_owner_is_refused(self):
        self.assert_refused(owner="another-run")
        self.replace_saved(run_id="another-run")
        self.assert_refused()

    def test_wrong_task_owner_is_refused(self):
        with self.rt.transaction():
            self.rt.db.execute("UPDATE tasks SET owner='another-run' WHERE stage=3 AND job_key='j1' AND source_hash='h1'")
        self.assert_refused()

    def test_expired_run_is_refused(self):
        with self.rt.transaction(): self.rt.db.execute("UPDATE review_runs SET lease_until=0 WHERE stage=3")
        self.assert_refused()

    def test_legacy_origin_is_refused(self):
        with self.rt.transaction(): self.rt.db.execute("UPDATE decisions SET origin='legacy' WHERE stage=3")
        self.assert_refused()

    def test_write_intent_is_refused_without_replanning(self):
        with self.rt.transaction(): self.rt.db.execute("INSERT INTO writeback VALUES('j1','h1','{}')")
        self.assert_refused()

    def test_completed_conflicted_or_staged_write_is_refused(self):
        for state in ("Written","Conflict","Needs Staging"):
            with self.subTest(state=state):
                self.replace_saved(writeback_status=state)
                self.assert_refused()

    def test_existing_conflict_is_refused(self):
        with self.rt.transaction(): self.rt._conflict(3,"j1","h1","Separate assessment conflict")
        self.assert_refused()

    def test_only_pending_needs_info_may_be_replaced(self):
        for decision,fit in (("Accept","Strong"),("Reject",None)):
            with self.subTest(decision=decision):
                previous=self.replace_saved(decision=decision,fit_level=fit)
                altered=copy.deepcopy(self.request); altered["expected_assessment_signature"]=assessment_signature(previous)
                self.assert_refused(altered)

    def test_other_pass_and_missing_clarification_are_refused(self):
        self.assert_refused(stage=2)
        altered=copy.deepcopy(self.request); altered["user_clarification"]=""
        self.assert_refused(altered)

    def test_revised_acceptance_needs_location_and_resolved_conflicts(self):
        altered=copy.deepcopy(self.request); altered["assessment"].pop("location_check")
        self.assert_refused(altered)
        altered=copy.deepcopy(self.request); altered["assessment"]["policy_conflicts"]=["Still unresolved"]
        self.assert_refused(altered)

    def test_writer_lock_blocks_amendment_without_changes(self):
        with sheet_writer_lock(self.queue.parent/"writer.lock"):
            self.assert_refused()

    def test_cli_accepts_one_request_without_live_refresh(self):
        request_file=self.queue/"amendment.jsonl"; atomic_json(request_file,[self.request],lines=True)
        out=io.StringIO()
        with patch("job_search_helper.review_runtime.live_refresh",side_effect=AssertionError("No live refresh expected")),redirect_stdout(out):
            code=main(["amend-pending","--pass","3","--run-id",self.owner,"--queue-dir",str(self.queue),"--file",str(request_file)])
        self.assertEqual(code,0); self.assertEqual(json.loads(out.getvalue())["amended"],1)

    def test_cli_rejects_multiple_requests(self):
        request_file=self.queue/"amendment.jsonl"; atomic_json(request_file,[self.request,self.request],lines=True)
        with redirect_stderr(io.StringIO()):
            code=main(["amend-pending","--pass","3","--run-id",self.owner,"--queue-dir",str(self.queue),"--file",str(request_file)])
        self.assertEqual(code,1); self.assertEqual(self.saved(),self.before); self.assertEqual(self.audit(),[])

    def test_writer_rereads_after_amendment_between_preflight_and_lock(self):
        repo=MemoryRepository({"Job History":[{"Company":"Fixture","Job Title":"Field Solutions Engineer","Official Job URL":"https://example.com/jobs/one","Job Key":"j1","Source Hash":"h1","Added to Opportunities?":"Pending","Review Status":"Needs Review","Job Status":"Open and verified","Reconsideration Count":0,"Reconsideration Status":"Eligible","Review Notes":"Personal note","Location":"Cleveland, Ohio, United States","Salary / Range":"$150,000 annual base"}],"Opportunities":[]})
        waiting=[True]
        @contextmanager
        def amend_before_acquiring(path):
            if waiting[0]:
                waiting[0]=False
                self.amend()
            with sheet_writer_lock(path): yield
        with patch("job_search_helper.review_writeback.sheet_writer_lock",side_effect=amend_before_acquiring):
            result=writeback(self.rt,self.owner,"j1","h1",repo=repo)
        self.assertEqual(result["writeback_status"],"Written",result)
        self.assertEqual(repo.read("Job History")[0]["Decision"],"Accept")
        self.assertEqual(len(repo.read("Opportunities")),1)
        self.assertEqual(len(self.audit()),1)


if __name__=="__main__": unittest.main()
