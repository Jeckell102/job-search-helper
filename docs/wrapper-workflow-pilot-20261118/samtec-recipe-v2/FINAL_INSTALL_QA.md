# Final independent installation QA

PASS for exact reviewed candidate `2c08149e746b98f970d6ed98f2944dde3c51db0e3cb4b2f69c728b7a3c706847`. Two fresh normal-dispatch runs each returned all 148 public jobs. All three listing pages were read twice per run; each of the 148 details was freshly downloaded per run. Independently rechecked all 308 response hashes, all 185 source hashes, stable IDs/URLs, and every complete description, title, location and department against captured public HTML. Employer and exact application identity checks passed.

66 offline tests passed before live validation. Current main source matches the live snapshot except the intended shared-board replacement. The guarded installer was reviewed and its hash is recorded. Four exact test files are approved for required installed verification (60 tests, including all 148 actual saved detail pages).

This permits only the scoped guarded installation, with automatic rollback if required checks fail. It does not enable the queue or publish jobs. The working implementation is AI-assisted configuration with host-written Python-generated code, not autonomous Jetson code generation.
