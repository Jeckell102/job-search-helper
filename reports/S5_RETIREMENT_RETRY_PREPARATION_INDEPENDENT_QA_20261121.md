# Independent retry preparation mode check

**ACCEPT** for the pinned preparation-only retry from a fresh scope.

| Exact reviewed file | SHA-256 |
|---|---|
| `prepare_native.py` | `d917ccb537f09c29216d1be97b3178f8b9ee5cc1ff068a29e464eb47a40ca2b8` |
| `test_prepare_native.py` | `164717f0b7d4cf69d3364fb76d87b4d1663ad991615e9fd96b8f60296dd30a34` |

The source diff changes only the fresh release ID, its observer path, and creation of the new controller at owner-only executable mode. It copies the reviewed controller bytes verbatim into a newly created 0700 file before enrollment. It does not revise the prior capsule or the payload. The fresh ID is `s5-owner-retirement-20261121-02`, the attempt uses its `-attempt` sibling, and the only enrolled observer is `/run/jsh-s5-owner-retirement-02/observer.sock`. The approved source manifest, exact installed predecessor, distinct current witness, exchange preparation, and attempt guard remain the same.

All seven disposable preparation tests passed. The enrollment seam checked the controller mode and exact shebang before returning the fixture enrollment. The real child launched directly with only `--help`, and the guarded test rejected any other subprocess command. The prepared exchange stayed at zero completed moves and routes and predecessor fixture files were preserved. Production paths and external operations were denied by the test audit guard. This review covers staged preparation and the executable regression, with native enrollment and installation outside the result.
