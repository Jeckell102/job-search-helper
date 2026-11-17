# Host-backed Wrapper Coder development

The Jetson runs the AI model. All wrapper source, edits, tests, scratch files, and local Git history belong in `dev/wrapper-coder/` inside the active Job Search Helper folder on the scraper computer. `repo/` is the source-only development checkout, `runs/` holds temporary test work, and `tools/` contains the host backend. The complete prior Jetson development workspace and setup records are preserved in a local migration archive.

An authenticated HTTP backend binds only to host loopback. An SSH reverse connection exposes it only on Jetson loopback. The Jetson client forwards the seven existing scoped development tools; it has no local file-operation fallback. If the scraper computer or connection is unavailable, the tools fail clearly. The backend and connection use user services and reconnect while the user service manager is running. The AI model/runtime remains installed on the Jetson.

Run coding tasks in a new Wrapper Coder chat. Use relative `src/`, `tests/`, and `docs/` paths. Writes and tests happen on the scraper computer. Tests remain offline and resource limited with Landlock/seccomp. The test launcher explicitly selects the development configuration so pytest does not search the production parent folder. The active scraper virtual environment is read-only to tests; runtime data and credentials remain outside their allowed paths.

Completed integrations still require validated installation from the development checkout into the active scraper's `src/job_search_helper/`, including dispatcher registration, tests, fixtures, and notes. Back up changed source to GitHub. A local development commit is not production installation. Do not restart a scraper or change live data merely to save development work.

Runtime service examples are provided as templates: replace the active checkout and SSH alias. Generate a random bridge token locally, store it with owner-only permissions in the host `bridge-token` and Jetson `config/wrapper-host.json`, and never commit it. Replace the Jetson coding_tools module with coding_tools_client.py; preserve its existing profile/runtime integration. Update its system instructions and /tools help to describe host-only storage. The default bridge port is 18789 on loopback only.

Rollback must preserve work in the host development checkout. Stop the host bridge services and restore matching backed-up Jetson runtime modules only if intentionally returning to the old design; do not silently restore local Jetson development storage. The default behavior when disconnected is to stop coding actions.

## Verified migration checks

Seven guarded-tool regression tests passed; 46 Bosch wrapper tests passed on the scraper computer; four host-location/isolation checks passed through both the Jetson forwarding client and a real model chat. Unauthorized HTTP access, path escape, write-scope denial and disconnected-write behavior were checked. The migration archive is kept locally, never published.

## Required development and test procedure

Copy `wrapper-development-test-protocol.md` into the development checkout's `docs/` directory. Install this directory's `coding_runtime.py` as the Jetson runtime module, in addition to the existing host-forwarding coding_tools client. The runtime loads the full protocol from the host before each coding turn, includes it in the model instructions, and reports the verified read. Missing, truncated or incorrect protocol content stops the turn before inference or coding actions. The host backend prevents model edits to the protocol.

The procedure requires baseline tests, verified public source evidence, focused repairs, nonempty normal-dispatch tests, negative cases, separate live read-only scraper validation with a receipt, and verified installation/GitHub delivery. Offline code_test calls cannot execute live network scraping; until the operator performs that check, the model must report it as outstanding. The actual entry point fetch_inventory includes source repair and provider dispatch. A passed direct-wrapper test or HTTP 200 alone does not establish a working live integration.

Twelve installed protocol/tool tests passed. The automated tests verify per-turn loading, preservation of conversation history, stopping on absent/truncated/wrong instructions, and prevention of model edits to the procedure. Model adherence to every substantive step still requires reviewing the recorded evidence; automatic loading does not make the model infallible.

## Work offloaded to the scraper computer

For Wrapper Coder, public web searches, raw page reads, and bounded JavaScript-rendered page reads now execute on the scraper host alongside source reads/edits, Git operations and offline tests. The Jetson retains AI inference and lightweight chat/tool coordination. Install public_web.py, public_web_types.py, rendered_web.py and public_tools.py with the host backend, and update the host_server and Jetson forwarding client/runtime. The rendered reader uses a fresh browser context, permits public GET navigation and same-site script/API reads, blocks writes, downloads, service workers, private destinations, third-party subresources and unneeded media, and returns bounded visible text and links. There is no web-execution fallback on the Jetson. Other chat profiles are unchanged.

The rendered-reader policy and host-dispatch suite has 10 passing tests. An active bridge request rendered the Scythe Robotics Dover page on the scraper computer and captured its explicit visible "No positions available at this time" state. This is public source evidence, not the required live fetch_inventory validation. Keep the scraper computer awake and its host/tunnel user services running for coding work.

The Wrapper Coder runtime permits twelve tool turns and records up to twenty actions in one request. Reaching that bound returns a continuation handoff with verified actions instead of raising `coding_tool_round_limit_exceeded`.
