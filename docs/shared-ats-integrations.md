# Shared ATS integrations — October 8, 2026

The scraper now recognizes Rippling, Pinpoint, Breezy HR, SmartRecruiters, Workable, JazzHR, Jobvite, Dayforce, Comeet, ClearCompany (legacy and current widgets), ApplicantPro, isolved, Paycor Recruiting, Jibe, and TalentBrew. Eightfold support extends beyond the existing Northrop adapter to verified public tenant boards.

These integrations discover official employer links and embedded board configurations. They retrieve full descriptions, preserve stable posting IDs, validate pagination where applicable, and recheck listing inventories before returning `complete`. Empty feeds require provider evidence. Failed details leave the inventory partial while retaining other verified postings. Generic browser links cannot replace a recognized provider's scope or completeness result.

The browser fallback uses ordinary anonymous public pages and their read-only listing/detail requests. Dayforce's public session CSRF value is kept in memory and sent only to that tenant's job-search route. No applicant login, application submission, recruiting-account API, or sheet write is performed by these adapters.

## Source and scope limitations

- A configured individual job URL does not authorize expanding to every job on its parent board.
- Employer-linked posting subsets retain that scope; they are not silently replaced with the complete parent inventory.
- Filtered, shared, or subsidiary boards require verified company-specific scope.
- TalentBrew compares the posting's hiring organization with the configured company. Boeing's entire board is not assigned to Boeing Defense, Space & Security.
- Missing careers URLs remain a configuration task. The adapter does not guess tenant names or replace the spreadsheet's source values.
- Public denials, changing inventories, duplicate pages, malformed descriptions, and unsupported custom widgets remain partial/blocked rather than being marked complete.

## Validation and activation

The integration task records complete live results separately from bounded large-board checks and from boards tested using a proposed replacement source. L3Harris, MTSI, and CACI have bounded full-description/pagination checks; these are not claims of a complete inventory. Northrop's existing specific adapter and header/navigation exclusions remain in place.

Install changes into the active checkout without overwriting unrelated work. An already running scraper process needs a restart to load the new code. The integration task does not restart production or change spreadsheet cells.

The detailed company-by-company audit is in the task workspace's `shared-integrations/coverage-report.md` and `coverage-report.json`.
