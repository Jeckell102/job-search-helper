# One-shot Amphenol operator release source review

**REJECT** source `e35ab4e3a093ebfdd04a17349456a3aee89c40a90eca03c2311d08a08aa2845d` due to a reproduced coordinator database mutation on held controls. The original source is preserved alongside this report.

| Evidence | SHA-256 |
| --- | --- |
| Independent test | `36ae8d08c4453ea3170089f7db03f1ff23b4dad8dc02ab218b5af324dfff0cf1` |
| Original test output | `645e00e16cfc07798e4d19bb42db6d4c59eb4420dee10ac5c5374c1f94229367` |
| Successful owner canary result | `9ff4e67ef53162089b6d7ad47f01c6c0f8f4a1e77ad6e28c9842036ca6fec993` |
| Independent immutable canary readback | `c71d27dea4cd92b19f42035ca6897c0ae1052a067935ee08bd1f23f695f8f43a` |

Five focused checks passed. A default call reaches neither approval nor the outer scope. A wrong private receipt digest is rejected before the scope or Store. The actual file locks acquire scheduler before supervision, use the existing inodes without creating or truncating them, release on contention, and remain held through the selected terminal receipt. Source shows no loop startup or control-enable calls.

The failed check starts from an existing fully populated current Store schema with queue enabled and conventional DELETE journaling. The actual one-shot reports `HELD_OPERATOR_COORDINATOR_CONTROLS` and never calls release, yet it changes the database bytes to WAL format. It constructs `Coordinator` before reading the controls or retained operator owner. The normal Store constructor executes WAL setup and DDL. It can also alter an existing schema. The one-shot needs an existing-Store attachment that skips startup writes, with read-only gates and the specific existing receipt write when authorized.

The actual combined canary copied the exact reviewed source. Immutable reads verified a confirmed one-shot, one `VALIDATED_COMPLETE` lifecycle/event, two matching sender/receiver receipt pairs, zero task or inference rows, one `SYNC_CONFIRMED` fixture publication, and one job in one fixture batch. That canary starts with an already bootstrapped receiver and covers recovery from a completed activation cut. Its injected maintenance scope is a fixture. The actual owner still must supply trusted exclusion of host startup, shutdown, and other writers. A fresh normal activation through the assembled one-shot and real live authorization remain separate.

Only staged source, disposable stores and saved canary artifacts were used. No native operation or network call was made.
