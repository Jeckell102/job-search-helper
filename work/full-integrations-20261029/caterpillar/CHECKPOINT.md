# Caterpillar checkpoint — 2026-11-01

Terminal outcome: blocked; not counted complete.

- Company: Caterpillar (`COMP-0238`)
- Official source: `https://careers.caterpillar.com/en/`
- Source type: Caterpillar's employer-owned custom HTML/XML careers portal
- Adapter/routing: `src/job_search_helper/caterpillar.py` plus `COMP-0238` dispatch in `ats.py`
- Focused validation: 2 assertions passed via direct Python invocation
- Installed normal rereads: 2/2 failed before discovery because terminal DNS/network access was unavailable; the browser fallback also reported missing Playwright
- Stable installed job count: not established
- Counted complete: no

The adapter remains fail-closed and will need two successful installed rereads after live access and browser support are restored.
