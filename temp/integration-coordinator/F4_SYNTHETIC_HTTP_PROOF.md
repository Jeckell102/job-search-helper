# F4 deployed synthetic HTTP proof

Status: isolated staging candidate only. Do not run or deploy before independent
review.

The proof script must use the deployed, authenticated `/api/wrapper-turn`
request path with a synthetic prompt and a fresh ownership binding. It must
not import, seed, or mutate the inference receipt store directly.

The operator authenticates `sudo` before the request begins. The script then:

1. submits one synthetic controlled HTTP request in a client thread;
2. observes `RUNNING` only through the owner-bound status endpoint;
3. restarts only `ollama.service`, causing a real in-flight backend transport
   failure;
4. proves the HTTP request did not return a successful result and the deployed
   receipt became `UNCERTAIN`;
5. records the post-failure Ollama generation through the owner-bound recovery
   endpoint while retaining the lane hold;
6. restarts only Ollama again, proves a distinct third generation is active
   and both earlier PIDs are absent, then requests settlement; and
7. writes only bounded service-generation and receipt-status evidence.

The endpoint is resolved at runtime from the Jetson's local settings file; no
host address is stored in GitHub-backed source. The generation sampled before
the request is only a pre-request observation, not an assertion about the
receipt's authoritative admission generation. The deployed receipt and
recovery checks remain authoritative for settlement.

Any timeout, successful first response, mismatched generation, lingering PID,
authentication failure, or recovery error stops the script. After an ambiguous
request has begun, failure must leave its `UNCERTAIN` receipt lane-blocking.
The script writes a mode-0600 sanitized checkpoint after the request starts,
flushes and synchronizes the temporary file, atomically replaces the evidence,
and synchronizes its parent directory. A bounded failure record is attempted
on any later error. If checkpoint persistence itself fails, the script makes
no recovery call and leaves the deployed receipt as the authoritative hold;
it never trades missing evidence for lane release.

Immediately before settlement, the script durably records
`settlement_authorized` with `lane_released: false`; a failure writing that
checkpoint prevents the settle call. After the server accepts settlement, its
terminal receipt is authoritative. If writing the final `complete` evidence
then fails, the script records that post-settlement boundary when storage is
available; it does not falsely claim that the already accepted settlement can
be reversed.
No Job Search task, company, prompt, credential, model output, or request ID is
written to the evidence file.
