# Independent AcquireTM recipe source gate

Verdict: **ACCEPT_SOURCE_ONLY** for the bounded candidate evaluation. This is not deployment, provider validation, synchronization, or general automation acceptance. No provider or model calls were made by this reviewer; production, stage source, job data, and Sheets were not changed.

The frozen source transformation compiles to exactly the materialized candidate. The only behavior change is the readiness helper and its one inventory call: wait for a previously unseen numeric posting ID on the same origin and detail path. The normal 12,000-ms deadline is preserved. Exact board checks, listing parsing, total/overlap/count guards, page bounds, detail identity/employer/full-description checks, detail rate/retry controls, and final full listing reread are unchanged. The typed pre-repair diagnostic helper remains unchanged; its original witness and diagnostic baseline test remain separate historical evidence, not proof of repaired success.

## Pins verified

| Artifact | SHA-256 |
|---|---|
| Stage recipe | `d6465801a0932a85895441914170d11e0258e642927f2d3349e2d044dfebc377` |
| Stage recipe tests | `5c8e73667ed66ad26a7c989ab3da9dc47bc6940210164c322499a9c6dd81e6f0` |
| Stage handoff | `c97be8c3499c95c3a04f9430e752e31a2bc3e30fd3eaac225b038816ae38be25` |
| Candidate adapter | `895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d` |
| Candidate dispatcher | `111ccb9067402832ad96b798100dfca293668cf24830409874c1ab4d6eaac07e` |
| Original six-test file retained in candidate | `5bace6904b1630871477aa2b5b408a591813a834742a2bcca85c757c8dd5e908` |
| Original typed witness W1 | `d10331c3e89b63ef00a8a26af7ac4c69f66beb95167e3b2005b4d9e101cd0602` |
| Raw snapshot manifest | `acc0ba9b1fa8855dc588cc28d9911bf4ab6fa58816cba426e8ca9954437e4bdf` |

The recipe requires exact source and witness bytes, validates the witness scope/failure fields, accepts only the exact two-field selection, and returns source/diff/receipt without installing or writing files. Wrong source/witness, alternate choices, absent choice, and additional fields were rejected. Source inspection found no file or network operations in this compiler.

## Independent checks

Reproducer: `/tmp/jsh-amphenol-independent-qa-20261121/check_recipe_offline.py`, SHA-256 `2ace7a13219f48dec78a56e32b014836144be6a58b89047cd0c168a437e1e32b`.

Run with `/usr/bin/python3 -I -B /tmp/jsh-amphenol-independent-qa-20261121/check_recipe_offline.py`.

This exact-pin check independently rebuilds the candidate, compares all non-readiness function/class ASTs, verifies all raw snapshot hashes, extracts and calls the actual candidate Python readiness helper, and executes its actual emitted JavaScript in Node's VM against inert anchors parsed from the captured HTML. It does not replace the expression with a modeled predicate. Results:

- Old 25-ID page: false; premature same-membership page: false; late 14-ID page: true.
- Foreign origin, foreign detail path, and nonnumeric ID: false.
- Actual callback arguments contain the exact 25 known IDs and exact detail path; deadline is 12,000 ms.
- Callback timeout raises `FetchError('partial', ...)`.
- Rebuilt bytes match candidate; guards unchanged; five invalid compiler inputs rejected.

The recipe's three offline tests also passed independently (`Ran 3 tests in 0.109s`, no bytecode/cache writes). They exercise inventory with synthetic/raw fixtures but stub the browser wait. Therefore those tests alone do not prove JavaScript execution; the separate actual-expression check above supplies that evidence. The release owner separately reported an actual Chromium offline check of the same callback. Original baseline and related-suite execution is the release owner's separate evidence (reported 16 passed), not relabeled as this reviewer's execution.

## Next gate

Prepared evaluator: `/tmp/jsh-amphenol-independent-qa-20261121/evaluate_recipe_candidate.py`, SHA-256 `692cf7db590f53524bfa1fc08d298c7f1bb842b682596eef799a851e85ed42ad`.

It requires exact root `/tmp/jsh-s5-amphenol-recipe-live-candidate` and pins the full 243-file source/config manifest digest `48f80b004f69fe4015f711e7f235176ffb69742162010091e017d21143dd1cae` before imports, plus the adapter/dispatcher pins. Its two sequential fresh normal-dispatch scans independently observe complete page membership, exact detail identity/employer/full descriptions, final listing reread, and stable cohort. Source pins are checked again after each run. It performs public reads only and has no database, release, or synchronization operation. The evaluator was prepared and syntax-checked here, not invoked here.

The release owner will run one bounded evaluation and supply its private capture for separate independent judgment. A successful source gate does not authorize broad processing, automatic release, or a claim that arbitrary wrappers can be generated. This experiment is a structured AI recipe selection followed by a host-authored fixed transformation.
