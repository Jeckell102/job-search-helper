# Final source-advance recheck

**ACCEPT for the staged interruption handling.** After it verifies the exact retained record and unchanged predecessor, the reuse branch now fsyncs the record's parent before returning to the caller that publishes PREPARED. An error at this barrier leaves the predecessor journal in place. Both fresh creation and reuse now have the same directory persistence barrier.

Installer SHA-256 `ab39e795246d7bb0f2e78907230cc527decaca55f9c38114e354f45a755c5340`. Composed fixture SHA-256 `54e99d5b34941eab6a74d5280deb2e1be4a34acc92aa6f9af9ff8659dcffc5e7`. The coordinator's existing composed fixture passed on these exact pins. This was a source-only recheck. The initial hold report is preserved beside this file.
