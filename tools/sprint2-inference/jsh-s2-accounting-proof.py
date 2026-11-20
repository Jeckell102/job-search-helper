#!/usr/bin/env python3
"""Offline Sprint 2 accounting proof using real HTTP and disposable SQLite stores."""
import argparse
from contextlib import ExitStack
import hashlib
from http.client import RemoteDisconnected
import importlib
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

MULE = Path("/home/chris/job-search-helper_old/dev/wrapper-coder/tools")
JETSON = Path("/tmp/jsh-s2-f4-qa.QYoY68/jetson")
HOST = "http://127.0.0.1:18790"
USAGE = {"done_reason": "stop", "prompt_eval_count": 12, "eval_count": 8}


def require(condition, reason):
    if not condition:
        raise AssertionError(reason)


def load(name, directory):
    module = importlib.import_module(name)
    require(Path(module.__file__).resolve() == directory / f"{name}.py",
            f"{name} resolved outside the requested source path")
    return module


def sha(module):
    return hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()


def serve(stack, root, jetson, native_calls, responses, response_closed):
    def native_turn(*_args, **_kwargs):
        native_calls.append(1)
        return ({"role": "assistant", "content": "", "tool_calls": [{
            "type": "function", "function": {
                "name": "code_read", "arguments": {"path": "src/never-read.py"}
            }
        }]}, USAGE.copy())

    profile = SimpleNamespace(context_tokens=12288, temperature=0.0)
    modules = {
        "storage": SimpleNamespace(ROOT=root, VERSION="fixture", settings=lambda: {}),
        "cluster": SimpleNamespace(),
        "jobs": SimpleNamespace(),
        "benchlog": SimpleNamespace(),
        "engine": SimpleNamespace(Engine=object, BackendError=type("BackendError", (Exception,), {}),
                                  InputError=type("InputError", (Exception,), {}),
                                  Cancelled=type("Cancelled", (Exception,), {})),
        "routing": SimpleNamespace(route=lambda value: value),
        "assistant_tools": SimpleNamespace(SCHEMAS=[], request_scope=lambda value: value,
                                          schemas_for=lambda _value: []),
        "local_tools": SimpleNamespace(),
        "profile_policy": SimpleNamespace(PROFILES={}, VISIBLE_PROFILES=(), LEGACY_ALIASES={},
                                          resolve_profile=lambda _name: profile,
                                          resolve_output_limit=lambda *_args: 1),
        "context_budget": SimpleNamespace(estimate_context=lambda *_args, **_kwargs: None,
                                          require_output_room=lambda *_args: None),
        "tool_runtime": SimpleNamespace(native_turn=native_turn),
    }
    stack.enter_context(patch.dict(sys.modules, modules))
    remote_store = load("inference_control_store", jetson)
    server = load("server", jetson)
    wrapper = load("wrapper_inference", jetson)

    class Handler(server.Handler):
        def response(self, status, payload):
            responses.append((self.command, status))
            super().response(status, payload)

    class TrackedServer(server.Server):
        def shutdown_request(self, request):
            super().shutdown_request(request)
            if responses == [("POST", 200)]:
                response_closed.set()

    httpd = TrackedServer(("127.0.0.1", 0), Handler, object())
    httpd.backend_generation = lambda: {"service": "ollama.service", "pid": 1, "start_monotonic": 1}
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()

    def shutdown():
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=5)

    stack.callback(shutdown)
    return httpd, (server, wrapper, remote_store)


def prove(mule, jetson):
    with tempfile.TemporaryDirectory(prefix="jsh-s2-accounting-") as tmp, ExitStack() as stack:
        root = Path(tmp)
        stack.enter_context(patch.object(sys, "path", [str(jetson), str(mule), *sys.path]))
        coordinator = load("coordinator", mule)
        task_store = load("coordinator_store", mule)
        inference_store = load("coordinator_inference", mule)

        repo = root / "repo"
        for directory in ("src", "tests", "docs"):
            (repo / directory).mkdir(parents=True)
        (repo / "src/a.py").write_text("value = 1\n")
        (repo / "tests/test_a.py").write_text("def test_a(): assert True\n")
        (repo / "docs/wrapper-development-test-protocol.md").write_text(
            "# Required wrapper development and test protocol\nFollow the fixture tests.\n")
        token = "disposable-local-wrapper-token"
        (root / "bridge-token").write_text(token)
        (root / "config").mkdir()
        (root / "config/wrapper-host.json").write_text(json.dumps({"token": token}))
        for name, value in (("BASE", root), ("ROOT", repo), ("VENV", root / "unused-venv")):
            stack.enter_context(patch.object(coordinator.code, name, value))
        stack.enter_context(patch.object(coordinator.code, "git", return_value=""))

        native_calls, responses = [], []
        response_closed = threading.Event()
        httpd, remote_modules = serve(stack, root, jetson, native_calls, responses, response_closed)

        def make_coordinator():
            result = coordinator.Coordinator(root / "tasks", budget=lambda _messages, _schemas:
                SimpleNamespace(available_generation_tokens=6000, prompt_tokens=50))
            result.workflow_version = 1
            return result

        host = make_coordinator()
        task = host.command({"action": "start", "objective": "Read src/a.py and run tests/test_a.py",
                             "mode": "review"})["id"]
        require(host.store.claim_queued(task) is not None, "Disposable task was not claimed")
        host.store.update(task, phase="inspect")
        initial_tools = host.store.receipts(task)
        direct = build_opener(ProxyHandler({}))
        lost = []
        statuses = []

        def open_local(request, *, timeout):
            target = urlsplit(request.full_url)
            require(f"{target.scheme}://{target.netloc}" == HOST and not target.query and not target.fragment,
                    "Coordinator must use its wrapper endpoint")
            method = request.get_method()
            is_turn = method == "POST" and target.path == "/api/wrapper-turn"
            is_status = method == "GET" and re.fullmatch(r"/api/wrapper-control/[0-9a-f]{32}", target.path)
            require(is_turn or is_status, "Unexpected fixture request")
            local = Request(f"http://127.0.0.1:{httpd.server_port}{target.path}", data=request.data,
                            headers=dict(request.header_items()), method=method)
            if is_status:
                statuses.append(1)
                return direct.open(local, timeout=min(timeout, 5))

            require(not lost, "Coordinator retried the inference")
            payload = json.loads(request.data)
            binding = {key: payload[key] for key in ("request_id", "request_fingerprint", "owner_generation")}
            saved, = task_store.Store(root / "tasks").inference_receipts(task)
            require(saved["status"] == "DISPATCHING" and saved["control_binding"] == binding,
                    "Exact control binding must be durable before the POST")
            with direct.open(local, timeout=5) as response:
                require(response.status == 200, "Fixture adapter did not complete inference")
                result = json.load(response)
            require(response_closed.wait(5), "The server did not close the real HTTP response")
            control = result["control"]
            require(control["status"] == "COMPLETED" and control["request_id"] == binding["request_id"],
                    "The adapter did not durably complete the controlled inference")
            lost.append(control["response_digest"])
            raise RemoteDisconnected("fixture discarded completed HTTP response")

        # Replace only endpoint selection and the client loss boundary.
        stack.enter_context(patch.object(coordinator.urllib.request, "build_opener",
                                         return_value=SimpleNamespace(open=open_local)))
        try:
            host.session(host.store.result_snapshot(task))
        except RemoteDisconnected:
            pass
        else:
            raise AssertionError("Coordinator did not observe the lost HTTP response")

        restarted = make_coordinator()
        pending, = restarted.store.inference_receipts(task)
        binding = pending["control_binding"]
        require(len(lost) == 1 and pending["status"] == "UNCERTAIN", "Lost response was not retained as uncertain")
        require(restarted.store.get(task)["tokens"] == pending["reserved_tokens"] > 20,
                "Ambiguous transport incorrectly released the token reservation")
        stale = dict(binding)
        owner = stale["owner_generation"]
        stale["owner_generation"] = ("1" if owner[0] == "0" else "0") + owner[1:]
        require(coordinator.inference_control_status(stale) is None and responses[-1] == ("GET", 400),
                "The adapter did not refuse the stale owner")
        require(restarted.reconcile_inference({**pending, "control_binding": stale}) is None and
                restarted.store.inference_receipts(task)[0] == pending, "The stale owner changed the local receipt")

        restarted.store.recover(restarted.reconcile_inference)
        final, = restarted.store.inference_receipts(task)
        state = restarted.store.get(task)
        require(final["status"] == "RESPONSE_DROPPED" and final["response_digest"] == lost[0],
                "Recovery did not settle the durable remote completion")
        require(final["observed_usage"] == USAGE and (state["calls"], state["tokens"]) == (1, 20),
                "Recovery did not settle the observed usage exactly once")
        require(state["status"] == "PAUSED_RECOVERY" and restarted.store.receipts(task) == initial_tools,
                "A tool ran or the task was made runnable after response loss")
        require(restarted.store.start_inference_session(task) is None, "The lost turn permitted a new session")
        require(len(statuses) == 3, "Recovery must make one owner-bound status request")
        repeated = restarted.reconcile_inference(final)
        require(repeated["settled"] is False and
                (restarted.store.get(task)["calls"], restarted.store.get(task)["tokens"]) == (1, 20),
                "Repeated reconciliation recharged the completed turn")
        restarted.store.recover(restarted.reconcile_inference)
        require(len(statuses) == 4, "Recovery queried an already terminal receipt")
        require(restarted.store.inference_receipts(task) == [final], "Recovery duplicated or changed the receipt")
        require(native_calls == [1] and [status for status in responses if status[0] == "POST"] == [("POST", 200)],
                "More than one inference POST or native call occurred")

        return {
            "mode": "offline-loopback",
            "source_sha256": {
                "mule": {module.__name__: sha(module) for module in (coordinator, task_store, inference_store)},
                "jetson": {module.__name__: sha(module) for module in remote_modules},
            },
            "adapter_terminal": "COMPLETED",
            "coordinator_terminal": final["status"],
            "task_status": state["status"],
            "stale_owner_http": 400,
            "settled_tokens": state["tokens"],
            "charged_calls": state["calls"],
            "inference_posts": 1,
            "native_calls": len(native_calls),
            "new_tool_receipts": 0,
            "status_requests": len(statuses),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mule", type=Path, default=MULE, help="MuleLab coordinator source directory")
    parser.add_argument("--jetson", type=Path, default=JETSON, help="local copy of the Jetson adapter source")
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    print(json.dumps(prove(args.mule.resolve(strict=True), args.jetson.resolve(strict=True)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
