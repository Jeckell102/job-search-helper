# F3 admission and lock contract

Candidate under source QA at `/tmp/jsh-f3-resume.ErTFRd`, 2026-11-20.

## Lock ownership

| Route | Ownership and order |
| --- | --- |
| Public start and resume | Stable bootstrap acquires scraper admission before the application imports. Controller then acquires `scrape-first-pass/controller.lock`. The scan child inherits the same open file description. Both handles close after the scan exits; controller ownership can continue through publication and review. |
| Guarded release and rollback | Acquire scraper admission, revalidate the safe version or exact journal, and hold through file installation or restoration and terminal journal write. Retry scheduling is a separate operation with a fresh admission check. |
| Selected and normal sync | Bootstrap acquires admission. Exact selected recovery uses that held boundary; normal SQLite delivery takes `writer.lock` only inside scraper admission. |
| Operational SQLite import | Acquire `scraper.lock`, then `writer.lock`, then `review-writeback.lock`. Ordinary sync watcher cycles take `writer.lock` alone and release it before intake dispatch. |
| Standalone review | Review and Sheets publication follow their existing review and writer boundaries. Neither acquires scraper admission while holding the publisher lock. |
| Direct legacy scan | A released installation requires bootstrap. A pre-release legacy path must check release journal presence while holding the same scraper lock. |

SQLite uses `scraper.lock` for admission. The Sheets backend uses `writer.lock`
for admission. Repeated acquisition of the same inode through a second handle
is invalid. Busy locks cause a hold. The application never deletes lock files
to admit a competing operation.

## Runtime evidence and recovery

- The bootstrap measures Python and JSON source, installed package files and
  configured startup and title-filter inputs under scraper admission. The
  worker validates the same lock ownership and runtime values before fetch.
- A start stores measured runtime identity in local cycle state and recovery
  notes. A resumed pinned attempt must match before starting a writer. Exact
  selected sync checks the saved pin before remote construction and at the
  durable plan boundary. Historical unpinned inventory keeps its existing
  provenance and may run the pre-release sync-only compatibility path.
- A prepared release backup and its manifest are durable before `PREPARED`
  names them. An interruption before journal publication leaves the original
  version admissible. The exact activation can adopt the verified backup on
  replay. An interruption after journal publication blocks new startup until
  exact rollback settles the journal and writes the corresponding receipt.
- Test evidence uses disposable source and state. No proof of production
  deployment or live operation follows from these fixture results.

Dependency package-tree measurement in the production environment, without
starting the application, took 0.79 and 0.84 seconds on two successive reads.
End-to-end startup latency and cold-cache cost remain unmeasured.
