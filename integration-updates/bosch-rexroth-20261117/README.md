# Bosch Rexroth U.S. integration

Bosch Rexroth (COMP-0571) now routes through a company-specific wrapper before generic SmartRecruiters discovery. The previous route downloaded roughly 5,055 worldwide Bosch postings and attributed the shared parent board to Rexroth.

The wrapper paginates the public BoschGroup API with `country=us`, validates every U.S. listing card, and selects the exact provider Legal Entity `Bosch Rexroth Corporation` before fetching descriptions. It includes that entity's Rexroth, Bosch Group, and Hägglunds brands. Other legal entities, including HydraForce, remain outside this corporate-entity scope. It does not claim worldwide coverage.

- Accepts only the verified Rexroth U.S. careers pages or legacy BoschGroup board URLs for the exact company identity. Changed sources fail closed.
- Rechecks all U.S. listing pages, counts, unique IDs, and selected records before declaring completion. Only changes to selected Rexroth records require detail reconciliation.
- Validates detail company, legal entity, country, title, posting ID, public URL, active state, requisition, and full description. HTTP failures, malformed cards, missing entity metadata, blocked access, or persistent changes remain incomplete.
- Reuses unchanged descriptions through a separate scope checkpoint and code-derived policy fingerprint. Existing cooperative workers share the normal host pacing and retry limits.
- A narrow alternate-section rule handles public legal notices whose duties are stored under `companyDescription`. It requires substantive text matching the employer, exact title, requisition, hiring language and qualifications marker; generic company boilerplate is rejected.
- Generic browser fallback is disabled so a failed scoped scan cannot silently expand to all Bosch jobs.
- The returned inventory source is the Rexroth U.S. job-opportunities page, distinct from the former BoschGroup source. Existing closure logic therefore does not compare the old parent inventory against this narrowed scope. Existing job keys remain SmartRecruiters + posting ID.

Validation on November 17, 2026: the live parent API had 5,067 worldwide postings; the U.S. feed had 355, of which 70 belonged to Bosch Rexroth Corporation. Of those 70, 62 carried the Rexroth brand, four Bosch Group and four Hägglunds. One Controls Systems Engineer posting used the alternate description layout.

Installation changes scraper code and regression tests only. It does not rewrite historical jobs, manual decisions, Opportunities, or live Sheet data, and does not restart an existing scraper process. A process started before installation retains its imported code; the wrapper is used by a new process when it next fetches this company's inventory. Resuming a cycle can reuse an already saved old inventory, so a fresh company fetch is needed to replace that older inventory.

Sources:

- https://www.boschrexroth.com/en/us/jobs-and-career/job-opportunities/
- https://developers.smartrecruiters.com/docs/endpoints
- https://api.smartrecruiters.com/v1/companies/BoschGroup/postings?limit=100&offset=0&country=us

## Update package

This is a backup of the change to the installed job-search runtime. GitHub main has a different code baseline, so this package deliberately does not replace its application modules. `runtime.patch` contains all six changed/new files against the installed November 17 baseline; `baseline-hashes.json` records its exact preconditions. The standalone wrapper and tests are also included under `files/`. Apply the patch only to that matching runtime after checking the baseline; do not apply it blindly to main.

Validation: 177 regression tests passed; live validation returned complete with 70 descriptions in 36.78 seconds. The installation receipt records the verified installed hashes. Existing scraper processes and saved cycle inventories are not restarted or rewritten.
