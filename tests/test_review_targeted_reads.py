"""Targeted existing-row commits retain fresh identity and cell safeguards."""
import unittest
from job_search_helper.repository import GoogleRepository, RepositoryError
from sheets_fixture import RangeSheets


def review(key="1"):
    return {"tab":"Job History","identity":{"Job Key":key},
            "values":{"Added to Opportunities?":"No","Review Status":"Reviewed","Decision":"Reject","Rejection Reason":"Saved rejection"},
            "expected":{"Source Hash":"h1","Added to Opportunities?":"Pending","Review Status":"Needs Review","Review Notes":"Personal note"},
            "append_notes":{"Review Notes":"Verified review"}}


class ExistingReviewReadTests(unittest.TestCase):
    def make(self,count=20):
        service=RangeSheets({"Job History":[{"Company":"Fixture","Job Key":str(i),"Official Job URL":f"https://example.test/jobs/{i}","Source Hash":"h1","Added to Opportunities?":"Pending","Review Status":"Needs Review","Review Notes":"Personal note","Current Snapshot":"large snapshot "*500,"Job Description":"large description "*500} for i in range(count)]})
        return service,GoogleRepository(service,"fixture",min_request_interval=0)

    def at_final_read(self,service,change):
        count=0
        def before_read(kwargs):
            nonlocal count
            if "'Job History'!1:1" in kwargs.get("ranges",[]):
                count+=1
                if count==2: change()
        service.before_read=before_read

    def test_only_affected_note_and_write_cells_are_loaded(self):
        service,repo=self.make(100)
        result=repo.commit([review("1")])
        ranges=[value for call in service.get_calls for value in call.get("ranges",[])]
        self.assertIn("'Job History'!K2:K1000",ranges)
        self.assertIn("'Job History'!A3:M3",ranges)
        self.assertNotIn("'Job History'!L2:L1000",ranges)
        self.assertNotIn("'Job History'!N2:N1000",ranges)
        self.assertNotIn("'Job History'!A1:AF1000",ranges)
        self.assertEqual(result["inserted"],0)
        row=repo.read_row("Job History",3)
        self.assertEqual(row["Added to Opportunities?"],"No")
        self.assertEqual(row["Review Notes"],"Personal note\n\nVerified review")
        self.assertEqual(row["Current Snapshot"],"large snapshot "*500)

    def test_duplicate_added_between_reads_is_refused(self):
        service,repo=self.make()
        self.at_final_read(service,lambda:service.set_cell("Job History",10,"Job Key","1"))
        with self.assertRaisesRegex(RepositoryError,"multiple rows"):
            repo.commit([review()])
        self.assertEqual(service.batches,[])

    def test_row_movement_between_reads_is_refused(self):
        service,repo=self.make()
        def move():
            rows=service.sheet("Job History")["data"][0]["rowData"]
            rows[2],rows[9]=rows[9],rows[2]
        self.at_final_read(service,move)
        with self.assertRaisesRegex(RepositoryError,"moved"):
            repo.commit([review()])
        self.assertEqual(service.batches,[])

    def test_guarded_source_edit_between_reads_is_refused(self):
        service,repo=self.make()
        self.at_final_read(service,lambda:service.set_cell("Job History",2,"Source Hash","changed"))
        with self.assertRaisesRegex(RepositoryError,"changed since planning"):
            repo.commit([review()])
        self.assertEqual(service.batches,[])

    def test_written_cell_formula_is_preserved(self):
        service,repo=self.make()
        service.set_cell("Job History",2,"Rejection Reason",cell={"userEnteredValue":{"formulaValue":"=1"},"effectiveValue":{"numberValue":1}})
        with self.assertRaisesRegex(RepositoryError,"existing formula"):
            repo.commit([review()])
        self.assertEqual(service.batches,[])

    def test_written_cell_validation_is_checked(self):
        service,repo=self.make()
        service.set_cell("Job History",2,"Added to Opportunities?",cell={"userEnteredValue":{"stringValue":"Pending"},"effectiveValue":{"stringValue":"Pending"},"dataValidation":{"strict":True,"condition":{"type":"ONE_OF_LIST","values":[{"userEnteredValue":"Pending"}]}}})
        with self.assertRaises(RepositoryError):
            repo.commit([review()])
        self.assertEqual(service.batches,[])

    def test_later_append_rediscovers_orphan_tail(self):
        service,repo=self.make(2)
        service.set_cell("Job History",8,"Review Notes","Manual orphan")
        repo.commit([review()])
        self.assertNotIn("Job History",repo._write_layout)
        repo.commit([{"tab":"Job History","identity":{"Job Key":"new"},"values":{"Company":"Fixture"},"append_if_missing":True}])
        self.assertEqual(repo.read_row("Job History",9)["Review Notes"],"Manual orphan")
        self.assertEqual(repo.read_row("Job History",10)["Job Key"],"new")

    def test_payload_is_much_smaller_than_full_cold_commit(self):
        service,repo=self.make(100)
        repo.commit([review()]); narrow_bytes=service.response_bytes
        full_service,full_repo=self.make(100)
        full_repo._load_existing_commit=lambda operations:full_repo._load(["Job History"])
        full_repo.commit([review()]); full_bytes=full_service.response_bytes
        self.assertLess(narrow_bytes,full_bytes/10)


class FilterRangeSheets(RangeSheets):
    def get(self,**kwargs):
        response=super().get(**kwargs); outer=self
        class Response:
            def execute(self,num_retries=0):
                result=response.execute(num_retries=num_retries)
                if "basicFilter" in kwargs.get("fields",""):
                    import copy
                    for sheet in result.get("sheets",[]):
                        source=outer.sheet(sheet["properties"]["title"])
                        if "basicFilter" in source:
                            sheet["basicFilter"]=copy.deepcopy(source["basicFilter"])
                return result
        return Response()


class ReviewFilterRefreshTests(unittest.TestCase):
    def make(self,with_filter=True):
        service=FilterRangeSheets({"Job History":[{"Company":"Fixture","Job Key":"1","Source Hash":"h1","Added to Opportunities?":"Pending","Review Status":"Needs Review","Review Notes":"Personal note"}]})
        history=service.sheet("Job History")
        if with_filter:
            history["basicFilter"]={"range":{"sheetId":history["properties"]["sheetId"],"startRowIndex":0,"endRowIndex":100,"startColumnIndex":0,"endColumnIndex":32},"criteria":{"2":{"hiddenValues":["No","Yes"]}},"filterSpecs":[{"columnIndex":2,"filterCriteria":{"hiddenValues":["No","Yes"]}}],"sortSpecs":[{"dimensionIndex":1,"sortOrder":"ASCENDING"}]}
        return service,GoogleRepository(service,"fixture",min_request_interval=0)

    def test_status_write_reapplies_exact_fresh_filter_in_same_batch(self):
        import copy
        service,repo=self.make()
        old=copy.deepcopy(service.sheet("Job History")["basicFilter"])
        seen=0
        def edit_filter(kwargs):
            nonlocal seen
            if "'Job History'!1:1" in kwargs.get("ranges",[]):
                seen+=1
                if seen==2:
                    current=service.sheet("Job History")["basicFilter"]
                    current["criteria"]["2"]["hiddenValues"]=["Yes"]
                    current["filterSpecs"][0]["filterCriteria"]["hiddenValues"]=["Yes"]
        service.before_read=edit_filter
        repo.commit([review()])
        requests=service.batches[-1]["body"]["requests"]
        self.assertIn("updateCells",requests[0])
        self.assertEqual(requests[-1],{"setBasicFilter":{"filter":service.sheet("Job History")["basicFilter"]}})
        self.assertNotEqual(requests[-1]["setBasicFilter"]["filter"],old)
        self.assertEqual(len(service.batches),1)

    def test_status_write_does_not_create_a_filter(self):
        service,repo=self.make(False); repo.commit([review()])
        self.assertFalse(any("setBasicFilter" in request for request in service.batches[-1]["body"]["requests"]))

    def test_nonstatus_edit_leaves_filter_untouched(self):
        service,repo=self.make()
        repo.commit([{"tab":"Job History","identity":{"Job Key":"1"},"values":{"Review Notes":"Updated personal note"}}])
        self.assertFalse(any("setBasicFilter" in request for request in service.batches[-1]["body"]["requests"]))

if __name__=="__main__": unittest.main()
