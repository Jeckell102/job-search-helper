#!/usr/bin/env python3
"""One-shot cross-host Sprint 2 acceptance. Default invocation prints help.

After independent deployed QA and a fresh idle-lane check, run:
    python3.11 -I -B /tmp/jsh-s2-live-accounting-proof.py --run --preflight /absolute/path.json

The operator's preflight JSON must provide verified_unix (Unix seconds),
independent_qa_accepted=true, jetson_lane_idle=true, held_control_generation
(the production MuleLab value), and exact mule_sha256 and jetson_sha256 maps.
MuleLab filenames and Jetson filenames are listed in MULE_FILES and JETSON_FILES.
Jetson hashes and idle status are attested by the operator. The production
MuleLab settings, task state, receipt state, and source hashes are checked here.
Keep queue, campaign, autopilot and pilot held for the whole operation.

The durable one-shot directory is fixed for this host. An existing directory
blocks any new turn. --status-only permits recovery of that same private
receipt by GET, including after interruption. Keep the directory for audit and
recovery. This proof does not invoke a service restart, cancellation, or
orphan settlement.
"""
import argparse
from contextlib import closing, contextmanager
import fcntl
import hashlib
from http.client import RemoteDisconnected
import importlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib import request
from unittest.mock import patch

ROOT = Path("/home/chris/job-search-helper_old/dev/wrapper-coder")
TOOLS = ROOT / "tools"
STATE = Path("/home/chris/.local/state/jsh-s2-live-accounting")
MULE_FILES = {"coordinator.py", "coordinator_store.py", "coordinator_inference.py", "coding_tools.py", "host_server.py"}
JETSON_FILES = {"server.py", "wrapper_inference.py", "inference_control_store.py"}
BRIDGE = "http://127.0.0.1:18790"
MESSAGES = [{"role": "user", "content": "Reply with exactly OK."}]
OUTPUT_LIMIT = 32
PROMPT_RESERVATION = 256
MAX_RESPONSE = 150000
HEX = re.compile(r"[0-9a-f]{64}")
REQUEST_ID = re.compile(r"[0-9a-f]{32}")


class ProofStopped(Exception):
    """Only fixed, public-facing descriptions belong in this exception."""


class Dropped(RemoteDisconnected):
    pass


class RefuseRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProofStopped("Tunnel redirect refused.")


def require(condition, message):
    if not condition:
        raise ProofStopped(message)


def identity(path):
    attrs = path.stat()
    return attrs.st_dev, attrs.st_ino, attrs.st_size, attrs.st_mtime_ns


def no_wal(database):
    wal = database.with_name(database.name + "-wal")
    try:
        return wal.stat().st_size == 0
    except FileNotFoundError:
        return True


def production_controls(generation):
    database = ROOT / "tasks/tasks.sqlite3"
    require(database.resolve(strict=True) == database and no_wal(database),
            "Production coordinator database has an unresolved WAL or unexpected path.")
    initial = identity(database)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        values = {key: json.loads(value) for key, value in db.execute(
            "SELECT key,value FROM settings WHERE key IN "
            "('queue_enabled','campaign_enabled','autopilot_enabled','pilot_task','control_generation')")}
        held = all(values.get(key) is False for key in ("queue_enabled", "campaign_enabled", "autopilot_enabled"))
        active = db.execute("SELECT 1 FROM tasks WHERE json_extract(state,'$.status') "
                            "IN ('QUEUED','RUNNING','PAUSING') LIMIT 1").fetchone()
        unresolved = db.execute("SELECT 1 FROM inference_receipts WHERE status "
                                "IN ('DISPATCHING','UNCERTAIN') LIMIT 1").fetchone()
    require(initial == identity(database) and no_wal(database),
            "Production coordinator database changed during hold verification.")
    require(held and values.get("pilot_task") is None and active is None and unresolved is None,
            "Production queue, campaign, autopilot, and pilot must be held with no active work.")
    require(type(values.get("control_generation")) is int and values["control_generation"] == generation,
            "Production coordinator control generation differs from the preflight.")


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def checkpoint(data):
    scratch = STATE / ".checkpoint.pending"
    try:
        scratch.unlink()
    except FileNotFoundError:
        pass
    fd = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(data, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(scratch, STATE / "checkpoint.json")
    sync_directory(STATE)


@contextmanager
def state_lease(create):
    require(STATE.parent.resolve(strict=True) == STATE.parent, "Unexpected private state parent.")
    if create:
        try:
            STATE.mkdir(mode=0o700)
        except FileExistsError:
            raise ProofStopped("One-shot state already exists. Only status recovery is available.") from None
        sync_directory(STATE.parent)
    fd = os.open(STATE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
                "One-shot state must be owned by the operator with mode 0700.")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(identity(STATE)[:2] == (info.st_dev, info.st_ino), "Private state directory was replaced.")
        yield
    finally:
        os.close(fd)


def private_regular(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1,
            "Expected an operator-owned private file.")


def verified_plan(plan, *, fresh):
    require(isinstance(plan, dict) and set(plan) == {"verified_unix", "independent_qa_accepted",
            "jetson_lane_idle", "held_control_generation", "mule_sha256", "jetson_sha256"},
            "Preflight has unexpected fields.")
    require(plan["independent_qa_accepted"] is True and plan["jetson_lane_idle"] is True,
            "Independent acceptance and an idle Jetson lane must be verified.")
    verified = plan["verified_unix"]
    require(type(verified) in (int, float) and (not fresh or 0 <= time.time() - verified <= 300),
            "Obtain fresh deployed preflight before dispatch.")
    generation = plan["held_control_generation"]
    require(type(generation) is int and generation >= 0, "Invalid preflight control generation.")
    for key, names in (("mule_sha256", MULE_FILES), ("jetson_sha256", JETSON_FILES)):
        hashes = plan[key]
        require(isinstance(hashes, dict) and set(hashes) == names and
                all(isinstance(digest, str) and HEX.fullmatch(digest) for digest in hashes.values()),
                "Preflight source pins are incomplete.")
    production_controls(generation)
    verify_mule(plan)
    return generation


def verify_mule(plan):
    for name, expected in plan["mule_sha256"].items():
        path = TOOLS / name
        require(path.resolve(strict=True) == path and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                "Installed MuleLab source differs from independent QA pins.")


def load_installed():
    sys.dont_write_bytecode = True
    sys.pycache_prefix = "/dev/null"
    sys.path.insert(0, str(TOOLS))
    modules = [importlib.import_module(name) for name in ("coordinator", "coordinator_inference")]
    coordinator, inference = modules
    for module in (*modules, coordinator.code, sys.modules["coordinator_store"]):
        require(Path(module.__file__).resolve() == TOOLS / f"{module.__name__}.py",
                "A coordinator dependency resolved outside the installed source.")
    require(coordinator.code.BASE == ROOT and hasattr(inference, "valid_owned_inference_receipt"),
            "The reviewed sender and owned-receipt validation must be installed.")
    private_regular(ROOT / "bridge-token")
    return coordinator, inference


def create_reservation(coordinator, inference):
    repo = STATE / "synthetic-checkout"
    for name in ("src", "docs", "tests"):
        (repo / name).mkdir(parents=True, exist_ok=False)
    (repo / "src/placeholder.py").write_text("value = 1\n", encoding="utf-8")
    workspace = importlib.import_module("coordinator_workspace")
    host = coordinator.Coordinator(STATE / "ledger")
    require(host.store.base == STATE / "ledger", "Disposable ledger path mismatch.")
    with patch.object(coordinator.code, "ROOT", repo), patch.object(workspace, "batch_source", return_value=repo):
        task = host.store.create("Review src/placeholder.py for the synthetic Sprint 2 receipt proof",
                                 [], "review", max_sessions=1)["id"]
    require(host.store.claim_queued(task) is not None, "Could not claim the disposable task.")
    state = host.store.start_inference_session(task, max_calls=1, max_tokens=PROMPT_RESERVATION + OUTPUT_LIMIT)
    require(state is not None, "Could not open the disposable inference session.")
    generation = host.store.control_generation()
    reservation = host.store.reserve_inference(
        task, phase=state["phase"], prompt_digest=inference.digest(MESSAGES),
        tools_digest=inference.digest([]), prompt_tokens=PROMPT_RESERVATION, output_tokens=OUTPUT_LIMIT,
        expected_control_generation=generation, session_id=state["inference_session_id"], max_calls=1,
        max_tokens=PROMPT_RESERVATION + OUTPUT_LIMIT, min_output_tokens=OUTPUT_LIMIT)
    require(reservation is not None, "Could not make the disposable inference reservation.")
    payload = {"messages": MESSAGES, "tools": [], "max_tokens": OUTPUT_LIMIT}
    binding = {
        "request_id": reservation["request_id"],
        "request_fingerprint": inference.digest(payload),
        "owner_generation": inference.digest({
            "task": task, "session_id": state["inference_session_id"],
            "control_generation": generation, "identity_digest": reservation["identity_digest"],
            "phase": reservation["phase"],
        }),
    }
    host.store.bind_inference_control(reservation["request_id"], binding)
    (saved,) = host.store.inference_receipts(task)
    require(saved["status"] == "DISPATCHING" and saved["control_binding"] == binding,
            "The exact ownership binding was not persisted.")
    require(host.store.receipts(task) == [], "Unexpected tool receipt in the disposable ledger.")
    sync_directory(host.store.base)
    sync_directory(STATE)
    return task, binding, payload


def completion(inference, raw, binding):
    data = json.loads(raw)
    require(isinstance(data, dict), "Adapter completion was not an object.")
    receipt = data.pop("control", None)
    require(isinstance(receipt, dict) and set(receipt) == {"request_id", "status", "response_digest", "usage"}
            and receipt["request_id"] == binding["request_id"] and receipt["status"] == "COMPLETED",
            "Adapter did not return a matching completion.")
    require(set(data) == {"message", "usage", "context_tokens"} and isinstance(data["message"], dict)
            and type(data["context_tokens"]) is int and data["context_tokens"] > 0
            and not data["message"].get("tool_calls") and inference.valid_inference_usage(data["usage"])
            and receipt["response_digest"] == inference.digest(data) and receipt["usage"] == data["usage"],
            "Adapter completion digest, usage, or tool boundary failed verification.")
    return receipt["response_digest"], receipt["usage"]


def dispatch(plan):
    generation = verified_plan(plan, fresh=True)
    coordinator, inference = load_installed()
    with state_lease(create=True):
        record = {"schema": "jsh-s2-one-shot-v1", "phase": "PREPARING", "plan": plan}
        checkpoint(record)
        task, binding, payload = create_reservation(coordinator, inference)
        record.update(phase="BOUND", task=task, binding=binding)
        checkpoint(record)
        direct = request.build_opener(request.ProxyHandler({}), RefuseRedirect())
        attempted = False

        def discard_once(outgoing, *, timeout):
            nonlocal attempted
            require(not attempted and outgoing.full_url == BRIDGE + "/api/wrapper-turn"
                    and outgoing.get_method() == "POST" and json.loads(outgoing.data) == {**payload, **binding},
                    "Sender attempted a second or out-of-scope request.")
            require(verified_plan(plan, fresh=True) == generation, "Preflight changed before dispatch.")
            private_regular(ROOT / "bridge-token")
            record["phase"] = "POST_MAY_HAVE_BEEN_SENT"
            checkpoint(record)
            attempted = True
            with direct.open(outgoing, timeout=min(timeout, 90)) as reply:
                require(reply.status == 200, "Adapter did not return successful HTTP completion.")
                raw = reply.read(MAX_RESPONSE + 1)
            require(0 < len(raw) <= MAX_RESPONSE, "Adapter response exceeded the bounded proof size.")
            digest, usage = completion(inference, raw, binding)
            record.update(phase="RESPONSE_DISCARDED", response_digest=digest, http_usage=usage)
            checkpoint(record)
            raise Dropped("intentional post-completion drop")

        control = coordinator.INFERENCE_CONTROL.set(binding)
        try:
            with patch.object(coordinator.urllib.request, "build_opener",
                              return_value=SimpleNamespace(open=discard_once)):
                coordinator.infer(MESSAGES, [], OUTPUT_LIMIT)
        except Dropped:
            pass
        else:
            raise ProofStopped("Lost response escaped the controlled client boundary.")
        finally:
            coordinator.INFERENCE_CONTROL.reset(control)
        require(attempted and record["phase"] == "RESPONSE_DISCARDED", "No durable response-drop checkpoint.")
    return subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--status-only"],
                          check=False).returncode


def recover():
    with state_lease(create=False):
        path = STATE / "checkpoint.json"
        private_regular(path)
        record = json.loads(path.read_text(encoding="utf-8"))
        require(record.get("schema") == "jsh-s2-one-shot-v1" and record.get("phase") in
                {"POST_MAY_HAVE_BEEN_SENT", "RESPONSE_DISCARDED", "VERIFIED", "RECOVERED"},
                "There is no dispatched owner-bound turn to recover.")
        if record["phase"] in {"VERIFIED", "RECOVERED"}:
            print("The one-shot receipt was already closed. No request was made.")
            return 0 if record["phase"] == "VERIFIED" else 2
        plan = record["plan"]
        generation = verified_plan(plan, fresh=False)
        coordinator, inference = load_installed()
        task, binding = record["task"], record["binding"]
        rid = binding.get("request_id")
        require(isinstance(rid, str) and REQUEST_ID.fullmatch(rid)
                and inference.valid_inference_binding(binding, rid), "Saved ownership binding is invalid.")
        host = coordinator.Coordinator(STATE / "ledger")
        (saved,) = host.store.inference_receipts(task)
        require(saved["control_binding"] == binding and host.store.receipts(task) == [],
                "Disposable durable receipt differs from the dispatch checkpoint.")
        saved_digest = record.get("response_digest")
        http_usage = record.get("http_usage")
        require(record["phase"] != "RESPONSE_DISCARDED" or
                (isinstance(saved_digest, str) and HEX.fullmatch(saved_digest)
                 and inference.valid_inference_usage(http_usage)),
                "The saved response-drop observation is incomplete.")
        status_count = 0
        retained = []
        direct = request.build_opener(request.ProxyHandler({}), RefuseRedirect())

        def owned_get(outgoing, *, timeout):
            nonlocal status_count
            request_headers = {key.lower(): value for key, value in outgoing.header_items()}
            require(outgoing.get_method() == "GET" and outgoing.data is None and
                    outgoing.full_url == BRIDGE + "/api/wrapper-control/" + rid and status_count < 2 and
                    request_headers.get("x-wrapper-request-fingerprint") == binding["request_fingerprint"] and
                    request_headers.get("x-wrapper-owner-generation") == binding["owner_generation"],
                    "Only bounded GET for the saved owner is permitted.")
            production_controls(generation)
            status_count += 1
            return direct.open(outgoing, timeout=min(timeout, 10))

        original_status = coordinator.inference_control_status

        def verified_status(control):
            require(control == binding, "Recovery attempted to use a different owner.")
            value = original_status(control)
            if (not inference.valid_owned_inference_receipt(value, rid) or value["status"] != "COMPLETED"
                    or value["cancel_requested"]
                    or value["response_digest"] is None or value["usage"] is None
                    or (saved_digest is not None and
                        (value["response_digest"], value["usage"]) != (saved_digest, http_usage))):
                return None
            usage = value["usage"]
            require(usage["prompt_eval_count"] <= PROMPT_RESERVATION and usage["eval_count"] <= OUTPUT_LIMIT
                    and usage["prompt_eval_count"] + usage["eval_count"] > 0,
                    "Retained usage exceeds the synthetic reservation or is empty.")
            proof = value["response_digest"], usage
            require(not retained or retained[0] == proof, "The retained completion changed between GETs.")
            retained.append(proof)
            return value

        with patch.object(coordinator.urllib.request, "build_opener",
                          return_value=SimpleNamespace(open=owned_get)), \
                patch.object(coordinator, "inference_control_status", verified_status):
            was_pending = saved["status"] in ("DISPATCHING", "UNCERTAIN")
            host.store.recover(host.reconcile_inference)
            (receipt,) = host.store.inference_receipts(task)
            require(receipt["status"] == "RESPONSE_DROPPED", "Owned completion unavailable. Existing recovery hold retained.")
            usage = receipt["observed_usage"]
            require(inference.valid_inference_usage(usage), "The disposable settlement did not save valid usage.")
            tokens = usage["prompt_eval_count"] + usage["eval_count"]
            state = host.store.get(task)
            require(state["status"] == "PAUSED_RECOVERY" and (state["calls"], state["tokens"]) == (1, tokens)
                    and host.store.receipts(task) == [], "Accounting or tool boundary failed.")
            again = host.reconcile_inference(receipt)
            after = host.store.get(task)
            require(again is not None and again["settled"] is False and
                    retained and retained[0] == (receipt["response_digest"], usage) and
                    (after["calls"], after["tokens"]) == (1, tokens) and
                    status_count == (2 if was_pending else 1) and
                    host.store.inference_receipts(task) == [receipt] and host.store.receipts(task) == [],
                    "Repeated owner-bound GET changed accounting.")
        production_controls(generation)
        verify_mule(plan)
        record.update(phase="VERIFIED" if saved_digest is not None else "RECOVERED",
                      calls=1, tokens=tokens, tool_receipts=0)
        checkpoint(record)
        if saved_digest is None:
            print("Owned completion recovered without a durable response-drop observation.")
            return 2
        print(json.dumps({"result": "PASS", "remote_terminal": "COMPLETED",
                          "local_terminal": "RESPONSE_DROPPED", "calls": 1, "tokens": tokens,
                          "tool_receipts": 0, "status_gets": status_count}, sort_keys=True))
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--run", action="store_true", help="authorize one bounded synthetic turn")
    modes.add_argument("--status-only", action="store_true", help="reconcile the existing owner by GET only")
    parser.add_argument("--preflight", type=Path, help="independently verified deployed pins and idle controls")
    args = parser.parse_args()
    if not (args.run or args.status_only):
        parser.print_help()
        return 0
    os.umask(0o077)
    try:
        if args.run:
            require(args.preflight is not None and args.preflight.is_absolute(),
                    "An absolute independent preflight file path is required.")
            return dispatch(json.loads(args.preflight.read_text(encoding="utf-8")))
        require(args.preflight is None, "Status recovery uses only its saved preflight.")
        return recover()
    except ProofStopped as error:
        print(f"STOPPED. {error}", file=sys.stderr)
    except (Exception, KeyboardInterrupt) as error:
        print(f"STOPPED. {type(error).__name__}. Preserve the private checkpoint for status recovery.",
              file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
