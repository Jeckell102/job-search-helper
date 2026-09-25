# Getting Help

Start with the [quick start](README.md#get-started) and
[user guide](docs/user-guide.md). Each command also accepts `--help`.

For a question, bug, or feature idea, use the appropriate
[issue template](https://github.com/Jeckell102/job-search-helper/issues/new/choose).
Search existing issues first. Include your operating system, Python version,
`job-search-helper --version`, the command, and what you expected to happen.
Replace personal paths and records with invented examples before posting output.

## Common Starting Points

| Symptom | What to check |
| --- | --- |
| Command not found | Activate the environment with `source .venv/bin/activate` from the checkout, then confirm installation succeeded. |
| Python cannot create a virtual environment | Install your Linux distribution's Python venv support, then repeat the setup step. |
| The catalog is empty | New catalogs start empty. Replace the placeholder company URL, apply the import, then scan a supported board. |
| An input CSV cannot be found | Relative input paths resolve inside `--workspace`, not inside the repository. |
| A source is unsupported or blocked | Verify the exact public employer board URL and inspect scan status. General careers pages may be unsupported; do not bypass an access restriction. |
| An interrupted scan remains unfinished | Follow the user guide's scan recovery steps; use the recorded cycle ID. |
| An application edit reports a stale version | Show the application again and use its current row version after reviewing the intervening changes. |

Keep personal databases, exports, resumes, notes, and credentials out of issues.
For sensitive problems, follow [SECURITY.md](SECURITY.md). Community help is
best-effort; there is no guaranteed response time or commercial support service.
