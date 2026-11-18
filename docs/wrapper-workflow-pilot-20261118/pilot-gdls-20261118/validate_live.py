"""Two fresh normal-dispatch reads; public-response evidence only, no publication.

Run with the production virtualenv, -B, and an OS sandbox that exposes the task
checkout read-only and only --output writable. This script is not the sandbox.
HTTPTransport._request is observed, not replaced: all calls use its real
production policy, pacing, retries and network implementation. Human/public
source reconciliation remains required before the final acceptance gate.
"""
import argparse
import dataclasses
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ["GDLS_CHECKPOINT_PATH"] = str(output / "fresh-checkpoint-1.json")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(repo / "src"))
    from job_search_helper import ats

    assert Path(ats.__file__).resolve() == repo / "src/job_search_helper/ats.py"
    # Freeze all source hashes: future repairs can add helper modules.
    sources = {str(p.relative_to(repo)): digest(p.read_bytes())
               for p in sorted((repo / "src").rglob("*.py"))}
    inputs = {"ats": "GD Land Systems", "careers_url": "https://www.gdls.com/careers/",
              "company_id": "COMP-0097", "company": "General Dynamics Land Systems"}
    report = {"utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "argv": sys.argv, "repo": str(repo), "sources": sources, "inputs": inputs,
              "production_transport": True, "transport_injection": False,
              "request_observer": "Delegates unchanged to HTTPTransport._request",
              "passes": [], "requests": [],
              "limitations": ["Automated integrity checks are necessary but insufficient to certify employer scope, full descriptions, and pagination.",
                              "An independent reviewer must reconcile saved public listing/detail bodies against returned IDs and confirm the current source contract.",
                              "Zero jobs cannot pass this pilot without separately reviewed explicit empty-state evidence."]}
    original_request = ats.HTTPTransport._request
    pass_number = 0

    def write_report():
        (output / "live-validation.json").write_text(json.dumps(report, indent=2))

    def observe(self, url, *positional, **keyword):
        started = time.monotonic()
        try:
            response = original_request(self, url, *positional, **keyword)
        except Exception as exc:
            report["requests"].append({"pass": pass_number, "url": url,
                                       "error": type(exc).__name__, "seconds": time.monotonic() - started})
            write_report()
            raise
        index = len(report["requests"]) + 1
        body_name = f"response-{index:04d}.body"
        (output / body_name).write_bytes(response.body)
        report["requests"].append({"pass": pass_number, "url": url,
                                   "status": response.status, "body_file": body_name,
                                   "body_sha256": digest(response.body), "bytes": len(response.body),
                                   "location": response.headers.get("Location", response.headers.get("location", "")),
                                   "seconds": time.monotonic() - started})
        write_report()
        return response

    ats.HTTPTransport._request = observe
    keysets = []
    try:
        for pass_number in (1, 2):
            # Separate fresh checkpoints force all detail reads again. No live
            # inventory DB, production checkpoint or browser profile is opened.
            checkpoint = output / f"fresh-checkpoint-{pass_number}.json"
            os.environ["GDLS_CHECKPOINT_PATH"] = str(checkpoint)
            assert not checkpoint.exists()
            started = time.monotonic()
            inventory = ats.fetch_inventory(**inputs)
            result = dataclasses.asdict(inventory)
            result_path = output / f"inventory-{pass_number}.json"
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            jobs = inventory.jobs
            ids = [str(j.get("posting_id", "")) for j in jobs]
            urls = [j.get("url", "") for j in jobs]
            keys = sorted(zip(ids, urls))
            keysets.append(keys)
            checks = {
                "complete": inventory.status == "complete",
                "nonempty": bool(jobs),
                "unique_nonempty_ids": all(ids) and len(set(ids)) == len(ids),
                "unique_nonempty_urls": all(urls) and len(set(urls)) == len(urls),
                "company_fields": all(j.get("company_id") == inputs["company_id"] and j.get("company") == inputs["company"] for j in jobs),
                "titles_present": all(bool(str(j.get("title", "")).strip()) for j in jobs),
                "description_minimum": all(len(str(j.get("description", "")).strip()) >= 120 for j in jobs),
                "no_pending_details": not inventory.browser_pending_urls,
                "discovery_not_incomplete": not inventory.browser_discovery_incomplete,
            }
            report["passes"].append({"pass": pass_number, "seconds": time.monotonic() - started,
                                     "status": inventory.status, "reason": inventory.reason,
                                     "source_url": inventory.source_url, "jobs": len(jobs),
                                     "checks": checks, "inventory_file": result_path.name,
                                     "inventory_sha256": digest(result_path.read_bytes()),
                                     "id_url_sha256": digest(json.dumps(keys).encode())})
            write_report()
            print(json.dumps(report["passes"][-1]), flush=True)
            if not all(checks.values()):
                report["result"] = "FAIL_LIVE_INTEGRITY_CHECKS"
                return 1
        report["stable_ids_urls"] = keysets[0] == keysets[1]
        current_sources = {str(p.relative_to(repo)): digest(p.read_bytes())
                           for p in sorted((repo / "src").rglob("*.py"))}
        report["sources_unchanged"] = sources == current_sources
        ok = report["stable_ids_urls"] and report["sources_unchanged"]
        report["result"] = "INTEGRITY_PASS_PENDING_PUBLIC_SOURCE_RECONCILIATION" if ok else "FAIL_UNSTABLE_INVENTORY_OR_SOURCE"
        return 0 if ok else 1
    except Exception as exc:
        report["result"] = "FAIL_EXCEPTION"
        report["exception"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        ats.HTTPTransport._request = original_request
        write_report()


if __name__ == "__main__":
    raise SystemExit(main())
