import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location("observer", HERE / "confirm_recipe_candidate.py")
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)


class OfflineFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.stage = Path(self.temp.name)
        self.root = self.stage / "candidate"
        package = self.root / "src" / "job_search_helper"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        self.url = "https://amphenol-aerospace.acquiretm.com/job_details_clean.aspx?ID=1"
        description = "D" * 130
        (package / "shared_boards.py").write_text(
            "class Scripts:\n def __init__(self, body): self.body=body\n def jobs(self): return [self.body]\n")
        (package / "company_sources.py").write_text("")
        (package / "cli.py").write_text("def load_environment(path): return None\n")
        (package / "integration_release.py").write_text(
            "import hashlib, json\nfrom pathlib import Path\n"
            "def source_tree_digest(root):\n"
            " paths=list((Path(root)/'src').rglob('*.py'))+[Path(root)/n for n in ('pyproject.toml','title-blacklist.txt','title-review-list.txt') if (Path(root)/n).is_file()]\n"
            " value={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}\n"
            " return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()\n"
            "def config_tree_digest(root): return 'config'\n"
            "def dependency_manifest_digest(root): return 'dependency'\n")
        (package / "acquiretm.py").write_text(
            "SOURCE='https://amphenol-aerospace.acquiretm.com/home.aspx'\n"
            "MODE='complete'\n"
            f"URL={self.url!r}\n"
            f"BODY={{'identifier':{{'value':'1'}},'url':URL,'title':'Engineer','hiringOrganization':{{'name':'Amphenol Aerospace'}},'description':{'%r' % description}}}\n"
            "def parse_listing(body):\n return 1, {'1': {'url':URL,'title':'Engineer'}}, ['page']\n"
            "def inventory(*a, **k):\n parse_listing(None); return {'1': {'url':URL,'title':'Engineer'}}\n"
            "class _DetailClient:\n"
            " def __init__(self): self.request=type('R',(),{'get':lambda s,url:type('X',(),{'status':429 if MODE.startswith('blocked') else 200,'headers':{'Retry-After':'60'} if MODE.startswith('blocked') else {}})()})()\n"
            " def get_body(self,url):\n"
            "  self.request.get(url)\n"
            "  if MODE=='blocked_raise': raise FetchError('429')\n"
            "  if MODE=='blocked_replay': self.request.get(url); raise FetchError('429')\n"
            "  return BODY\n"
            "class FetchError(Exception): pass\n")
        (package / "ats.py").write_text(
            "from . import acquiretm\n"
            "def text(v): return str(v)\n"
            "class Result:\n def __init__(self,status,jobs): self.status=status; self.jobs=jobs; self.source_url=acquiretm.SOURCE; self.ats='AcquireTM'; self.reason=''\n"
            "def fetch_inventory(*a):\n"
            " entries=acquiretm.inventory(); c=acquiretm._DetailClient(); jobs=[]\n"
            " try:\n"
            "  for ident,row in entries.items(): body=c.get_body(row['url']); jobs.append({'posting_id':ident,'url':row['url'],'title':row['title'],'description':body['description']})\n"
            " except acquiretm.FetchError: return Result('blocked',jobs)\n"
            " acquiretm.inventory(); return Result('complete',jobs)\n")
        manifest = observer.source_manifest(self.root)
        acquiretm_sha = hashlib.sha256((package / "acquiretm.py").read_bytes()).hexdigest()
        ats_sha = hashlib.sha256((package / "ats.py").read_bytes()).hexdigest()
        self.prep = {"candidate_root": str(self.root), "candidate_vector_count": 256,
                     "candidate_vector_sha256": observer.digest(manifest), "source_manifest_sha256": observer.digest(manifest),
                     "release_id": "REL-" + "a" * 24, "company_id": "COMP-0490", "source_revision": "b" * 64,
                     "paced_adapter_sha256": acquiretm_sha, "dispatcher_sha256": ats_sha}
        proposal = {"release_id": self.prep["release_id"], "company_id": "COMP-0490", "source_revision": "b" * 64,
                    "config_sha256": "config", "dependency_manifest_sha256": "dependency"}
        self.prep["manifest_sha256"] = observer.digest(proposal)
        (self.stage / "PREPARED.json").write_text(json.dumps(self.prep, sort_keys=True))
        (self.stage / "PROPOSED_MANIFEST.json").write_text(json.dumps(proposal, sort_keys=True))
        self.raw_sha = hashlib.sha256((self.stage / "PREPARED.json").read_bytes()).hexdigest()

    def tearDown(self):
        for key in list(sys.modules):
            if key == "job_search_helper" or key.startswith("job_search_helper."):
                del sys.modules[key]
        self.temp.cleanup()

    def _expected_pass(self):
        cohort = [('1', self.url, 'Engineer')]
        detail = [{"id":"1","url":self.url,"employer":"amphenol aerospace","description_chars":130,
                   "description_sha256":hashlib.sha256(("D" * 130).encode()).hexdigest()}]
        observer.COHORT_SHA256, observer.DETAILS_SHA256 = observer.digest(cohort), observer.digest(detail)

    def test_preparation_binds_raw_bytes_and_manifest(self):
        prep = observer.prepare(self.root, self.raw_sha)
        self.assertEqual(prep["release_id"], "REL-" + "a" * 24)
        with self.assertRaises(RuntimeError):
            observer.prepare(self.root, "0" * 64)

    def test_complete_fixture_uses_normal_calls_and_emits_timing(self):
        self._expected_pass()
        output = []
        ticks = iter((0, 13_000_000_000, 14_000_000_000, 15_000_000_000, 16_000_000_000, 28_000_000_000))
        with patch.object(observer.time, "monotonic_ns", side_effect=lambda: next(ticks)):
            self.assertEqual(observer.evaluate(self.root, observer.prepare(self.root, self.raw_sha), record=output.append), 0)
        self.assertEqual(output[-1]["stage"], "observation_candidate_confirmation_passed")
        starts = [row for row in output if row["stage"] == "detail_start"]
        ends = [row for row in output if row["stage"] == "detail_complete"]
        self.assertEqual(len(starts), len(ends) == 1)
        self.assertIn("monotonic_ns", starts[0]); self.assertEqual(ends[0]["calls"][0]["status"], 200)

    def test_blocked_fetch_error_keeps_first_429_evidence(self):
        self._expected_pass()
        sys.path.insert(0, str(self.root / "src"))
        from job_search_helper import acquiretm
        acquiretm.MODE = "blocked_raise"
        output = []
        self.assertEqual(observer.evaluate(self.root, observer.prepare(self.root, self.raw_sha), record=output.append), 1)
        hold = output[-1]
        self.assertEqual((hold["stage"], hold["status"], hold["retry_after_seconds"]),
                         ("held_provider_rate_limit", 429, 60.0))

    def test_duplicate_attempt_after_hold_is_not_eligible(self):
        self._expected_pass()
        sys.path.insert(0, str(self.root / "src"))
        from job_search_helper import acquiretm
        acquiretm.MODE = "blocked_replay"
        with self.assertRaisesRegex(RuntimeError, "stop cleanly"):
            observer.evaluate(self.root, observer.prepare(self.root, self.raw_sha), record=lambda _: None)

    def test_unpaced_detail_or_final_reread_fails(self):
        with self.assertRaisesRegex(RuntimeError, "detail request"):
            observer.require_normal_pacing([
                {"monotonic_ns": 0, "completed_monotonic_ns": 1},
                {"monotonic_ns": 2, "completed_monotonic_ns": 3},
            ], [{"started_monotonic_ns": 20_000_000_000}])
        with self.assertRaisesRegex(RuntimeError, "final listing"):
            observer.require_normal_pacing([{"monotonic_ns": 0, "completed_monotonic_ns": 10}],
                                            [{"started_monotonic_ns": 11}])


if __name__ == "__main__":
    unittest.main()
