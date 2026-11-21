# Independent Amphenol fresh-window result

**HOLD confirmed. No qualification PASS or release is established.** Read-only artifact QA of the single new window prepared at 2026-11-21 13:15:42 Eastern. The log starts 18:15:56.842112 UTC (13:15:56 Eastern) on exact Company COMP-0490, Amphenol Aerospace, AcquireTM and `https://amphenol-aerospace.acquiretm.com/home.aspx`.

There are exactly four logged events: started, one listing_observed, dispatch_returned blocked, and failed/RuntimeError (`normal dispatch is not complete`). Initial listing pages contain 25 and 14 disjoint IDs, total 39. I compared the actual ID/title/URL entries to the earlier complete run 1: they are equal, with membership digest ff45144db9475e3978bd06cf64ec00669f43eaa03da13088849230494e2c6877. This is an initial-listing observation only; there is no final reread.

Dispatch returned count 0 and details_observed 0 after one listing pass, with reason `AcquireTM detail request remained rate-limited or unavailable.` Zero observed details means no successfully observed detail response in this evaluator; it does not mean no detail requests were attempted. The adapter retains bounded internal retries. No raw HTTP status, response headers, Retry-After value or detail response body is saved here. The observed classification is blocked; this report does not assert an independently verified HTTP 429, outage cause, account/IP policy or recovery deadline.

There is no run_verified, successful normalized-detail comparison, separate_candidate_confirmation_passed or candidate_live_checks_passed event. The supplied foreground exit 1 agrees with the final exception and unchanged evaluator's exception-to-exit 1 path. stderr is empty. The preparation bounds one normal dispatch and 240 wall seconds, but these artifacts do not themselves record the actual end time or external timeout-controller result.

The exact evaluator and 256-member candidate vector are unchanged. I recomputed the vector rather than trusting PREPARED.json. Original evidence and prior failed confirmation hashes also remain exact. Thus this new result does not replace or reinterpret the earlier complete 39, blocked 35 and blocked 37 results. The accumulated evidence remains one complete observation followed by three incomplete confirmations (35, 37, 0 details). Combining them cannot establish complete repeated coverage.

| Artifact | Verified SHA-256 |
| --- | --- |
| New PREPARED.json | 90428b72dca8de0ab73777c1b47997c584c2d73f2594c446396adc5e24b3b076 |
| New confirmation.jsonl | 0fef582b880b4e63a8745a5773f4cf5440e7027e2fe932334b11e202f60f3520 |
| New empty stderr.txt | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| Accepted confirmation evaluator | 43ab6b9f3899b289992d95d9e79c6ff3c625fa7518cdb969bfda06fcc2a753a5 |
| Candidate 256-member vector | 7e371be5094a3d23de58af47e8e8607c7f64d6d35a4a7e58bfb365baa132bdea |
| Adapter | 895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d |
| Dispatcher | 111ccb9067402832ad96b798100dfca293668cf24830409874c1ab4d6eaac07e |
| Prior 39/35 log | dfd69d46fd48deeeab7feb88d457ba01978d5ef5d4ae4548adc076df5d41638e |
| Prior 37 confirmation log | 7fe4af029b0f6f40b7b97ea1ebc02ad812e9aa344965f4c38281aa364f3f8d01 |

Inputs are `/tmp/jsh-amphenol-fresh-validation.c9e37dss/{PREPARED.json,confirmation.jsonl,stderr.txt}` and the prior unchanged `/tmp/jsh-amphenol-current-validation.fehq8g9f` candidate/evaluator/logs. The evaluator is public-read-only and has no deployment, application storage or release receipt operation. These artifacts contain no qualification receipt or evidence of a release. This is not a global native-state audit.

End this one-shot window in the recorded provider-limited hold; no repeat request or bypass is warranted by this result. Keep the separate accepted disposable worker/host proofs and preserved original Jetson choice, without promoting them to live acceptance. This QA made no provider or other external call, read no native database/service, changed no source/shared evidence, and encountered no display/tool transport issue.
