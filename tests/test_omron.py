import unittest

from job_search_helper.omron import (
    ADP_SOURCE, CHINA_HANDOFF, JAPAN_HANDOFF, MANIFEST_SOURCE, REGIONAL_MANIFEST,
    SF_SOURCE, _merge, _validate_manifest,
)
from job_search_helper.ats import FetchError, Inventory


class OmronManifestTests(unittest.TestCase):
    def test_manifest_has_exact_delegated_regions(self):
        self.assertTrue(_validate_manifest())
        self.assertEqual([r.source for r in REGIONAL_MANIFEST],
                         [ADP_SOURCE, SF_SOURCE, SF_SOURCE, JAPAN_HANDOFF, CHINA_HANDOFF])
        self.assertEqual(REGIONAL_MANIFEST[0].provider, "ADP MyJobs")

    def test_wrong_scope_is_rejected_by_merge(self):
        region = REGIONAL_MANIFEST[1]
        bad = Inventory("complete", [{"title": "Wrong", "description": "full", "url": "https://foreign.example/job/1"}])
        # The manifest merger accepts only complete, full rows; the provider
        # adapter is responsible for host scope, so malformed provider rows are rejected.
        with self.assertRaises(FetchError):
            _merge([(region, Inventory("complete", [{"title": "Wrong", "description": "", "url": "https://foreign.example/job/1"}]))])

    def test_duplicate_canonical_urls_are_deduplicated(self):
        a, b = REGIONAL_MANIFEST[1:3]
        rows = lambda ats: [{"posting_id": "1", "ats": ats, "title": "Engineer", "description": "Full description", "url": "https://careers.omron.com/job/1/"}]
        merged = _merge([(a, Inventory("complete", rows("SuccessFactors"))), (b, Inventory("complete", rows("SuccessFactors")))])
        self.assertEqual(len(merged), 1)

    def test_incomplete_delegated_region_blocks_global_completion(self):
        with self.assertRaises(FetchError):
            _merge([(REGIONAL_MANIFEST[0], Inventory("complete", [])),
                    (REGIONAL_MANIFEST[3], Inventory("blocked", [], "handoff unavailable"))])


if __name__ == "__main__":
    unittest.main()
