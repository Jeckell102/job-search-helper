# Security Reporting

This is an alpha project. Security fixes target the current `main` branch;
there are no separately maintained older release branches. Review updates and
back up your catalog before upgrading. No response or remediation time is guaranteed.

## Report Sensitive Problems Privately

Do not post credentials, personal job-search records, or exploit details in a
public issue or pull request.

If GitHub shows **Report a vulnerability** in this repository's Security tab,
use that private reporting channel. If it is unavailable, open an issue titled
"Private security contact requested" with no technical details or sensitive
attachments, and ask the maintainer to arrange a private channel. Do not send
the details until a private channel has been established.

Once a channel is available, include the affected version, impact, and a minimal
reproduction using invented records. Share only the data needed to reproduce the
problem. Remove exposed credentials from use and replace them at their provider;
deleting a posted file does not invalidate a credential.

Ordinary bugs without sensitive implications belong in the
[bug tracker](https://github.com/Jeckell102/job-search-helper/issues/new/choose).

## Local Data

Catalogs, backups, and exports can contain personal notes and application history.
The application does not add database encryption. Protect the workspace using
your operating system's access controls and storage protections. The repository's
ignore rules help prevent accidental commits but do not inspect arbitrary files
or remove information already shared.
