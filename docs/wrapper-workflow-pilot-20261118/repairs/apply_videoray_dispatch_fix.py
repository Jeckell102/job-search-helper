"""Move VideoRay's HTML/API split to normal dispatch and verify it."""
from pathlib import Path
import hashlib
import sys


TOOLS = Path("/home/chris/job-search-helper_old/dev/wrapper-coder/tools")
TASKS = Path("/home/chris/job-search-helper_old/dev/wrapper-coder/tasks")
TASK_ID = "WRAP-5bbb2a9156"
sys.path.insert(0, str(TOOLS))

import coding_tools as code
from coordinator import manifest
from coordinator_store import Store
from coordinator_workspace import workspace


def execute(store, state, name, arguments):
    receipt = store.intent(TASK_ID, state["phase"], name, arguments)
    result = code.execute(name, arguments, {name})
    store.finish(receipt, result)
    if not result.get("ok"):
        raise RuntimeError(f"receipt {receipt} failed: {result}")
    print(receipt, name)
    return result


def edit(store, state, path, old, new):
    target = code.root() / path
    arguments = {
        "path": path,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "old": old,
        "new": new,
    }
    return execute(store, state, "code_edit", arguments)


store = Store(TASKS)
state = store.get(TASK_ID)
with workspace(store, state):
    edit(
        store, state, "src/job_search_helper/videoray.py",
        "from .ats import FetchError, HTTPTransport, Inventory, _base, text\nfrom .discovery import CareersTransport\nfrom .workday import fetch_workday",
        "from .ats import FetchError, HTTPTransport, Inventory, _base, text\nfrom .workday import fetch_workday",
    )
    edit(
        store, state, "src/job_search_helper/videoray.py",
        "    transport = transport or HTTPTransport()\n    discovery_transport = discovery_transport or CareersTransport()",
        "    transport = transport or HTTPTransport()\n    discovery_transport = discovery_transport or transport",
    )
    edit(
        store, state, "src/job_search_helper/ats.py",
        "    if company_id == \"COMP-0348\" and company.casefold() == \"videoray\":\n        from .videoray import fetch_videoray\n        return fetch_videoray(careers_url, company_id, company, transport or HTTPTransport(), html_transport)",
        "    if company_id == \"COMP-0348\" and company.casefold() == \"videoray\":\n        from .discovery import CareersTransport\n        from .videoray import fetch_videoray\n        return fetch_videoray(careers_url, company_id, company, transport or HTTPTransport(),\n                              html_transport or CareersTransport())",
    )
    edit(
        store, state, "tests/test_videoray.py",
        "import job_search_helper.ats as ats_module\nimport job_search_helper.videoray as videoray_module",
        "import job_search_helper.ats as ats_module\nimport job_search_helper.discovery as discovery_module",
    )
    edit(
        store, state, "tests/test_videoray.py",
        "    monkeypatch.setattr(videoray_module, \"CareersTransport\", lambda: local)",
        "    monkeypatch.setattr(discovery_module, \"CareersTransport\", lambda: local)",
    )
    tests = execute(store, state, "code_test", {"paths": "tests/test_videoray.py tests/test_workday.py tests/test_workday_leidos.py tests/test_workday_leidos_reconcile.py tests/test_workday_reconcile.py"})
    if tests["result"].get("exit_code") != 0:
        raise RuntimeError("Focused tests failed; task remains paused for inspection.")
    execute(store, state, "code_diff", {})
    current_manifest = manifest()

store.update(
    TASK_ID,
    manifest=current_manifest,
    phase="verify",
    status="QUEUED",
    stop_requested=False,
    no_progress=0,
    reason="Receipt-backed dispatcher transport split passed focused tests; independent verification queued.",
    checkpoint={"summary": "Jetson found the transport mismatch; MuleLab moved the HTML/API split to normal dispatch and focused tests passed.",
                "next_action": "Run the coordinator independent verification, then live normal-dispatch validation.",
                "outcome": "phase_done"},
)
store.export(TASK_ID)
