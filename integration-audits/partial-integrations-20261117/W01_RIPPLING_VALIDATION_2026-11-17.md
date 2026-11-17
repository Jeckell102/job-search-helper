# W01 Rippling query-key validation — 17 November 2026

This record covers the shared parser repair, not a scraper-cycle or Google Sheets publication.

## Implementation

`src/job_search_helper/shared_boards.py` now validates an unfiltered Rippling `queryKey` explicitly. It accepts both verified layouts:

1. `['board', slug, 'job-posts', <boolean>, filters]`
2. `['board', slug, 'job-posts', <boolean>, filters, 'en-US']`

The filters must exactly describe an unfiltered 20-item page for the expected page number. The boolean must actually be a boolean; current public boards use both `true` and `false`. Any malformed or ambiguous layout, non-`en-US` locale, or nonempty search/location/department filter remains partial.

## Local regression checks

Command:

```text
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' PYTHONPATH=src /home/chris/job-search-helper_old/.venv/bin/python -m pytest -q tests/test_shared_boards.py tests/test_rippling_locations.py
```

Result: `20 passed in 0.13s`.

Coverage added in `tests/test_shared_boards.py`: current trailing-locale schema, both boolean variants, malformed/missing/ambiguous query keys, filtered query rejection, wrong board identity, and 21-posting two-page pagination.

## Read-only live normal-dispatch validation

The validation used `job_search_helper.ats.fetch_inventory('Rippling', source_url, company_id, company)` with no scraper-cycle start, state write, or Sheets publication. Each `complete` result includes the adapter's final inventory reread.

| Company ID | Company | Source | Result | Full postings | Final reread |
|---|---|---|---|---:|---|
| COMP-0066 | Forterra | `ats.rippling.com/forterra/jobs` | complete | 50 | stable |
| COMP-0110 | goTenna | `ats.rippling.com/gotenna/jobs` | partial | 0 | not reached: HTTP 404 |
| COMP-0178 | Performance Drone Works | `ats.rippling.com/pdwcareers/jobs` | complete | 39 | stable |
| COMP-0188 | DroneUp | `ats.rippling.com/droneup/jobs` | complete | 0 | stable explicit empty inventory |
| COMP-0237 | Bonsai Robotics | `ats.rippling.com/bonsairoboticsmain/jobs` | complete | 7 | stable |
| COMP-0260 | Advanced Navigation | `ats.rippling.com/advanced-navigation/jobs` | complete | 22 | stable |
| COMP-0288 | ADLINK Technology | `ats.rippling.com/ampro-adlink-technology-inc/jobs` | complete | 10 | stable |
| COMP-0320 | Foundation | `ats.rippling.com/foundation-robotics/jobs` | complete | 26 | stable |
| COMP-0349 | Blue Robotics | `ats.rippling.com/blue-robotics/jobs` | complete | 1 | stable |
| COMP-0350 | Kraken Robotics | `ats.rippling.com/kraken-robotics-inc/jobs` | complete | 22 | stable |
| COMP-0483 | Cyngn | `ats.rippling.com/cyngn/jobs` | complete | 19 | stable |
| COMP-0495 | Overland AI | `ats.rippling.com/overland-ai/jobs` | complete | 46 | stable |
| COMP-0539 | Mytra | `ats.rippling.com/mytra/jobs` | complete | 40 | stable |

Twelve current boards completed normally with 282 total full postings. goTenna is not a parser failure: its recorded employer board currently returns HTTP 404, so it remains partial until a verified public source is established. No company status was manually promoted; installation into a future scraper run and Sheet publication remain separate follow-up work.
