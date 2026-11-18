# Samtec evidence-selection recipe pilot

This is a staged, host-written Python recipe, not an autonomously AI-written wrapper. Jetson selected the four evidence IDs in `selection.json`. The earlier accepted route change remains AI-authored. Transport and listing implementation are host-written and constrained to the pinned Samtec Jobvite board.

`recipe.build(source_bytes, selection)` verifies the exact approved input hash and unique source anchors, verifies the static helper hash, and returns content, a unified patch, and a provenance receipt. It never installs or writes the input. `read_selection` accepts exactly four known evidence IDs, rejecting duplicate keys, extra fields, wrong types, and unsupported choices. The recipe contains the company, host, and path binding; model input cannot supply code or URLs.

`acceptance_repo` is an isolated generated preview. `build-receipt.json` binds the actual Jetson selection response by path and SHA256. `proposed.patch` shows only the Samtec transport exception, helper, and dispatch. Existing route, detail extraction, identity checks, all-page reread/reconciliation, and other-provider implementation remain unchanged.

Transport permits only the Samtec search path, optional trailing slash, and a single ASCII `p` integer or no query. Traversal is stricter: only an observed next link to the consecutive canonical page is followed. It validates actual class-scoped job anchors, displayed contiguous ranges and dynamic total, unique scoped IDs and titles, terminal-page consistency, and a twenty-page bound. Missing, ambiguous, malformed, duplicate, filtered, or out-of-scope evidence fails closed. Zero needs a consistent displayed zero range plus explicit visible empty text.

Local checks: 3 recipe unit tests, 19 independent normal-dispatch pagination tests, and 16 existing shared-provider tests pass. Offline replay of the three saved public HTML pages matches all 148 observed IDs exactly. This is not live detail/download validation or an installation certification. Independent QA and a fresh normal-dispatch run remain separate gates.
