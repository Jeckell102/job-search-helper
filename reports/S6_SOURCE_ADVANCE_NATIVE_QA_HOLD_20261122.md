# Sprint 6 native source-only composition

**HOLD on the checked entry composition.** The no-active-application predicate runs before the installer acquires the canonical scraper and writer locks. The normal bootstrap still admits a direct canonical manual command through the scraper lock while wrapper and alternate routes are fenced. That command can save unfinished State and release its lock without leaving a pending request. The installer subsequently checks source and queue, but not State under its locks. Run the existing no-active-work predicate under the installer locks before sealing a record or publishing PREPARED.

The package's initial 0664 mode also refused its private-read bootstrap gate; readback confirmed that mode is now 0600. The package SHA is unchanged. The bootstrap loader compares exact physical installed bytes with the two enrolled hashes before execution. Fresh native closure accepts the predecessor only. Restoration permits the exact successor or restored predecessor and admits an interrupted source rollback only under the exact HELD native and quiet records, closed exchange, held services, and an empty listener and route census. The entry installs source only, with no command to run an application worker or publish data. The observer script is separate from all entry actions and its maintenance ID and socket match the window.

Exact source pins

- `native_window.py` `78d07bcd6296b0e11d3e80026a22372a89388a2fa8de015b965915881ca6c7ad`
- `start_observer.sh` `bd41e03929be48646cebf8698562f686d8d1e72e38af88e656d32e924db0ea14`
- `native_source_release_entry.py` `519b2aaa9a6199a5e35b950f6d287533af7077f2c6a7990f0fd390b2b354edcc`
- `maintenance_source_owner.py` `dc854425fa66a8bcef02decf75c25ed48e5fc89634745c9f03f7aab3d2044a98`
- `native_source_advance.py` `ab39e795246d7bb0f2e78907230cc527decaca55f9c38114e354f45a755c5340`

Static source and file-mode review only. No host, observer, production data or network checks.
