# Release-qualification custody dependency slice

This scratch-only repair removes a provider-specific import from the automated
release qualification gate.  It does not change release policy, owner
authority, qualifying receipt fields, or any provider capture workflow.

## Design

`private_file_custody.py` is a narrow extraction of the existing local custody
primitives: canonical decode, directory owner/mode/identity, absolute
component-wise no-follow directory lookup, regular-file owner/mode/link-count,
physical stamp, no-follow read, size bound, pre/post stat, named-path check,
and identity return.  It defaults to `CustodyError(ValueError)`.

`ordinary_raw_capture.py` retains its public private helpers as wrappers that
pass `CaptureError`; its existing capture consumers therefore retain the same
types and error codes.  `release_qualification.py` imports the neutral helper
directly.  It preserves its exact descriptor duplication, root identity check,
approved receipt hash, canonical decode, receipt schema/value checks, and final
named-file/root rechecks.

## Baseline pins

- `ordinary_raw_capture.py`: `b038adffbdf2bac9811806a8aaecf2cb816cebeb2bcce73037447670503ee571`
- `release_qualification.py`: `886e6ac97e9b4979fdde4cb9f01630a8896edb569418f19bdfd76c7190f323d5`
- `tests/test_release_qualification.py`: `11d7bcd0964bc5b1e90fa90f97faa7867c7130793f3b54d16f2ed5dda3fdd9ee`

## Changed files

- `src/job_search_helper/private_file_custody.py` (new neutral equivalent)
- `src/job_search_helper/ordinary_raw_capture.py` (delegating wrappers only)
- `src/job_search_helper/release_qualification.py` (neutral helper import)
- `tests/test_release_qualification_custody_import.py` (fresh subprocess import
  regression with a blocker for `job_search_helper.ordinary_raw_capture`)

## Focused verification

```
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q \
  tests/test_release_qualification.py \
  tests/test_release_qualification_custody_import.py \
  tests/test_ordinary_raw_capture.py
```

Result: `77 passed in 1.39s`.

The import regression uses `-I -S -B` in a fresh subprocess and a meta-path
blocker that fails immediately if release qualification resolves the old
provider-specific raw capture module.  It imported the neutral helper instead.
No production, release, data, service, network, or provider operation occurred.
