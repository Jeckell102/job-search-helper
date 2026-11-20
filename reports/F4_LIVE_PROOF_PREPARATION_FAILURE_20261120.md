# F4 live proof preparation failure

The first run of the one-shot validation tool stopped with a ValueError while preparing its disposable coordinator ledger. Its private checkpoint remained PREPARING, before a request binding or dispatch was recorded. A fresh read-only check of Jetson found the same three terminal receipts and no new receipt. The first run made no inference request.

The harness owner is reproducing the failure in a new disposable ledger. The failed checkpoint is preserved. Installed paired source and operational checks already passed independent QA. Full deployed F4 acceptance remains open pending the corrected live proof.
