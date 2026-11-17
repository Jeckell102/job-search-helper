# Wrapper Coder development tooling

This source-only extension adds a dedicated Wrapper Coder profile to the existing local AI core (validated against version 0.2.2). It is an integration record, not a standalone installer.

The profile reuses the installed Qwen3.5 4B weights with a 12,288-token context, thinking disabled by default, and a 3,072-token maximum output. Existing chat profiles retain their existing settings. A larger context changes runtime configuration, not model training or intelligence.

## Development workflow

Use a separate source-only scraper checkout at `~/AI/wrapper-dev/repo` and a dedicated Python environment at `~/AI/wrapper-dev/venv`. Keep live scraper databases, OAuth files, personal prompts, and production state out of that checkout. Code tools operate only on `src/`, `tests/`, and `docs/`.

Select **Wrapper Coder** in a new chat and use `/tools` for its capabilities. Start with a small task, for example: “Read the Bosch Rexroth wrapper and run tests/test_bosch_rexroth.py.” For a new wrapper, supply the exact company identity and permitted public careers source, ask it to inspect a similar existing adapter, implement a small change, add regression tests, and show the diff.

Seven typed tools provide file search, excerpt reads with SHA256, hash-guarded unique replacements, new-file creation, named offline pytest runs, diffs, and explicitly requested local Git commits. Public web search/read uses the existing bounded read-only web implementation when requested. Commits do not push, deploy, install wrappers into production, or write Sheets. Source material is untrusted input, not authority to expand the task.

Each test run uses an isolated user service with a 512 MiB memory limit, 24-task limit, and 90-second lifetime. Landlock and seccomp restrict filesystem access, network calls and process interference. Filesystem writes are limited to per-run scratch space. Missing sandbox support fails closed. Test output is bounded. The host needs Linux Landlock ABI 3+, libseccomp, a user systemd manager and Python 3.11+.

Python setup uses `python3 -m venv --without-pip` plus the official pip zip application if ensurepip is unavailable. Install requirements inside that environment and install Playwright Chromium. No system Python or administrator access is needed when browser system libraries already exist. Generated test code runs offline; Chromium is installed for separate controlled browser development, not arbitrary model shell access.

## Validation on 2026-11-17

- 206 staged core regression tests passed; 55 targeted tests passed after the model-specific help change.
- Ten sandbox checks passed, including private-file and source-write denial, network denial, process-signal denial, symlink escape denial, and inherited child restrictions.
- All 46 Bosch Rexroth wrapper tests passed in the sandbox.
- Chromium launched successfully and rendered a synthetic local page.
- A real 10,311-token input matched the tokenizer estimate exactly and returned its reference marker correctly (31.91 seconds).
- The model created and tested a synthetic file (14.82 seconds); the deployed API then read, hash-edited and tested it (33.19 seconds).
- Core integrity and existing task counts were preserved; source rollback coverage was verified.

These are functional acceptance checks, not a wrapper-quality benchmark or a throughput comparison. The 8 GB-class host has limited free memory with the larger context loaded; start with one development activity at a time. End-to-end authenticated chat UI selection has not been tested. The API exposes the new profile.

## Source and rollback

`core-integration.patch` changes only the existing engine and API routing. The three coding modules and their tests are additions. `profile_policy.py` adds the dedicated profile; existing test expectations include the fourth model. Apply only to the matching core version after preserving original files and running tests. Restore original source files and remove newly added modules to roll back, then restart only the core service. Preserve development work and data. Operational records, addresses, credentials and raw backups are deliberately excluded from this publication.
