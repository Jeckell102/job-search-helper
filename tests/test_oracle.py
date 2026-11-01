import json
import re
from pathlib import Path
import unittest

from job_search_helper.ats import HTTPResponse, fetch_inventory, text
from job_search_helper.oracle import fetch_oracle, supports_oracle


URL = "https://acme.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/jobs"
OCEANEERING_URL = "https://ebfr.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/jobs"


def response(value):
    return HTTPResponse(200, json.dumps(value).encode())


FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "oracle" / "oceaneering.json").read_text())
LIVE_LISTING = json.loads((Path(__file__).parent / "fixtures" / "oracle" / "oceaneering-listing-page-0.json").read_text())
LIVE_DETAIL = json.loads((Path(__file__).parent / "fixtures" / "oracle" / "oceaneering-detail-11836.json").read_text())
LIVE_DETAIL_11792 = json.loads((Path(__file__).parent / "fixtures" / "oracle" / "oceaneering-detail-11792.json").read_text())
LIVE_INVENTORY = json.loads((Path(__file__).parent / "fixtures" / "oracle" / "oceaneering-inventory.json").read_text())
EMPTY_11539 = json.loads((Path(__file__).parent / "fixtures" / "oracle" / "oceaneering-detail-11539-en_US.json").read_text())
PT_11539 = json.loads((Path(__file__).parent / "fixtures" / "oracle" / "oceaneering-detail-11539-pt_BR.json").read_text())


class Page:
    def get(self, url):
        return HTTPResponse(200, b'<link href="x?siteNumber=CX_42">')


class API:
    def get(self, url):
        if "recruitingCEJobRequisitionDetails" in url:
            return response({"items": [{"Id": "1", "Title": "Engineer", "RequisitionId": "REQ-1",
                                          "ExternalDescriptionStr": "<p>Build systems.</p>", "ExternalResponsibilitiesStr": "",
                                          "ExternalQualificationsStr": "", "PrimaryLocation": "Boston, MA",
                                          "otherWorkLocations": [], "secondaryLocations": []}]})
        return response({"items": [{"TotalJobsCount": 1, "requisitionList": [{"Id": "1"}]}]})


class OracleTests(unittest.TestCase):
    def test_supports_site_specific_jobs_path(self):
        self.assertTrue(supports_oracle(
            "Oracle Recruiting Cloud",
            "https://icfcjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/Aerospace/jobs",
        ))

    def test_accepts_a_single_public_external_description_section(self):
        class ResponsibilitiesOnly(API):
            def get(self, url):
                if "recruitingCEJobRequisitionDetails" in url:
                    return response({"items": [{"Id": "1", "Title": "Engineer", "RequisitionId": "REQ-1",
                                                  "ExternalDescriptionStr": "", "ExternalResponsibilitiesStr": "<p>Build systems.</p>",
                                                  "ExternalQualificationsStr": "", "PrimaryLocation": "Boston, MA",
                                                  "otherWorkLocations": [], "secondaryLocations": []}]})
                return super().get(url)
        result = fetch_oracle("Oracle", URL, "C-1", "Acme", ResponsibilitiesOnly(), Page())
        self.assertEqual(result.status, "complete", result.reason)

    def test_complete_public_inventory(self):
        result = fetch_oracle("Oracle", URL, "C-1", "Acme", API(), Page())
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(result.jobs[0]["title"], "Engineer")
        self.assertEqual(result.jobs[0]["location"], "Boston, MA")

    def test_dispatches_from_candidate_experience_url(self):
        result = fetch_inventory("Oracle", URL, "C-1", "Acme", API(), discovery_transport=Page())
        self.assertEqual(result.status, "complete", result.reason)

    def test_oceaneering_captured_scope_paginates_and_keeps_full_detail_sections(self):
        class OceaneeringAPI:
            def get(self, url):
                if "recruitingCEJobRequisitionDetails" in url:
                    ident = re.search(r'Id%3D%22(\d+)%22', url).group(1)
                    item = dict(FIXTURE["detail_sample"])
                    item["Id"] = ident
                    if ident != "11836":
                        item["Title"] = f"Oceaneering role {ident}"
                    return response({"items": [item]})
                offset = int(re.search(r"offset%3D(\d+)", url).group(1))
                total = FIXTURE["published_total"]
                rows = []
                for index in range(offset, min(offset + 20, total)):
                    ident = "11836" if index == 0 else str(20000 + index)
                    title = FIXTURE["listing_sample"]["Title"] if index == 0 else f"Oceaneering role {ident}"
                    rows.append({"Id": ident, "Title": title})
                return response({"items": [{"TotalJobsCount": total, "requisitionList": rows}]})

        result = fetch_oracle("Oracle Fusion", URL, "COMP-0047", "Oceaneering Technologies", OceaneeringAPI(), Page())
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 274)
        first = result.jobs[0]
        self.assertEqual(first["posting_id"], "11836")
        self.assertIn("Outside Machinists", first["description"])
        self.assertIn("Set up, align", first["description"])
        self.assertIn("Secret security clearance", first["description"])
        self.assertEqual(first["location"], "Bremerton, WA, United States")

    def test_oceaneering_live_payload_replay_uses_captured_oracle_schema(self):
        captured_rows = LIVE_LISTING["items"][0]["requisitionList"][:20]
        captured_detail = LIVE_DETAIL["items"][0]

        class CapturedPage:
            def get(self, url):
                return HTTPResponse(200, b'<base href="/hcmUI/CandidateExperience/en/sites/jobs?siteNumber=CX_3001">')

        class CapturedAPI:
            def get(self, url):
                if "recruitingCEJobRequisitionDetails" in url:
                    ident = re.search(r'Id%3D%22(\d+)%22', url).group(1)
                    row = next(item for item in captured_rows if str(item["Id"]) == ident)
                    item = dict(captured_detail)
                    item.update(Id=ident, Title=row["Title"])
                    return response({"items": [item], "count": 1, "hasMore": False, "limit": 1, "offset": 0, "links": []})
                page = json.loads(json.dumps(LIVE_LISTING))
                page["items"][0]["TotalJobsCount"] = 20
                page["items"][0]["requisitionList"] = captured_rows
                return response(page)

        result = fetch_oracle("Oracle Fusion", URL, "COMP-0047", "Oceaneering Technologies", CapturedAPI(), CapturedPage())
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 20)
        first = result.jobs[0]
        self.assertEqual(first["posting_id"], "11836")
        self.assertIn("Outside Machinists at Oceaneering", first["description"])
        self.assertIn("Technical & Mechanical Work", first["description"])
        self.assertIn("High School Diploma/GED", first["description"])

    def test_oceaneering_live_detail_preserves_all_five_public_body_sections(self):
        detail = LIVE_DETAIL_11792["items"][0]
        listing_row = next(row for row in LIVE_INVENTORY["jobs"] if str(row["Id"]) == "11792")

        class Page:
            def get(self, url):
                return HTTPResponse(200, b'<base href="/hcmUI/CandidateExperience/en/sites/jobs?siteNumber=CX_3001">')

        class API:
            def get(self, url):
                if "recruitingCEJobRequisitionDetails" in url:
                    return response(LIVE_DETAIL_11792)
                return response({"items": [{"TotalJobsCount": 1, "requisitionList": [listing_row]}]})

        result = fetch_oracle("Oracle Fusion", OCEANEERING_URL, "COMP-0047", "Oceaneering Technologies", API(), Page())
        self.assertEqual(result.status, "complete", result.reason)
        expected = "\n".join(filter(None, (text(detail.get(field)) for field in (
            "CorporateDescriptionStr", "OrganizationDescriptionStr",
            "ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr",
        ))))
        self.assertEqual(result.jobs[0]["description"], expected)
        for marker in ("global provider", "India Center", "Lead Software Engineer"):
            self.assertIn(marker, result.jobs[0]["description"])

    def test_oceaneering_corporate_only_body_without_external_role_text_stays_partial(self):
        detail = json.loads(json.dumps(LIVE_DETAIL_11792))
        item = detail["items"][0]
        for field in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr"):
            item[field] = ""
        listing_row = next(row for row in LIVE_INVENTORY["jobs"] if str(row["Id"]) == "11792")

        class Page:
            def get(self, url):
                return HTTPResponse(200, b'<base href="/hcmUI/CandidateExperience/en/sites/jobs?siteNumber=CX_3001">')

        class API:
            def get(self, url):
                if "recruitingCEJobRequisitionDetails" in url: return response(detail)
                return response({"items": [{"TotalJobsCount": 1, "requisitionList": [listing_row]}]})

        result = fetch_oracle("Oracle Fusion", OCEANEERING_URL, "COMP-0047", "Oceaneering Technologies", API(), Page())
        self.assertEqual(result.status, "partial")

    def test_oceaneering_three_record_replay_retains_two_valid_details_when_one_is_empty(self):
        rows = [dict(row) for row in LIVE_LISTING["items"][0]["requisitionList"][:3]]
        captured_detail = LIVE_DETAIL["items"][0]

        class CapturedPage:
            def get(self, url):
                return HTTPResponse(200, b'<base href="/hcmUI/CandidateExperience/en/sites/jobs?siteNumber=CX_3001">')

        class ThreeJobAPI:
            def get(self, url):
                if "recruitingCEJobRequisitionDetails" in url:
                    ident = re.search(r'Id%3D%22(\d+)%22', url).group(1)
                    row = next(item for item in rows if str(item["Id"]) == ident)
                    item = dict(captured_detail, Id=ident, Title=row["Title"])
                    if ident == str(rows[1]["Id"]):
                        item.update(ExternalDescriptionStr="", ExternalResponsibilitiesStr="", ExternalQualificationsStr="")
                    return response({"items": [item]})
                page = json.loads(json.dumps(LIVE_LISTING))
                page["items"][0]["TotalJobsCount"] = 3
                page["items"][0]["requisitionList"] = rows
                return response(page)

        result = fetch_oracle("Oracle Fusion", URL, "COMP-0047", "Oceaneering Technologies", ThreeJobAPI(), CapturedPage())
        self.assertEqual(result.status, "partial", result.reason)
        self.assertEqual(len(result.jobs), 2)

    def test_oceaneering_empty_english_detail_recovers_verified_pt_br_payload(self):
        listing_row = next(row for row in LIVE_INVENTORY["jobs"] if str(row["Id"]) == "11539")

        class CapturedPage:
            def get(self, url):
                return HTTPResponse(200, b'<base href="/hcmUI/CandidateExperience/en/sites/jobs?siteNumber=CX_3001">')

        class LocalizedAPI:
            def __init__(self, detail=None):
                self.detail = detail or PT_11539
                self.headers = []

            def get(self, url):
                if "recruitingCEJobRequisitionDetails" in url:
                    return response(EMPTY_11539)
                return response({"items": [{"TotalJobsCount": 1, "requisitionList": [listing_row]}]})

            def get_with_headers(self, url, headers):
                self.headers.append(dict(headers))
                return response(self.detail)

        api = LocalizedAPI()
        result = fetch_oracle("Oracle Fusion", OCEANEERING_URL, "COMP-0047", "Oceaneering Technologies", api, CapturedPage())
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]["posting_id"], "11539")
        self.assertEqual(result.jobs[0]["title"], "Workshop Service Technician V")
        self.assertEqual(result.jobs[0]["content_locale"], "pt-BR")
        self.assertGreater(len(result.jobs[0]["description"]), 1000)
        self.assertEqual(api.headers, [{"Accept-Language": "pt-BR", "Ora-Irc-Language": "pt-BR"}])

    def test_oceaneering_pt_br_fallback_rejects_wrong_identity_or_locale(self):
        listing_row = next(row for row in LIVE_INVENTORY["jobs"] if str(row["Id"]) == "11539")

        class Page:
            def __init__(self, site="CX_3001"):
                self.site = site
            def get(self, url):
                return HTTPResponse(200, f'<base href="/hcmUI/CandidateExperience/en/sites/jobs?siteNumber={self.site}">'.encode())

        class API:
            def __init__(self, localized): self.localized = localized
            def get(self, url):
                if "recruitingCEJobRequisitionDetails" in url: return response(EMPTY_11539)
                return response({"items": [{"TotalJobsCount": 1, "requisitionList": [listing_row]}]})
            def get_with_headers(self, url, headers): return response(self.localized)

        for change in (
            {"Id": "99999"},
            {"RequisitionId": 999999999},
            {"ContentLocale": "pt"},
        ):
            localized = json.loads(json.dumps(PT_11539))
            localized["items"][0].update(change)
            with self.subTest(change=change):
                result = fetch_oracle("Oracle Fusion", OCEANEERING_URL, "COMP-0047", "Oceaneering Technologies", API(localized), Page())
                self.assertEqual(result.status, "partial")

    def test_oceaneering_pt_br_fallback_is_not_enabled_for_another_oracle_host(self):
        listing_row = next(row for row in LIVE_INVENTORY["jobs"] if str(row["Id"]) == "11539")

        class API:
            def __init__(self): self.localized_calls = 0
            def get(self, url):
                if "recruitingCEJobRequisitionDetails" in url: return response(EMPTY_11539)
                return response({"items": [{"TotalJobsCount": 1, "requisitionList": [listing_row]}]})
            def get_with_headers(self, url, headers):
                self.localized_calls += 1
                return response(PT_11539)

        api = API()
        result = fetch_oracle("Oracle Fusion", URL, "COMP-0047", "Oceaneering Technologies", api, Page())
        self.assertEqual(result.status, "partial")
        self.assertEqual(api.localized_calls, 0)

    def test_oceaneering_pt_br_fallback_is_scoped_to_exact_site_and_brazil_records(self):
        listing_row = next(row for row in LIVE_INVENTORY["jobs"] if str(row["Id"]) == "11539")

        class Page:
            def __init__(self, site="CX_3001"):
                self.site = site
            def get(self, url):
                return HTTPResponse(200, f'<base href="/hcmUI/CandidateExperience/en/sites/jobs?siteNumber={self.site}">'.encode())

        class API:
            def __init__(self, row, localized, english=None):
                self.row, self.localized, self.english, self.localized_calls = row, localized, english or EMPTY_11539, 0
            def get(self, url):
                if "recruitingCEJobRequisitionDetails" in url: return response(self.english)
                return response({"items": [{"TotalJobsCount": 1, "requisitionList": [self.row]}]})
            def get_with_headers(self, url, headers):
                self.localized_calls += 1
                return response(self.localized)

        wrong_site = OCEANEERING_URL.replace("/sites/jobs", "/sites/other/jobs")
        api = API(listing_row, PT_11539)
        result = fetch_oracle("Oracle Fusion", wrong_site, "COMP-0047", "Oceaneering Technologies", api, Page("CX_3002"))
        self.assertEqual(result.status, "partial")
        self.assertEqual(api.localized_calls, 0)

        non_brazil = dict(listing_row, PrimaryLocationCountry="US")
        empty_non_brazil = json.loads(json.dumps(EMPTY_11539))
        empty_non_brazil["items"][0]["PrimaryLocationCountry"] = "US"
        api = API(non_brazil, PT_11539, empty_non_brazil)
        result = fetch_oracle("Oracle Fusion", OCEANEERING_URL, "COMP-0047", "Oceaneering Technologies", api, Page())
        self.assertEqual(result.status, "partial")
        self.assertEqual(api.localized_calls, 0)

        blank_pt = json.loads(json.dumps(PT_11539))
        blank_pt["items"][0].update(ExternalResponsibilitiesStr="", ExternalQualificationsStr="", ShortDescriptionStr="")
        api = API(listing_row, blank_pt)
        result = fetch_oracle("Oracle Fusion", OCEANEERING_URL, "COMP-0047", "Oceaneering Technologies", api, Page())
        self.assertEqual(result.status, "partial")
        self.assertEqual(api.localized_calls, 1)

    def test_oceaneering_captured_inventory_has_all_274_unique_published_ids(self):
        self.assertEqual(LIVE_INVENTORY["total"], 274)
        self.assertEqual(len(LIVE_INVENTORY["jobs"]), 274)
        ids = [str(row["Id"]) for row in LIVE_INVENTORY["jobs"]]
        self.assertEqual(len(set(ids)), 274)
        self.assertIn("11539", ids)

    def test_oceaneering_nonfirst_page_final_recheck_catches_same_count_id_drift(self):
        rows = [dict(row) for row in LIVE_INVENTORY["jobs"][:21]]
        detail_sample = LIVE_DETAIL["items"][0]

        class CapturedPage:
            def get(self, url):
                return HTTPResponse(200, b'<base href="/hcmUI/CandidateExperience/en/sites/jobs?siteNumber=CX_3001">')

        class DriftAPI:
            def __init__(self): self.page_calls = {}
            def get(self, url):
                if "recruitingCEJobRequisitionDetails" in url:
                    ident = re.search(r'Id%3D%22(\d+)%22', url).group(1)
                    row = next(item for item in rows if str(item["Id"]) == ident)
                    item = dict(detail_sample, Id=ident, Title=row["Title"])
                    return response({"items": [item]})
                offset = int(re.search(r"offset%3D(\d+)", url).group(1))
                self.page_calls[offset] = self.page_calls.get(offset, 0) + 1
                page_rows = rows[offset:offset + 20]
                if offset == 20 and self.page_calls[offset] > 1:
                    page_rows = [dict(page_rows[0], Id=rows[0]["Id"])]
                return response({"items": [{"TotalJobsCount": 21, "requisitionList": page_rows}]})

        result = fetch_oracle("Oracle Fusion", OCEANEERING_URL, "COMP-0047", "Oceaneering Technologies", DriftAPI(), CapturedPage())
        self.assertEqual(result.status, "partial")

    def test_oceaneering_missing_detail_content_retains_valid_jobs_as_partial(self):
        class APIWithOneMissing(API):
            def get(self, url):
                if "recruitingCEJobRequisitionDetails" in url and "Id%3D%221%22" in url:
                    return response({"items": [{"Id": "1", "Title": "Engineer", "ExternalDescriptionStr": "", "ExternalResponsibilitiesStr": "", "ExternalQualificationsStr": ""}]})
                return super().get(url)

        result = fetch_oracle("Oracle", URL, "C-1", "Acme", APIWithOneMissing(), Page())
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.jobs), 0)

    def test_oceaneering_listing_count_drift_and_detail_identity_are_partial(self):
        class Drift(API):
            def __init__(self): self.calls = 0
            def get(self, url):
                if "recruitingCEJobRequisitions" in url:
                    self.calls += 1
                    value = super().get(url)
                    if self.calls > 1:
                        body = json.loads(value.body)
                        body["items"][0]["TotalJobsCount"] += 1
                        return response(body)
                    return value
                return super().get(url)
        result = fetch_oracle("Oracle", URL, "C-1", "Acme", Drift(), Page())
        self.assertEqual(result.status, "partial")

        class WrongId(API):
            def get(self, url):
                value = super().get(url)
                if "recruitingCEJobRequisitionDetails" in url:
                    body = json.loads(value.body)
                    body["items"][0]["Id"] = "999"
                    return response(body)
                return value
        result = fetch_oracle("Oracle", URL, "C-1", "Acme", WrongId(), Page())
        self.assertEqual(result.status, "partial")

    def test_oceaneering_route_scope_rejects_query_foreign_host_and_wrong_ats(self):
        self.assertTrue(supports_oracle("Oracle Fusion", URL))
        self.assertFalse(supports_oracle("Oracle Fusion", URL + "?q=secret"))
        self.assertFalse(supports_oracle("Oracle Fusion", URL.replace("acme.fa.us2.oraclecloud.com", "other.example")))
        result = fetch_oracle("Greenhouse", URL, "COMP-0047", "Oceaneering Technologies", API(), Page())
        self.assertEqual(result.status, "unsupported")
