# Automatic Google authorization recovery

This update fixes the startup failure where a valid read-only credential passed
preflight, but an expired write refresh token stopped `start` with `RefreshError`.

## Install

Save `scraper-auth-update.tar.gz` in `~/Downloads`. If the scraper is currently
running, stop it with Ctrl+C, then run:

```bash
cd ~/job-search-helper_old
tar -xzf ~/Downloads/scraper-auth-update.tar.gz
./job-search-scraper start --fetch-workers 5
```

The archive overlays only these files:

- `src/job_search_helper/repository.py`
- `src/job_search_helper/cli.py`
- `src/job_search_helper/runner.py`
- `tests/test_auth_recovery.py`
- `AUTH-RECOVERY-UPDATE.md`

It contains no credentials, tokens, environment settings, databases, or title
lists. The existing `.env`, `.secrets`, `.state`, other source modules, and
existing tests are preserved. The scraper resumes its saved cycle normally.
The Google dependencies already used by the scraper are sufficient.

## Behavior

`start` and `sync` validate both Google credentials at startup and before each
Google HTTP request. When either access token expires, both are refreshed and
saved automatically. A valid refresh token renews access without a browser.

If Google reports an expired/revoked refresh grant (`invalid_grant`) or an invalid
scope, the affected credential opens Google sign-in automatically. Complete the
authorization to continue. Each token keeps its own scope and file:

| Credential | Scope | Default file |
| --- | --- | --- |
| Read-only | `https://www.googleapis.com/auth/spreadsheets.readonly` | `.secrets/token-readonly.json` |
| Write | `https://www.googleapis.com/auth/spreadsheets` | `.secrets/token-write.json` |

Both grants may require separate browser authorizations if both need consent.
Google still requires a person to approve a new grant; software cannot silently
replace revoked consent. New grants explicitly request offline access and
consent so a replacement refresh token is returned.

Refreshed tokens are written atomically with private file permissions. The
same protection against shared token paths and symlinked token paths remains.
OAuth response bodies, credential contents and token values are not printed.

An authentication failure in Google's authorized HTTP transport may retry the
same request once after recovery. That failure occurs before transmission or
after an HTTP 401 rejection. Network timeouts and other ambiguous write failures
keep the existing durable recovery behavior and are not replayed automatically.

Manual commands:

```bash
./job-search-scraper auth             # Check/renew both credentials.
./job-search-scraper auth --write     # Check/renew only the write credential.
./job-search-scraper auth --read-only # Check/renew only the read credential.
```

`preflight` continues to check read access and headers without requesting write
authorization. Its `write_test: not performed` result is intentional.

## Validation

All 30 authentication regression tests passed using mocked Google libraries,
transports and credentials. They cover paired expiry, revoked grants, recovery
during a run, bounded authentication retries, permission denial, atomic token
writes, noninteractive read-only behavior, and preservation of ambiguous writes.
Syntax checks and the `auth --help` command also passed.

Run the focused tests after installation with the scraper's virtual environment:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover \
  -s tests -p 'test_auth_recovery.py' -v
```

The uploaded source did not include the existing test suite or configuration
files. No live Google account authorization or spreadsheet write was performed
in the test environment.

The broader offline demo has a pre-existing `IndexError` in `engine.run_demo`
when it indexes `state.reviews(cycle, "pending")[0]`. The same failure was
reproduced in the original uploaded source with isolated title-list fixtures.
This update does not modify that module or its demo.
