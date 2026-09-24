# v3.2 Efficiency Update

This update preserves the direct-Google-Sheets architecture and changes how work is routed and read.

## Efficiency changes

- Python rejects obvious non-target titles for $0.
- Python sends obvious target-function titles directly to full review, skipping Luna.
- Luna sees only genuinely ambiguous job titles and receives the title only.
- Python rejects an unambiguous annual USD base maximum below $120,000 before Sol.
- Sol receives a cleaned job description with obvious trailing EEO/privacy/agency boilerplate removed.
- First reviews do not send previous review notes or historical descriptions.
- Reassessments send prior posting context only when a previously reviewed job actually changed.
- Historical evaluation records retain hashes/decision/narrative rather than repeated full posting copies.
- AI queue scans read only `Job Key`, `Review Status`, and `Review Started At`.
- A selected job then reads one Job History row rather than the whole tab.
- Scan-cycle completion checks read only `Cycle ID` and `Cycle Status`.
- Company and Opportunity lookups in the reviewer use narrow columns/rows where possible.
- Schema validation reads header rows rather than downloading every operational tab.
- Absence reconciliation reads only the Job History columns it needs.

## Install

From your home directory after downloading the archive:

```bash
rm -rf /tmp/job-search-update
mkdir -p /tmp/job-search-update

tar -xzf ~/Downloads/job-search-helper-v3.2-efficient.tar.gz \
  -C /tmp/job-search-update

/tmp/job-search-update/install-v3.2.sh ~/job-search-helper
```

Then:

```bash
cd ~/job-search-helper
./job-search-reviewer start
```

The installer does not replace `.env`, `.state`, `.secrets`, `credentials.json`, or `.venv`.
