import copy
import unittest
import json
from unittest.mock import patch

from job_search_helper.core import material_hash
from job_search_helper.locations import check_location, check_posting_location
from job_search_helper.workday import _posting, resolve_country_scope
from job_search_helper.location_cleanup import plan_cleanup, publish_cleanup
from job_search_helper.repository import MemoryRepository
from test_workday import detail, WorkdayTransport, page, listing, ROOT
from test_location_cleanup import job, DeliveryTests
from test_job_screening import ScreeningIntegrationTests
from job_search_helper.location_metadata import structured_location
from job_search_helper.workday import _structured_country_scope


class CountryTests(unittest.TestCase):
    def posting(self, **changes):
        data = detail()
        data["jobPostingInfo"].update(changes)
        return _posting(data, listing()["externalPath"], "Careers", "acme.wd501.myworkdayjobs.com", "C-1", "Acme")

    def test_workday_primary_country_is_preserved(self):
        row = self.posting(location="Barcelona", country={"descriptor": "Spain"}, additionalLocations=[])
        self.assertEqual(row["location"], "Barcelona, Spain")
        self.assertEqual(check_posting_location(row).status, "non_us")

    def test_requisition_country_fallback_and_us_secondary(self):
        row = self.posting(location="Barcelona", jobRequisitionLocation={"country": {"descriptor": "Spain"}}, additionalLocations=["Dallas TX"])
        self.assertEqual(row["location"], "Barcelona, Spain; Dallas TX")
        self.assertEqual(check_posting_location(row).status, "us")

    def test_primary_country_never_applied_to_secondary_cities(self):
        row = self.posting(location="Rotterdam", country={"descriptor": "Netherlands"}, additionalLocations=["Delft"])
        self.assertEqual(row["location"], "Rotterdam, Netherlands; Delft")
        self.assertEqual(check_posting_location(row).status, "unknown")
        facets = [{"facetParameter": "locationCountry", "values": [{"id": "US-ID", "descriptor": "United States of America"}]}]
        transport = WorkdayTransport([page(0, []), page(0, [])])
        resolve_country_scope([row], ROOT, {"appliedFacets": {}, "searchText": "", "limit": 20}, transport, facets)
        self.assertEqual(check_posting_location(row).status, "non_us")
        self.assertEqual(transport.posts[0][1]["appliedFacets"], {"locationCountry": ["US-ID"]})

    def test_official_us_alternative_is_preserved_and_hash_covers_scope(self):
        row = self.posting(location="Rotterdam", country={"descriptor": "Netherlands"}, additionalLocations=["Austin"])
        before = material_hash(row)
        facets = [{"facetParameter": "locationCountry", "values": [{"id": "US-ID", "descriptor": "United States of America"}]}]
        transport = WorkdayTransport([page(), page()])
        resolve_country_scope([row], ROOT, {"appliedFacets": {}, "searchText": "", "limit": 20}, transport, facets)
        self.assertEqual(check_posting_location(row).status, "us")
        self.assertNotEqual(before, material_hash(row))

    def test_moving_country_listing_does_not_prove_exclusion(self):
        row = self.posting(location="Rotterdam", country={"descriptor": "Netherlands"}, additionalLocations=["Delft"])
        facets = [{"facetParameter": "locationCountry", "values": [{"id": "US-ID", "descriptor": "United States"}]}]
        resolve_country_scope([row], ROOT, {"appliedFacets": {}}, WorkdayTransport([page(0, []), page()]), facets)
        self.assertEqual(check_posting_location(row).status, "unknown")

    def test_state_without_comma_and_territory_protection(self):
        self.assertEqual(check_location("Dallas TX; Denver CO").status, "us")
        self.assertEqual(check_posting_location({"location": "Guam", "location_country_scope": {"source_url": ROOT, "us_eligible": False}}).status, "unknown")

    def test_slash_inside_office_name_does_not_hide_structured_country(self):
        row = self.posting(location="Chennai ITEC/KBS", country={"descriptor": "India"}, additionalLocations=[])
        self.assertEqual(check_posting_location(row).status, "non_us")

    def test_conflicting_us_primary_and_foreign_country_is_not_rejected(self):
        row = self.posting(location="Austin, TX", country={"descriptor": "Germany"}, additionalLocations=[])
        self.assertEqual(check_posting_location(row).status, "unknown")

    def test_provider_country_facet_name_is_used_exactly(self):
        row = self.posting(location="Rotterdam", country={"descriptor": "Netherlands"}, additionalLocations=["Delft"])
        facets = [{"facetParameter": "Country", "values": [{"id": "US-ID", "descriptor": "United States"}]}]
        transport = WorkdayTransport([page(0, []), page(0, [])])
        resolve_country_scope([row], ROOT, {"appliedFacets": {}}, transport, facets)
        self.assertEqual(transport.posts[0][1]["appliedFacets"], {"Country": ["US-ID"]})
        self.assertEqual(check_posting_location(row).status, "non_us")

    def test_nested_country_facets_and_turkiye(self):
        row = self.posting(location="Rotterdam", country={"descriptor": "Netherlands"}, additionalLocations=["Delft"])
        facets = [{"facetParameter": "locationMainGroup", "values": [{"facetParameter": "locationCountry", "values": [{"id": "US-ID", "descriptor": "United States"}]}]}]
        resolve_country_scope([row], ROOT, {"appliedFacets": {}}, WorkdayTransport([page(0, []), page(0, [])]), facets)
        self.assertEqual(check_posting_location(row).status, "non_us")
        self.assertEqual(check_location("Istanbul, Türkiye").status, "non_us")

    def test_ignored_country_filter_does_not_prove_foreign_status(self):
        row = self.posting(location="Rotterdam", country={"descriptor": "Netherlands"}, additionalLocations=["Delft"])
        facets = [{"facetParameter": "Country", "values": [{"id": "US-ID", "descriptor": "United States", "count": 1}]}]
        resolve_country_scope([row], ROOT, {"appliedFacets": {}}, WorkdayTransport([page(0, [])]), facets)
        self.assertEqual(check_posting_location(row).status, "unknown")


class EvidenceCleanupTests(unittest.TestCase):
    def test_proof_is_tied_to_exact_source_and_preserves_choices(self):
        row = job(Location="Barcelona")
        proof = {row["Job Key"]: {"source_hash": row["Source Hash"], "original_location": "Barcelona", "official_url": row["Official Job URL"], "reason": "Location exclusion: posting is outside the U.S. (Barcelona, Spain)."}}
        repo = MemoryRepository({"Job History": [row]})
        self.assertEqual(len(plan_cleanup(repo, evidence=proof)[0]), 1)
        for changes in ({"Location": "Austin"}, {"Source Hash": "new"}, {"Official Job URL": "https://example.com/new"}, {"Added to Opportunities?": "Yes"}, {"Review Started At": "claimed"}):
            other = MemoryRepository({"Job History": [{**row, **changes}]})
            self.assertEqual(plan_cleanup(other, evidence=proof)[0], [])
        protected = MemoryRepository({"Job History": [row], "Opportunities": [{"Company": "Fixture", "Job URL": row["Official Job URL"]}]})
        self.assertEqual(plan_cleanup(protected, evidence=proof)[0], [])


class StructuredCountryTests(unittest.TestCase):
    url = 'https://acme.wd501.myworkdayjobs.com/Careers/job/Test/REQ1'

    def html(self, countries, **changes):
        job = {'@type': 'JobPosting', 'title': 'Product Manager', 'url': self.url,
               'jobLocation': [{'@type': 'Place', 'address': {'addressCountry': c}} for c in countries]}
        job.update(changes)
        return '<script type="application/ld+json">' + json.dumps(job) + '</script>'

    def test_complete_country_addresses_and_us_options(self):
        self.assertEqual(structured_location(self.html(['IN', 'GB']), 'Product Manager', self.url).status, 'non_us')
        self.assertEqual(structured_location(self.html(['IN', 'US']), 'Product Manager', self.url).status, 'us')
        self.assertEqual(structured_location(self.html(['IN', '']), 'Product Manager', self.url).status, 'unknown')
        self.assertEqual(structured_location(self.html(['Guam']), 'Product Manager', self.url).status, 'unknown')

    def test_exact_job_match_and_remote_applicant_country(self):
        self.assertEqual(structured_location(self.html(['IN']), 'Different title', self.url).status, 'unknown')
        self.assertEqual(structured_location(self.html(['IN'], url=self.url + '-different'), 'Product Manager', self.url).status, 'unknown')
        html = self.html(['IN'], applicantLocationRequirements={'@type': 'Country', 'name': 'United States'})
        self.assertEqual(structured_location(html, 'Product Manager', self.url).status, 'us')

    def test_workday_fallback_records_official_page_evidence(self):
        row = {'url': self.url, 'title': 'Product Manager', 'location': 'India; Remote'}
        response = type('Response', (), {'status': 200, 'body': self.html(['IN', 'IN']).encode()})()
        with patch('job_search_helper.discovery.CareersTransport') as transport:
            transport.return_value.get.return_value = response
            _structured_country_scope([row])
        self.assertFalse(row['location_country_scope']['us_eligible'])
        self.assertEqual(check_posting_location(row).status, 'non_us')


class EvidenceDeliveryTests(DeliveryTests):
    def test_country_proof_works_with_compact_sheet_without_source_hash(self):
        self.local.commit([{"tab": "Job History", "identity": {"Job Key": "foreign"}, "values": {"Location": "Barcelona"}}])
        self.remote.commit([{"tab": "Job History", "identity": {"Job Key": "foreign"}, "values": {"Location": "Barcelona"}}])
        row = self.local.matches("Job History", {"Job Key": "foreign"})[0][1]
        proof = {"foreign": {"source_hash": row["Source Hash"], "original_location": "Barcelona", "official_url": row["Official Job URL"], "reason": "Location exclusion: posting is outside the U.S. (Barcelona, Spain)."}}
        result = publish_cleanup(self.local, self.remote, evidence=proof)
        self.assertEqual(result["verified"], 1)
        self.assertEqual(self.remote.read("Job History")[0]["Location"], "Barcelona")


class EngineCountryTests(ScreeningIntegrationTests):
    def test_verified_country_scope_rejects_before_review(self):
        row = self.stage(location="Rotterdam, Netherlands; Delft", location_country_scope={"us_eligible": False, "source_url": ROOT})[0]
        self.assertEqual(row["Added to Opportunities?"], "No")
        self.assertEqual(row["Review Status"], "Reviewed")

    def test_cleanup_rejection_survives_country_enrichment_on_next_scan(self):
        row = self.stage(location="Barcelona")[0]
        self.repo.commit([{"tab": "Job History", "identity": {"Job Key": row["Job Key"]},
                           "values": {"Added to Opportunities?": "No", "Review Status": "Reviewed", "Decision": "Reject",
                                      "Rejection Reason": "Location exclusion: Barcelona, Spain", "Review Notes": "[US location cleanup] Keep notes"}}])
        row = self.stage(location="Barcelona, Spain")[0]
        self.assertEqual(row["Added to Opportunities?"], "No")
        self.assertEqual(row["Review Status"], "Reviewed")
        self.assertIn("Keep notes", row["Review Notes"])
