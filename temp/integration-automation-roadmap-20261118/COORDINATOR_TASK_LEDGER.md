# Integration automation task ledger

Updated 2026-11-18.

## Current checkpoint

- Coordinator goal: `01a1f124-9793-7e53-9d37-92f11052c967`, active; started 2026-11-18.
- Current focus: Milestone 1 guarded operational acceptance for the company-only scrape-to-storage path, with an offline-accepted Milestone 2/F1 event-to-request bridge.
- Main checkout protection: `/home/chris/job-search-helper_old` has 1,825 pre-existing changed/untracked paths on branch `repair/annapolis-static-careers-2026-11-01`; it is not being edited.  Development occurs in clean isolated worktree `/tmp/job-search-helper-integration-automation`, branch `codex/integration-automation-20261118` at `debfa37`.
- Fresh live-state observation: no active scraper/coordinator process was found.  Existing `.state/scraper.lock` and `.state/writer.lock` name PID `485601`, which was not live at observation; locks are retained pending the documented recovery path.  Coordinator and deployment locks were also retained.

## Worker assignments

| Worker | Lane | Scope | Acceptance target | Status |
| --- | --- | --- | --- | --- |
| `scrape_intake` | Scraping/intake | M1 scoped scheduling/execution, focused tests | Target-only cycle; reject unsafe selection; no full-scan fallback | Implemented; guarded operational evidence pending |
| `repair_release` | Coordinator/repair/release | F6/F7 data contract and current coordinator integration points | Receipt identities/states and safe recovery requirements | Implemented; guarded operational evidence pending |
| `m2_bridge` | Intake/storage | M2/F1 Company event outbox to normal scoped-intake bridge | No lost update/cancellation race; idempotent recovery; one scoped cycle | Implemented; independent offline QA accepted |
| `independent_qa` | Independent QA | Baseline and M1/F1-F8 acceptance matrix | Evidence-backed readiness report; no self-certification | Ongoing; M2 bridge repair accepted |

## Open findings and next action

F1-F5 and F8 remain OPEN; F6/F7 are IMPLEMENTED_AWAITING_QA. Commit `debfa37` has 108 passing focused Python 3.11 checks and independent offline QA: Company changes are transactionally recorded, the newest revision is selected before paging, bridge writes and normal intake share one lock, and an actual local run creates one scoped cycle. The next gate remains guarded real M1 evidence: safe main-checkout reconciliation, scoped idle/busy timing, confirmed synchronization, and lost-ack recovery without refetching. F1 also still needs external-change reconciliation and bootstrap/watermark proof.
