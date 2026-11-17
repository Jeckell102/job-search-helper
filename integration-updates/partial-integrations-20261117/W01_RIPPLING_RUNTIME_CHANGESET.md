# W01 Rippling runtime change set — 17 November 2026

This is a source-level backup for the live runtime at `/home/chris/job-search-helper_old`. The repository backup branch has a different application layout, so this file preserves the exact W01 implementation intent and verification rather than pretending it can be applied to that older source tree unchanged.

## Runtime production change

File: `src/job_search_helper/shared_boards.py`

Add `_rippling_filters(query_key, slug, page)` immediately before `listing`. It must:

- accept only five- or six-item query keys;
- require `['board', slug, 'job-posts']` as the prefix;
- require the fourth item to be a real boolean, accepting both `true` and `false`;
- require the fifth item to exactly equal the unfiltered page object:
  ```python
  {
      'searchQuery': '',
      'departments': [],
      'workplaceType': None,
      'country': '',
      'state': '',
      'city': '',
      'page': page,
      'pageSize': 20,
  }
  ```
- permit no sixth item, or exactly `'en-US'`; and
- raise `FetchError('partial', ...)` for changed shape, filters, locale, or identity.

In the Rippling listing branch, replace:

```python
key = qs[0]['queryKey'][-1]
# validation calls key.get(...)
```

with:

```python
key = qs[0]['queryKey']
_rippling_filters(key, b.slug, page)
# validate only listing pagination metadata here
```

This avoids treating a trailing locale string as a dictionary while retaining the unfiltered-scope and pagination checks.

## Runtime test change

File: `tests/test_shared_boards.py`

Add regression coverage that runs the normal shared-board dispatch with a trailing `'en-US'` key, accepts a `false` boolean variant, rejects missing/ambiguous/filtering/nonboolean/wrong-locale variants and a wrong board identity, and reconciles a 21-job two-page current-layout listing. Preserve existing old-layout fixture coverage and Rippling duplicate-location tests.

## Verification receipt

- Focused local regression: 20 passed.
- Live normal dispatch: 12 current Rippling boards complete with stable final rereads and 282 total full postings.
- goTenna remains partial because its recorded board returns HTTP 404 before parser execution.

See `W01_RIPPLING_VALIDATION_2026-11-17.md` and the live handoff for the full company table and commands.
