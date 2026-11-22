# Receipt-aware Embraer disarm: staged only

Entry native_embraer_disarm.py SHA eb5fe67a0b13f120109e1bf337cd409758664fa2c6963a9ff2bef26af0874003.
Fixture test_disarm_receipt.py SHA 80008cb64749558d3c8edf68a7db98b9ba56ffb87daecc64794fcb71a664036d.
Three pure disposable readback tests pass: exact terminal receipt and independent pin; changed current coordinator reference; foreign original deployment or unfinished transition refusal. No native action, task read or service call was executed by the author.

This is a narrow copied-entry delta from the original 211e71de armer. Supported actions inspect/disarm only. Invocation retains original request ID/hash and reviewed entry SHA, adding mandatory --forward-receipt-sha256 for the independently reviewed eventual terminal file at ../forward/transaction/receipt.json. This dynamic pin is not known until the real tool update finishes; no receipt is invented by this slice.

It uses the original app source owner, active original release/journal/receipt, restored -12 records, current application source proof and exact sender/receiver/task/baseline ownership. It measures the terminal coordinator reference (device/inode/mode/owner/hash/mtime), pinned predecessor and restart reference, rejects eligible coordinator bytecode, then reuses extended_window from forward/native_forward.py to prove no other tool change. It repeats receipt/source readback under leases and during service inspection. Original -12 and initial armer files are unchanged.

Inspect is a withdrawal-readiness check: it requires the task at a real operator terminal gate or explicitly stopped quiescent abort, no unresolved inference/tool action and no foreign active task. It does not convert a paused blocked task into an aborted or completed task. Actual disarm delegates to existing embraer_pilot_arming.reconcile_pilot, preserves paired receipt custody and changes only the exact enrollment variable plus targeted wrapper restart.

Standalone invocation uses the existing fresh -13 observer and will hold if it has expired. Do not request an extra maintenance window just for this prepared source. A later approved native release can reuse the receipt check, extension and underlying disarm library while it already owns current process exclusion and service restoration; withdraw before application source advances, since original operator source proof intentionally binds REL-2a5c7bb2ad922f73cf868d15. That caller must supply its own exact approved current native context rather than editing this entry's fixed observer binding or reusing an expired observer.

No live withdrawal or release acceptance is claimed. Independent source review and actual terminal-receipt pin remain root-owned.
