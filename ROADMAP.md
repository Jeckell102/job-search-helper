# Roadmap And Starter Tasks

Job Search Helper aims to make a personal job catalog reliable, understandable,
and easy to extend. This roadmap is a set of contribution directions, not a
promise that each feature will ship. Propose other ideas when you have a concrete
workflow they would improve.

## Available Today

The current release includes a local SQLite catalog, public job-board adapters,
recoverable scans, company import, application history, optional rule-based
screening, readable CSV exports, and verified backups. See the
[user guide](docs/user-guide.md) for supported commands.

## Starter Tasks

These are suggestions, not claims that someone is assigned or already working
on them. Check [open issues](https://github.com/Jeckell102/job-search-helper/issues)
and coordinate there before starting overlapping work.

| Task | Where to start | A useful finished contribution |
| --- | --- | --- |
| Improve first-run troubleshooting | `README.md`, `SUPPORT.md` | Reproduce a setup problem on a clean Linux environment and document the fix with the Python and OS versions used. |
| Explain one complete application workflow | `docs/user-guide.md`, `tests/test_catalog_commands.py` | Add a worked example with fictional records covering list, show, update, and the row-version check; verify every command. |
| Cover a missing date edge case | `dates.py`, `tests/test_source_dates.py` | Find a case absent from existing tests, use invented input, and preserve the distinction between date-only, zoned, and ambiguous values. |
| Strengthen an adapter failure test | `tests/test_ats.py`, `tests/fixtures/` | Add a synthetic malformed or interrupted response absent from current coverage; verify it cannot be mistaken for a complete empty board. |

Module names above live under `src/job_search_helper/`. Small documentation PRs
are welcome even when they do not match this list.

## Next Priorities

- **Provider reliability:** clearer diagnostics, more synthetic coverage for
  pagination and employer scope, and fixes for confirmed provider changes.
- **Everyday usability:** actionable command errors, easier catalog review, and
  clearer import and recovery instructions.
- **Contributor experience:** reproducible setup, understandable module boundaries,
  and easier ways to test new adapters without network access.

## Larger Ideas To Discuss

- Additional public job-board adapters with explicit scope and completeness rules.
- A local graphical interface over the catalog and application workflow.
- Broader platform support. File locking and atomic export publication currently
  rely on platform-specific behavior; changing the install instructions alone
  would not establish Windows or macOS support.
- Optional integrations that keep personal data under the user's control and
  preserve a usable local core.

For one of these, open a feature proposal with a user scenario, a small first
milestone, expected data changes, and a verification plan. A proposal should also
explain whether it adds runtime dependencies or sends data to another service.

## Design Commitments

Keep fetched evidence separate from interpretation. Preserve application history.
Represent incomplete or unknown information honestly. Make previews, backups,
and recovery part of workflows that change user data. Keep dates readable in
normal output and retain machine-readable timestamps internally.

Start with [CONTRIBUTING.md](CONTRIBUTING.md) when you are ready to work on an idea.
