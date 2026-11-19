# Davidson legacy-plan read-only preview

Run: 2026-11-19

## Scope

- Exact cycle: `CYC-B639C6D864EC`
- Company: `COMP-0035` (Davidson Technologies)
- Plan: one retained legacy plan, local cursor 19 of 19 operations
- Allowed action: selected-row and Company-control reads only

The preview tool has no commit, receipt, cleanup, inventory, queue, scrape,
or local-state mutation path. It shared the existing writer exclusion boundary
and used the project virtual environment for Google read access.

## Result

`REMOTE_PROFILE_INCOMPATIBLE` (read-only hold).

The current remote `Companies` profile does not contain the legacy plan's
required control columns: `Active Cycle ID`, `Claim Expires At`, `Claim Token`,
`Claimed By`, `Coverage Status`, `Last Inventory Count`, `Last Successful
Scan`, `Record Updated`, and `Scan State`.

Consequently remote equality cannot be proved. The local cursor is not
evidence of Google publication, and the plan must not be replayed, confirmed,
acknowledged, cleaned up, migrated, or used to advance the broad cycle.

The preview returned `mutation_performed: false`, empty chunks, no control
digest, and no possible-write upper bound. No scrape, Google write, receipt,
queue action, database mutation, lock deletion, service action, or Jetson
action occurred.

## Follow-up

Retain Davidson and the broad cycle as an explicit legacy-profile hold. Any
future migration needs a separately reviewed design that maps only verified
legacy identities into the current compact profile and does not reinterpret
the local cursor as remote delivery evidence.
