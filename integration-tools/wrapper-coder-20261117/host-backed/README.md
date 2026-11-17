# Host-backed Wrapper Coder development

The Jetson runs the AI model. All wrapper source, edits, tests, scratch files, and local Git history belong in `dev/wrapper-coder/` inside the active Job Search Helper folder on the scraper computer. `repo/` is the source-only development checkout, `runs/` holds temporary test work, and `tools/` contains the host backend. The complete prior Jetson development workspace and setup records are preserved in a local migration archive.

An authenticated HTTP backend binds only to host loopback. An SSH reverse connection exposes it only on Jetson loopback. The Jetson client forwards the seven existing scoped development tools; it has no local file-operation fallback. If the scraper computer or connection is unavailable, the tools fail clearly. The backend and connection use user services and reconnect while the user service manager is running. The AI model/runtime remains installed on the Jetson.

Run coding tasks in a new Wrapper Coder chat. Use relative `src/`, `tests/`, and `docs/` paths. Writes and tests happen on the scraper computer. Tests remain offline and resource limited with Landlock/seccomp. The test launcher explicitly selects the development configuration so pytest does not search the production parent folder. The active scraper virtual environment is read-only to tests; runtime data and credentials remain outside their allowed paths.

Completed integrations still require validated installation from the development checkout into the active scraper's `src/job_search_helper/`, including dispatcher registration, tests, fixtures, and notes. Back up changed source to GitHub. A local development commit is not production installation. Do not restart a scraper or change live data merely to save development work.

Runtime service examples are provided as templates: replace the active checkout and SSH alias. Generate a random bridge token locally, store it with owner-only permissions in the host `bridge-token` and Jetson `config/wrapper-host.json`, and never commit it. Replace the Jetson coding_tools module with coding_tools_client.py; preserve its existing profile/runtime integration. Update its system instructions and /tools help to describe host-only storage. The default bridge port is 18789 on loopback only.

Rollback must preserve work in the host development checkout. Stop the host bridge services and restore matching backed-up Jetson runtime modules only if intentionally returning to the old design; do not silently restore local Jetson development storage. The default behavior when disconnected is to stop coding actions.

## Verified migration checks

Seven guarded-tool regression tests passed; 46 Bosch wrapper tests passed on the scraper computer; four host-location/isolation checks passed through both the Jetson forwarding client and a real model chat. Unauthorized HTTP access, path escape, write-scope denial and disconnected-write behavior were checked. The migration archive is kept locally, never published.
