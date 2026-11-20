# Milestone 5 current public validation specimen

**Disposition: public specimen complete for the two named Rippling boards. Integrated fixture replay held on employer authority format. Release qualification remains open.** The result is tied to the already frozen, previously reviewed working-route candidate. It establishes public scope and posting coverage in the observation window on November 20, 2026, about 5:38–5:42 p.m. Eastern. The separately generated Sprint 5 repair candidate still needs its own current evidence and review.

## Public evidence

| Employer and exact board | Pagination and stable identity | Detail coverage |
| --- | --- | --- |
| Forterra `COMP-0066`, `forterra` | Provider declared 65 openings on four unfiltered pages. Both reads returned 20/20/20/5 rows with 65 canonical unique UUIDs, identical order and listing metadata. | 65/65 exact scoped detail URLs returned HTTP 200 and passed posting UUID, title, listed state, board and full visible provider description checks. |
| PDW `COMP-0178`, `pdwcareers` | Provider declared 33 openings on two unfiltered pages. Both reads returned 20/13 rows with 33 canonical unique UUIDs, identical order and listing metadata. | 33/33 exact scoped detail URLs returned HTTP 200 and passed the same checks. |

- The current Forterra careers response contains distinct, explicitly named Forterra and goTenna widget mounts. In the Forterra section, the employer page assigns `forterra` to `rr-job-board-forterra` when building the public Rippling iframe. The adjacent goTenna widget assigns `gotenna-inc` to its own mount. This is a source-level authority observation. The widget was not rendered for this check. All four exact canonical Forterra provider listing responses identify only `forterra`. [Forterra careers](https://www.forterra.com/careers) · [Forterra Rippling board](https://ats.rippling.com/forterra/jobs)
- The PDW careers response contains both the exact canonical board anchors and a same-tenant shorthand. A separate public GET with redirect following disabled returned HTTP 308 and `Location: /pdwcareers/jobs`. The employer HTML was served from a CDN cache with `Age: 706301` seconds. The public web view also exposed the PDW careers links, and the separate redirect and listing reads returned current provider dates. [PDW careers](https://www.pdw.ai/careers) · [PDW Rippling board](https://ats.rippling.com/pdwcareers/jobs)
- The full public body bytes and original response headers were preserved. Both reads matched all scoped listing rows and all per-page UUID orderings while raw HTML hashes differed. No zero-opening case occurred. The verified descriptions cover the complete visible `company` and `role` sections supplied in each provider response. The independent read stores descriptions as lengths and hashes in the summary and retains source bodies in the staging tree.
- Bounds used were two company career pages, one PDW alias probe, two reads of the six provider listing pages and one GET for each of the 98 listed detail URLs. This yielded 113 successful captures comprising 112 HTTP 200 and the one expected HTTP 308. Requests used public HTTPS GET with a response-size bound and no automatic retries or redirect following. The initial restricted-network DNS failure was resolved using the approved public HTTPS path. No display failure occurred during the observation.

## Candidate and fixture boundary

The exact frozen candidate was remeasured in `/tmp/jsh-m5-pre-release-validation.OHy7TsMZ`. The independent release-admission measurement helper SHA-256 remains `c8a915a8311d74454d292a7f89a0f583b199a5a13832a89f00012cb99c0b500f`.

| Pin | SHA-256 |
| --- | --- |
| Candidate package source | `7f556997f9296433756bf2d825221b8c33e2a1665c39362ca619829c26bf7dad` |
| Candidate configuration | `fafe5191319d13d4c329a6a9e1913460f07b24ad46dbd398c43a0ad430afa1d8` |
| Candidate dependency policy | `d633e308a88f1056ea979f2024a9a0b92c76f3fb6c0030130a79abeb21156d5d` |
| Previously accepted capture oracle | `46a0d7372a6e73447e59fb2f6a9e3b3e25839ec48a82a3293c98b5874d87db0d` |
| Previously accepted fixture validator | `47c734bc718dfbed60e2d15044e72f061715e2a05b7f47fa3f1f3f2089c44dc0` |

The accepted fixture oracle checked the actual listing and detail responses directly. Its employer authority check requires a single literal canonical Rippling link or iframe. Both real authority inputs returned HOLD. Forterra mounts the boards through script, and PDW publishes both literal URL forms. The integrated fixture validator was therefore not run against these captures, and no synthetic employer HTML or `PASS` receipt was created. [Previous synthetic validation and QA](/tmp/jsh-m5-pre-release-validation-handoff.md)

## Independent QA

Independent QA corroborated the public specimen with separate HTML extraction and the accepted oracle. QA also ran a distinct air-gapped provider-only replay of `ats.fetch_inventory` with the exact pinned candidate and raw saved canonical provider responses. The candidate returned all 65 Forterra postings and all 33 PDW postings, and every identity and full description matched the independent oracle. The replay consumed 73 and 37 saved responses respectively. This replay had no integrated employer authority decision. Both original employer inputs still held under the approved fixture authority check. The independent QA report SHA-256 is `55a4f540f16a4391a8748fb9c4597587d09b5e7488bd59b05391ec4f68cc2a30`. [Independent QA report and reproducible probes](/tmp/jsh-m5-validation-independent.pKaySTku/PUBLIC_SPECIMEN_QA.md)

## Evidence and reproducibility

Staging is `/tmp/jsh-m5-current-public-validation.NyyH0uPo`. The verified `SHA256SUMS` binds 233 raw, derived and executable evidence files. Its SHA-256 is `4b724ffead928ea1678e594eddfb4d934ee4139279e661e783ed7aa3397e55ce`. The derived observations SHA-256 is `00d3cfffb774fa7b162eb30656c84843edf449f0c15780d57314e2ec8d281861`. The remeasured candidate receipt SHA-256 is `927c0e5517c6e764dd8aa3a0939123728afdfc6abfba0580651b1b7aa4a72f1c`. The supplemental HTTPS request ledger SHA-256 is `6d073231bc61cfb5d15e673997d8233836724ae3065ce0090a588ff6e12d7625`. The initial four request URLs are recorded separately in the same manifest.

```bash
cd /tmp/jsh-m5-current-public-validation.NyyH0uPo
sha256sum -c SHA256SUMS --quiet
python -I -S -B inspect_public.py
sha256sum -c SHA256SUMS --quiet
```

These checks use local frozen evidence and exit 0. No repeat public requests are needed to reproduce the recorded observations.

[Evidence and response hashes](/tmp/jsh-m5-current-public-validation.NyyH0uPo/public-observations.json) · [Full hash manifest](/tmp/jsh-m5-current-public-validation.NyyH0uPo/SHA256SUMS) · [Candidate binding](/tmp/jsh-m5-current-public-validation.NyyH0uPo/frozen-candidate.json)

## Handoff to release owner

Review a narrow authority proof that can recognize Forterra's named employer widget and verify PDW’s exact same-tenant redirect alongside its canonical links. Keep the two Forterra page widgets explicitly disjoint. Then capture a fresh bounded specimen for the actual generated repair candidate and bind its outcome to that exact version. Production, company records, queues, Sheets, wrappers, release and retry code, and Jetson were untouched.
