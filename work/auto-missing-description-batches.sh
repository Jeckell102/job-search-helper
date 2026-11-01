#!/usr/bin/env bash
set -euo pipefail

reviewer='./job-search-reviewer'
run_id='pass-2-5bf6c7fd964e4891acc9b602943e7cf8'
max_batches="${1:-25}"
decision_file=''

submit_verified_on_exit() {
  if [[ -n "$decision_file" && -s "$decision_file" ]]; then
    "$reviewer" --pass 2 --run-id "$run_id" --file "$decision_file" submit >/dev/null || true
    rm -f "$decision_file"
  fi
}
trap submit_verified_on_exit EXIT HUP INT TERM

for ((batch_number=1; batch_number<=max_batches; batch_number++)); do
  claimed="$($reviewer --pass 2 --run-id "$run_id" --limit 4 next)"
  missing_count="$(printf '%s' "$claimed" | node -e 'let source=""; process.stdin.on("data", chunk => source += chunk).on("end", () => console.log(JSON.parse(source).batch.missing_descriptions ?? -1))')"
  item_count="$(printf '%s' "$claimed" | node -e 'let source=""; process.stdin.on("data", chunk => source += chunk).on("end", () => console.log(JSON.parse(source).items.length))')"

  if [[ "$item_count" -eq 0 ]]; then
    printf 'STOPPED: no items claimed after %d batches\n' "$((batch_number - 1))"
    break
  fi
  if [[ "$missing_count" -ne "$item_count" ]]; then
    printf 'STOPPED: batch %d requires individual assessment (missing=%s, items=%s)\n' "$batch_number" "$missing_count" "$item_count"
    break
  fi

  decision_file="$(mktemp /tmp/pass2-missing-description-XXXXXX.jsonl)"
  printf '%s' "$claimed" | node -e '
    let source = "";
    process.stdin.on("data", chunk => source += chunk).on("end", () => {
      const batch = JSON.parse(source);
      const decisions = batch.items.map(item => JSON.stringify({
        job_key: item.job_key,
        source_hash: item.source_hash,
        claim_token: item.claim_token,
        input_version: item.input_version,
        triage_decision: "NEEDS_INFO",
        reason: "Incomplete listing; job description unavailable.",
        description_complete: false,
        evidence_source: "local_sqlite_job_evidence",
        evidence_locator: "local evidence unavailable",
        policy_conflicts: ["Job description unavailable"]
      }));
      require("fs").writeFileSync(process.argv[1], decisions.join("\n") + "\n");
    });
  ' "$decision_file"

  "$reviewer" --pass 2 --run-id "$run_id" --file "$decision_file" submit >/dev/null
  rm -f "$decision_file"
  decision_file=''
  printf 'submitted batch %d (%d records)\n' "$batch_number" "$item_count"
done
