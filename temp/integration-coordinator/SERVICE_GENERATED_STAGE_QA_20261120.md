# Independent QA — generated stopped-watcher stage and sandbox rehearsal

**Verdict: ACCEPT for the generated, non-installed stage and sandbox-only
rehearsal.** This does not authorize a host install, service start/enable,
intake activation, Google contact, or live scraping.

## Generated stage

The non-installed stage is
`/tmp/job-search-helper-service-stage-20261120/stage` and contains exactly:

- `20-retained.conf`, mode 0644, SHA-256
  `3b3b1c193a4768efa4ce6b59bf6224ef50bbd229c0c3e7c1d52b131227b0ae50`
- `expiry.conf`, mode 0644, SHA-256
  `a2c49ad9110950450980a23adbb1b2dc8d2319912d59590529eae36585ba40dd`
- `retained-watch.env`, mode 0600, SHA-256
  `5512506b18ba99b04bdd1c086b3f9f6d11580a5329a561cbfa851151b0996c02`

The generated verifier passed. The configured key ID is
`integration-review-20261119`; the public verifier value matches the reviewed
public-key file without reading or reproducing private material. The request
interval is 1.1 seconds. The staged expiry is
`2026-11-22T12:00:00Z`, equal to and no later than the signed authorization
expiry. The generated-verification receipt SHA-256 is
`fd29e81194122d7293f6c7fc6301cc69ed421699a7e660ce3c5718f6a8c24aa5`.

## Fresh read-only host evidence

The user service was freshly observed as inactive/dead and disabled, with
fragment path `/home/chris/.config/systemd/user/job-search-sync.service`.
Both durable intake controls were false. The current merged unit SHA-256 is
`4eebb5afea183c056453e108ce9e26cf49805b78fe908018bc24190b71729980`.
The current expiry target remains owner UID 1000, mode 0644, SHA-256
`715ecf9626dc5a91b715c40ee7ed0aecec97455df118980441586c1fde8ec884`.

## Sandbox rehearsal

The byte-bound preflight passed against a disposable mirror of that evidence.
The accepted stage installed and rolled back only inside the sandbox. The
receipt finished in `ROLLED_BACK`, the exact old expiry bytes/owner/mode were
restored, and both created targets were removed. The sandbox preflight SHA-256
is `333915a0678348c181cd26bf90dfcd6152d8ea96803e30ab790e49ae4a46e9f8`;
the rolled-back receipt SHA-256 is
`cdbbe4a22532a94b68db061372022158a983186c98ad697cc24faa2a76d344a8`.

After rehearsal, the real host create targets remained absent, the real expiry
target retained its original hash/owner/mode, and both intake controls remained
false. Independent QA accepted the evidence. No real host file, service,
Google, database, request, cycle, receipt, credential, lock, or Jetson state
was changed.

## Remaining gate

The real host installation is still a separate guarded action. The signed
historical-cycle exception also still requires the exact user acknowledgement
recorded in `LIVE_ACTIVATION_READY_20261119.md`; a one-word approval is not
accepted by that safety gate.
