import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RECIPE_PATH = ROOT / "repair_recipe" / "acquiretm_membership_recipe.py"
SOURCE_PATH = ROOT / "src" / "job_search_helper" / "acquiretm.py"
WITNESS_PATH = Path("/tmp/jsh-s5-amphenol-typed-live/result.json")
RAW_RESULT_PATH = Path("/tmp/jsh-s5-amphenol-raw-fixture/result.json")
RAW_RESULT_SHA256 = "acc0ba9b1fa8855dc588cc28d9911bf4ab6fa58816cba426e8ca9954437e4bdf"


def recipe():
    spec = importlib.util.spec_from_file_location("acquiretm_recipe", RECIPE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DelayedPage:
    """Synthetic Playwright page: the original HTML change appears at 98 ms;
    a new same-board ID is available only at the W1 347-ms transition.
    """
    def __init__(self):
        self.url = "https://amphenol-aerospace.acquiretm.com/home.aspx"
        self.ids, self.wait = ["1"], None

    def goto(self, url, **_kwargs):
        assert url == self.url

    def content(self):
        links = "".join('<a href="job_details_clean.aspx?ID=%s">Engineer %s</a>' % (i, i) for i in self.ids)
        return '<div>2 positions found.</div>' + links + '<a aria-label="Go to page 2 of job results">page</a>'

    def get_by_role(self, role, *, name, exact):
        self.asserted = (role, name, exact)
        return type("Link", (), {"click": lambda _self, **_kw: None})()

    def wait_for_function(self, predicate, *, arg, timeout):
        self.wait = (predicate, arg, timeout)
        self.ids = ["2"]


class RawDelayedPage:
    """Private raw W1 samples; HTML remains outside reports and receipts."""
    def __init__(self):
        raw = json.loads(RAW_RESULT_PATH.read_text())
        assert hashlib.sha256(RAW_RESULT_PATH.read_bytes()).hexdigest() == RAW_RESULT_SHA256
        root = RAW_RESULT_PATH.parent
        self.preclick = (root / raw["snapshots"][1]["file"]).read_text()
        self.premature = (root / raw["snapshots"][2]["file"]).read_text()
        self.late = (root / raw["snapshots"][3]["file"]).read_text()
        self.current = self.preclick
        self.url = "https://amphenol-aerospace.acquiretm.com/home.aspx"
        self.wait = None

    def goto(self, url, **_kwargs):
        assert url == self.url
        self.current = self.preclick

    def content(self):
        return self.current

    def get_by_role(self, role, *, name, exact):
        assert (role, name, exact) == ("link", "Go to page 2 of job results", True)
        owner = self
        class Link:
            def click(self, **_kwargs):
                owner.current = owner.premature
        return Link()

    def wait_for_function(self, predicate, *, arg, timeout):
        self.wait = (predicate, arg, timeout)
        self.current = self.late


class RecipeTests(unittest.TestCase):
    def test_only_w1_and_exact_pins_are_accepted(self):
        module = recipe()
        source, witness = SOURCE_PATH.read_bytes(), WITNESS_PATH.read_bytes()
        result = module.build(source, {"strategy": "listing_membership_change", "evidence": "W1"}, witness)
        self.assertEqual(result["receipt"]["source_sha256"], module.SOURCE_SHA256)
        self.assertEqual(result["receipt"]["witness_sha256"], module.WITNESS_SHA256)
        self.assertTrue(result["receipt"]["pre_repair_diagnostic_retained"])
        for selection in ({}, {"strategy": "html_change", "evidence": "W1"},
                          {"strategy": "listing_membership_change", "evidence": "W2"}):
            with self.assertRaises(ValueError):
                module.build(source, selection, witness)

    def test_actual_inventory_callback_waits_for_new_same_board_id(self):
        module = recipe()
        result = module.build(SOURCE_PATH.read_bytes(), module.SELECTION, WITNESS_PATH.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "candidate.py"
            target.write_text(result["source"])
            spec = importlib.util.spec_from_file_location("job_search_helper.acquiretm_candidate", target)
            candidate = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(candidate)
            page = DelayedPage()
            self.assertEqual(set(candidate.inventory(page)), {"1", "2"})
        predicate, arg, timeout = page.wait
        self.assertIn("previous.has(id)", predicate)
        self.assertEqual(arg, {"path": "/job_details_clean.aspx", "seen": ["1"]})
        self.assertEqual(timeout, candidate.ACQUIRETM_REFRESH_TIMEOUT_MS)

    def test_private_raw_w1_callback_requires_late_membership(self):
        module = recipe()
        result = module.build(SOURCE_PATH.read_bytes(), module.SELECTION, WITNESS_PATH.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "candidate.py"
            target.write_text(result["source"])
            spec = importlib.util.spec_from_file_location("job_search_helper.acquiretm_raw_candidate", target)
            candidate = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(candidate)
            page = RawDelayedPage()
            total, first, _ = candidate.parse_listing(page.preclick)
            premature_total, premature, _ = candidate.parse_listing(page.premature)
            late_total, late, _ = candidate.parse_listing(page.late)
            self.assertEqual((total, premature_total, late_total), (39, 39, 39))
            self.assertEqual((len(first), len(premature), len(late)), (25, 25, 14))
            self.assertEqual(first, premature)
            self.assertFalse(first.keys() & late.keys())
            self.assertEqual(len(candidate.inventory(page)), 39)
        predicate, arg, timeout = page.wait
        self.assertIn("previous.has(id)", predicate)
        self.assertEqual(len(arg["seen"]), 25)
        self.assertEqual(timeout, candidate.ACQUIRETM_REFRESH_TIMEOUT_MS)


if __name__ == "__main__":
    unittest.main()
