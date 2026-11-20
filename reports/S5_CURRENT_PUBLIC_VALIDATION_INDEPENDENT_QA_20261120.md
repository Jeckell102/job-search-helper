# Independent QA of the Forterra and PDW public specimen

**Verdict: public specimen corroborated. Release qualification remains open.** The saved employer and provider responses support the two intended Rippling tenants. The current integrated fixture validator holds on both unmodified employer responses. All work in this review read the validation lead's saved files. The independent provider replay used local files as transport, with network and process starts denied.

The captures in `/tmp/jsh-m5-current-public-validation.NyyH0uPo` were collected November 20, 2026 around 5:38–5:42 p.m. Eastern. The lead's exact derived summary `public-observations.json` measured `00d3cfffb774fa7b162eb30656c84843edf449f0c15780d57314e2ec8d281861` when checked. I used a separate HTML extraction pass and compared it with the accepted fixture listing and detail oracle, SHA-256 `46a0d7372a6e73447e59fb2f6a9e3b3e25839ec48a82a3293c98b5874d87db0d`.

| Scope | Employer authority from saved response | Canonical Rippling listings and details |
| --- | --- | --- |
| Forterra `COMP-0066` | `https://www.forterra.com/careers` returned final 200 after interim 103. The raw JavaScript binds existing DOM container `rr-job-board-forterra` to tenant `forterra` and mounts that embed. The same page has separate `rr-job-board-gotenna` and `gotenna-inc` code. No literal Rippling link or iframe exists in the raw HTML. | `https://ats.rippling.com/forterra/jobs` advertised 65 over four unfiltered `en-US` pages, 20/20/20/5. All 65 canonical UUIDs were unique. All 65 listed same-tenant detail pages returned 200, with matching UUID/title/URL and both company and role sections. |
| PDW `COMP-0178` | `https://www.pdw.ai/careers` returned 200, with two canonical `/pdwcareers/jobs` anchors and two shorter `/pdwcareers` anchors. The separately captured shorter route returned a same-host 308 with `Location: /pdwcareers/jobs`. The canonical endpoint was captured directly. | `https://ats.rippling.com/pdwcareers/jobs` advertised 33 over two unfiltered `en-US` pages, 20/13. All 33 canonical UUIDs were unique. All 33 listed same-tenant details returned 200 with matching UUID/title/URL and both description sections. |

The second full read preserved membership, item order, and all captured listing-row metadata for both companies. The initial and reread raw HTML fingerprints differed. Rippling listings showed `DYNAMIC` and `private, no-cache, no-store`; the employer pages had cache hits. PDW careers reported Vercel `HIT`, HTTP Date November 12, and Age 706301 seconds (about 8.2 days). The November 20 live alias and direct board responses corroborate the tenant mapping while the saved PDW employer response has that age limitation. These are raw HTML and server-provided public hydration observations. The independent QA did not execute the Forterra JavaScript or establish browser-rendered widget visibility. Both inventories were nonempty, so the specimen contributes no public zero-opening proof.

### Exact frozen candidate provider replay

The related offline replay ran `ats.fetch_inventory` on the existing frozen candidate source `7f556997f9296433756bf2d825221b8c33e2a1665c39362ca619829c26bf7dad`, with its original Forterra source URL and the canonical PDW Company source. The candidate selected the exact scoped boards and consumed the raw provider captures, with no external discovery or access. The runs completed 65 postings in 73 saved-response reads and 33 postings in 37 saved-response reads. All job identities and full projected descriptions matched the independent oracle. Projection digests were `ce001b011f2dfaf778b4a6980845f8a9af274b8bf635aec3c492b533e32c76b6` for Forterra and `de34debc1ddce8c16a9df083c7165af4c0b6c5d8fce69f346f1159e21975f4ce` for PDW.

The integrated authority parser requires a singleton literal exact board link. Unmodified Forterra raw HTML contributes zero such links because the parser ignores scripts. Unmodified PDW raw HTML contributes two distinct Rippling URLs because the parser does not normalize an independently pinned 308. Both correctly hold under its reviewed synthetic-capture scope. Qualification needs reviewed extraction of Forterra's named mount and exclusion of its sibling tenant, and pinned PDW same-host alias normalization using the original href, exact status/Location, and canonical response. Preserve and bind the raw authority and redirect evidence, freshness and capture time, exact Company row/revision, candidate source/config/dependencies, and complete inventory/details/reread. Use the eventual exact repaired candidate and normal dispatch for independent release review.

### Reproduction

From `/tmp/jsh-m5-validation-independent.pKaySTku`:

```sh
/usr/bin/python3 -I -B ./probe_public_captures.py --terminal
/home/chris/job-search-helper_old/.venv/bin/python -I -S -B -c 'from pathlib import Path; import sys; sys.path.insert(0, str(Path.cwd())); import probe_public_dispatch'
```

Both exited 0. The second command also passed under standard-library-only system Python. The frozen fixture source hashes and the candidate's complete measured source/configuration/dependency vector matched their accepted values. No application, service, queue, workbook, or production state was changed in this QA.
