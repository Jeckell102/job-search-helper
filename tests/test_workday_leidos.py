import copy
import json
import unittest
from unittest.mock import patch

from job_search_helper.ats import HTTPResponse
from job_search_helper.workday import _fetch_leidos_partitions


HOST = "leidos.wd5.myworkdayjobs.com"
SITE = "External"
ENDPOINT = f"https://{HOST}/wday/cxs/leidos/{SITE}"
GROUPS = ("engineering", "program-management")


def facets(counts=None, dimensions=False):
    counts = counts or {group: 1000 for group in GROUPS}
    result = [{"facetParameter": "jobFamilyGroup", "values":
               [{"id": group, "count": count} for group, count in counts.items()]}]
    if dimensions:
        result.extend([
            {"facetParameter": "workerSubType", "values": [{"id": "regular", "count": 2000}]},
            {"facetParameter": "timeType", "values": [{"id": "full", "count": 2000}]},
            {"facetParameter": "Is_Evergreen", "values": [{"id": "no", "count": 2000}]},
        ])
    return result


def item(number, group):
    return {"title": f"Leidos {group} {number}",
            "externalPath": f"/job/US/Leidos-{group}-{number}",
            "locationsText": "Remote", "bulletFields": [f"R{number}"]}


def detail(number, group, posting_id=None):
    path = f"/job/US/Leidos-{group}-{number}"
    return {"jobPostingInfo": {"id": posting_id or f"opaque-{group}-{number}",
            "jobPostingId": f"R{number}", "jobPostingSiteId": SITE,
            "jobReqId": f"R{number}", "title": f"Leidos {group} {number}",
            "jobDescription": "Full public job description.",
            "location": "Remote", "additionalLocations": [], "posted": True}}


class PartitionTransport:
    def __init__(self, mode="ok"):
        self.mode = mode
        self.calls = []
        self.partition_reads = {group: 0 for group in GROUPS}
        self.offset_reads = {(group, offset): 0 for group in GROUPS for offset in range(0, 1000, 20)}
        self.details = {}
        for group in GROUPS:
            for number in range(1000):
                self.details[f"{ENDPOINT}/job/US/Leidos-{group}-{number}"] = detail(number, group)

    def post(self, url, payload):
        self.calls.append(("partition", url, copy.deepcopy(payload)))
        applied = payload.get("appliedFacets", {})
        group_values = applied.get("jobFamilyGroup", [])
        if group_values:
            group = group_values[0]
            read = self.partition_reads[group]
            self.partition_reads[group] += 1
            offset = int(payload.get("offset", 0))
            self.offset_reads[(group, offset)] += 1
            count = 999 if self.mode == "count-drift" and read else 1000
            if self.mode == "short-page" and group == GROUPS[0] and offset == 20 and self.offset_reads[(group, offset)] == 1:
                entries = [item(n, group) for n in range(20, 39)]
                return HTTPResponse(200, json.dumps({"total": 1000, "jobPostings": entries,
                    "facets": []}).encode(), {})
            if self.mode == "facet-count-drift" and offset == 0 and read == 0 and group == GROUPS[0]:
                # Same facet IDs, changed advertised count.
                return HTTPResponse(200, json.dumps({"total": 1000, "jobPostings":
                    [item(n, group) for n in range(20)],
                    "facets": facets({"engineering": 999, "program-management": 1001})}).encode(), {})
            entries = [item(n, group) for n in range(offset, min(offset + 20, count))]
            # A late-page change must be detected during the complete
            # recheck; a first-page-only validator will miss this.
            if self.mode == "late-drift" and group == GROUPS[1] and offset == 980 and self.offset_reads[(group, offset)] > 1:
                entries[-1] = item(1999, group)
            if self.mode == "late-metadata" and group == GROUPS[1] and offset == 980 and self.offset_reads[(group, offset)] > 1:
                entries[-1]["title"] = "Changed after details"
            if self.mode == "cross-overlap" and group == GROUPS[1] and offset == 0:
                entries[0]["externalPath"] = item(0, GROUPS[0])["externalPath"]
            if self.mode == "duplicate" and offset == 20:
                entries[-1] = entries[-2]
            data_facets = facets() if offset == 0 else []
            return HTTPResponse(200, json.dumps({"total": (count if offset == 0 or self.mode == "count-drift" else 0), "jobPostings": entries,
                "facets": data_facets}).encode(), {})
        global_reads = sum(1 for call in self.calls if call[0] == "global")
        facet_counts = {group: 1000 for group in GROUPS}
        if self.mode == "dimension-mismatch": facet_counts = {GROUPS[0]: 999, GROUPS[1]: 1001}
        if self.mode == "unknown-facet-count": facet_counts = {group: None for group in GROUPS}
        data = {"total": 2000, "jobPostings": [], "facets": facets(facet_counts, dimensions=True)}
        if self.mode in ("facet-drift", "final-dimension-drift"):
            data["facets"] = facets({"engineering": 999, "program-management": 1001}) if self.mode == "facet-drift" else facets(dimensions=True)
            if self.mode == "final-dimension-drift" and global_reads:
                data["facets"][-1]["values"][0]["count"] = 1999

        if self.mode == "final-global-drift" and global_reads:
            data["total"] = 2001
        self.calls.append(("global", url, copy.deepcopy(payload)))
        return HTTPResponse(200, json.dumps(data).encode(), {})

    def get(self, url):
        if self.mode == "blocked" and url.endswith("Leidos-engineering-0"):
            return HTTPResponse(403, b"denied", {})
        if self.mode == "missing-body" and url.endswith("Leidos-engineering-0"):
            data = copy.deepcopy(self.details[url]); data["jobPostingInfo"]["jobDescription"] = ""
            return HTTPResponse(200, json.dumps(data).encode(), {})
        data = copy.deepcopy(self.details[url])
        if self.mode == "duplicate-id" and "program-management" in url:
            data["jobPostingInfo"]["id"] = "same-opaque-id"
        return HTTPResponse(200, json.dumps(data).encode(), {})


class LeidosPartitionTests(unittest.TestCase):
    def initial(self):
        return {"total": 2000, "jobPostings": [], "facets": facets(dimensions=True)}

    def run_partition(self, mode="ok"):
        transport = PartitionTransport(mode)
        payload = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
        initial = {"total": 2000, "jobPostings": [],
                   "facets": facets({group: None for group in GROUPS})} if mode == "unknown-facet-count" else self.initial()
        with patch("job_search_helper.workday.PAGE_SIZE", 20):
            result = _fetch_leidos_partitions(ENDPOINT, payload, SITE, HOST,
                                              "COMP-0003", "Leidos", transport, initial)
        return result, transport

    def test_two_full_partitions_and_final_global_check_complete(self):
        result, transport = self.run_partition()
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 2000)
        self.assertGreaterEqual(sum(transport.partition_reads.values()), 100)

    def test_partition_count_drift_is_partial(self):
        result, _ = self.run_partition("count-drift")
        self.assertEqual(result.status, "partial")

    def test_final_facet_drift_is_partial(self):
        result, _ = self.run_partition("facet-drift")
        self.assertEqual(result.status, "partial")

    def test_same_facet_ids_with_changed_advertised_counts_is_partial(self):
        result, _ = self.run_partition("facet-count-drift")
        self.assertEqual(result.status, "partial")

    def test_final_global_drift_after_details_is_partial(self):
        result, _ = self.run_partition("final-global-drift")
        self.assertEqual(result.status, "partial")

    def test_final_exhaustive_dimension_drift_is_partial(self):
        result, _ = self.run_partition("final-dimension-drift")
        self.assertEqual(result.status, "partial")

    def test_late_page_path_drift_is_partial(self):
        result, _ = self.run_partition("late-drift")
        self.assertEqual(result.status, "partial")

    def test_late_page_metadata_drift_reconciles_current_stable_cohort(self):
        result, _ = self.run_partition("late-metadata")
        self.assertEqual(result.status, "complete", result.reason)
        self.assertIn("Reconciled once", result.reason)

    def test_duplicate_late_page_is_partial(self):
        result, _ = self.run_partition("duplicate")
        self.assertEqual(result.status, "partial")

    def test_short_page_with_unchanged_total_is_partial(self):
        result, _ = self.run_partition("short-page")
        self.assertEqual(result.status, "partial")

    def test_cross_partition_overlap_is_partial(self):
        result, _ = self.run_partition("cross-overlap")
        self.assertEqual(result.status, "partial")

    def test_duplicate_opaque_detail_id_is_partial(self):
        result, _ = self.run_partition("duplicate-id")
        self.assertEqual(result.status, "partial")

    def test_independent_dimension_count_mismatch_is_partial(self):
        result, _ = self.run_partition("dimension-mismatch")
        self.assertEqual(result.status, "partial")

    def test_unknown_facet_counts_do_not_opt_into_partition_repair(self):
        # A missing advertised count is not sufficient to opt into the
        # capped-board partition repair; the caller must retain partial state.
        result, _ = self.run_partition("unknown-facet-count")
        self.assertIsNone(result)

    def test_blocked_detail_propagates_without_false_complete(self):
        result, _ = self.run_partition("blocked")
        self.assertEqual(result.status, "blocked")

    def test_missing_description_is_partial(self):
        result, _ = self.run_partition("missing-body")
        self.assertEqual(result.status, "partial")
        self.assertLess(len(result.jobs), 2000)


if __name__ == "__main__":
    unittest.main()
