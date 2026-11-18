"""Apply the receipt-backed VideoRay correction inside one isolated task."""
from pathlib import Path
import hashlib
import sys


TOOLS = Path("/home/chris/job-search-helper_old/dev/wrapper-coder/tools")
TASKS = Path("/home/chris/job-search-helper_old/dev/wrapper-coder/tasks")
TASK_ID = "WRAP-5bbb2a9156"
sys.path.insert(0, str(TOOLS))

import coding_tools as code
from coordinator_store import Store
from coordinator_workspace import workspace


def guarded_edit(store, state, path, old, new):
    target = code.root() / path
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    arguments = {"path": path, "sha256": digest, "old": old, "new": new}
    receipt = store.intent(TASK_ID, "implement", "code_edit", arguments)
    result = code.execute("code_edit", arguments, {"code_edit"})
    store.finish(receipt, result)
    if not result.get("ok"):
        raise RuntimeError(f"receipt {receipt} failed: {result}")
    print(receipt, result["result"]["sha256"])


store = Store(TASKS)
state = store.get(TASK_ID)
with workspace(store, state):
    guarded_edit(
        store,
        state,
        "src/job_search_helper/videoray.py",
        "from .ats import FetchError, HTTPTransport, Inventory, _base, text, CareersTransport\nfrom .workday import fetch_workday",
        "from .ats import FetchError, HTTPTransport, Inventory, _base, text\nfrom .discovery import CareersTransport\nfrom .workday import fetch_workday",
    )
    guarded_edit(
        store,
        state,
        "src/job_search_helper/videoray.py",
        "    transport = transport or HTTPTransport()\n    discovery_transport = discovery_transport or transport",
        "    transport = transport or HTTPTransport()\n    discovery_transport = discovery_transport or CareersTransport()",
    )
    guarded_edit(
        store,
        state,
        "tests/test_videoray.py",
        "from job_search_helper.ats import HTTPResponse, fetch_inventory\nfrom job_search_helper.videoray import SOURCE, fetch_videoray",
        "import job_search_helper.ats as ats_module\nimport job_search_helper.videoray as videoray_module\nfrom job_search_helper.ats import HTTPResponse, fetch_inventory\nfrom job_search_helper.videoray import SOURCE, fetch_videoray",
    )
    guarded_edit(
        store,
        state,
        "tests/test_videoray.py",
        "def test_normal_dispatch_uses_videoray_adapter():\n    transport = Transport([response({\"total\": 0, \"jobPostings\": [], \"facets\": []})])\n    transport.responses = [HTTPResponse(200, LOCAL_INDEX), HTTPResponse(200, LOCAL_DETAIL), *transport.responses]\n    result = fetch_inventory(\"Workday (shared parent board)\", SOURCE, \"COMP-0348\", \"VideoRay\", transport)\n    assert result.status == \"complete\", result.reason\n    assert result.ats == \"VideoRay local + AVAV Workday\"",
        "def test_normal_dispatch_uses_videoray_adapter():\n    transport = Transport([response({\"total\": 0, \"jobPostings\": [], \"facets\": []})])\n    transport.responses = [HTTPResponse(200, LOCAL_INDEX), HTTPResponse(200, LOCAL_DETAIL), *transport.responses]\n    result = fetch_inventory(\"Workday (shared parent board)\", SOURCE, \"COMP-0348\", \"VideoRay\", transport)\n    assert result.status == \"complete\", result.reason\n    assert result.ats == \"VideoRay local + AVAV Workday\"\n\n\ndef test_normal_dispatch_builds_separate_default_transports(monkeypatch):\n    api = Transport([response({\"total\": 1, \"jobPostings\": [listing()], \"facets\": []}), response(detail())])\n    local = Transport([HTTPResponse(200, LOCAL_INDEX), HTTPResponse(200, LOCAL_DETAIL)])\n    monkeypatch.setattr(ats_module, \"HTTPTransport\", lambda: api)\n    monkeypatch.setattr(videoray_module, \"CareersTransport\", lambda: local)\n\n    result = fetch_inventory(\"Workday (shared parent board)\", SOURCE, \"COMP-0348\", \"VideoRay\")\n\n    assert result.status == \"complete\", result.reason\n    assert len(result.jobs) == 1\n    assert len(api.posts) == 1\n    assert not local.posts\n    assert not api.responses\n    assert not local.responses",
    )

state = store.get(TASK_ID)
store.update(
    TASK_ID,
    workflow={**state.get("workflow", {}), "stall_turns": 0, "last_action": None,
              "finish_requested": True},
    checkpoint={"summary": "Jetson diagnosed the transport split and authored the first guarded edit; MuleLab corrected its import and completed the exact receipt-backed repair and regression test.",
                "next_action": "Run the focused test suite and inspect the nonempty diff.",
                "outcome": "phase_done"},
    reason="Receipt-backed VideoRay transport repair is ready for focused verification.",
    status="QUEUED",
    no_progress=0,
)
store.export(TASK_ID)
