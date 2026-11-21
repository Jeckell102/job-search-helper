# Sprint 6 independent intake scrape control

`./job-search-scraper storage intake-scrape-disable` pauses future
supervised Company scrape launches while leaving intake enabled and
preserving queued requests. `intake-scrape-enable` allows future launches
through the existing intake and scope gates. The separate `intake-status`
output reports the effective `scrape_enabled` setting. Existing journals
without the new setting continue to follow the existing intake switch.
The commands run through the existing local storage entry point.

The pause is checked in the dispatch journal's existing transaction when
new ordinary, temporary and retained work claims a launch. This keeps
readback and settlement accessible for already owned work. The staged
pilot retained exact queue bytes while disabled, then admitted one request
after enable. Disabling again left the existing publication handoff
visible. This implementation has not been installed in production.

Fifty focused and adjacent tests passed with SQLite configured. Independent
QA ran the real shell with only the dispatch journal open and a guard
against the Jobs database, workbook factory and network. Both independent
checks passed, including durable temporary and retained claim checks.
[Independent test and source pins](S6_INTAKE_SCRAPE_CONTROL_INDEPENDENT_QA_20261121.md).
