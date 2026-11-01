# Hallam-ICS checkpoint — 2026-11-01

- Company: Hallam-ICS (`COMP-0397`)
- Official careers page: <https://www.hallam-ics.com/careers>
- Official ATS source: the company-specific UKG Pro Workforce Ready/SaaShr portal at `https://secure7.saashr.com/ta/6211585.careers?CareersSearch=&career_portal_id=4915719&ein_id=118982210&lang=en-US`.
- Installed code now routes this exact company to a guarded SaaShr adapter. The adapter requires tenant-scoped posting links, complete public descriptions, and a stable second inventory read.
- Focused tests: 2 passed.
- Installed normal pipeline reread 1: failed before board discovery with `Careers page network/timeout failure; board discovery did not complete.`
- Installed normal pipeline reread 2: same failure.
- Terminal blocker: this environment could not resolve/connect to `secure7.saashr.com`; no live inventory was established.
- **Do not count complete.** No completion ledger was modified.
