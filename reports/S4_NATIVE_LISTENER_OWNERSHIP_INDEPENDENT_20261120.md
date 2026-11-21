# Independent listener ownership source review

**ACCEPT for source within the approved boundary.** The ownership boundary is the launch account in the enrolled native network namespace, with a trusted administrator observer for enrolled system helpers. Review scope was the disposable source and fixtures.

| Reviewed file | SHA-256 |
| --- | --- |
| [ancillary_process_witness.py](/tmp/jsh-s4-listener-observer.Zwv760tc/ancillary_process_witness.py) | `f4a82eaed30a46b507c525875418d4ec471b8b9147036adc67061970a5e70819` |
| [host_checkpoint.py](/tmp/jsh-s4-listener-observer.Zwv760tc/host_checkpoint.py) | `fe5ac8bed3ab1e88ff645859ba6f156229694643d3b3549415748c8952016e43` |
| [test_ancillary_process_witness.py](/tmp/jsh-s4-listener-observer.Zwv760tc/test_ancillary_process_witness.py) | `47de4f8e5d1ae438ebe96f9b2289d3c8b21977f79c81129ea2fb6dc128187658` |
| [Independent fixtures](/tmp/jsh-s4-listener-independent.TZp0LEwj/test_listener_review.py) | `d15ffd7b8abf1bccdfdf040cd53a36d2a828055c4694cc069f040b7f52742a95` |

The host check pins the network namespace, reads the exact configured IPv4 loopback port, and requires the approved wrapper to possess the current listening inode set. It scans the other launch-account processes and delegates a descriptor permission gap to the administrator observer. An incomplete descriptor inventory holds if its PID is still present. The site attestation compares the listener sets from two checks. [Ownership check](/tmp/jsh-s4-listener-observer.Zwv760tc/host_checkpoint.py:175) · [Second check](/tmp/jsh-s4-listener-observer.Zwv760tc/host_checkpoint.py:448)

The observer requires the operator-enrolled port, approved request scope and PID, and a current process identity for an approved role. It compares the actual listener inode set immediately before and after reading the helper descriptors and rejects an exact socket match. The checker validates the returned process identity and a fresh challenge bound to the original request, including the port and inode set. A response limited to checkout-route evidence cannot fill the ownership gap. [Listener inspection](/tmp/jsh-s4-listener-observer.Zwv760tc/ancillary_process_witness.py:59) · [Response verification](/tmp/jsh-s4-listener-observer.Zwv760tc/ancillary_process_witness.py:168) · [Request enrollment](/tmp/jsh-s4-listener-observer.Zwv760tc/ancillary_process_witness.py:215)

The final combined run passed **114 tests**, including 11 independent fixtures. The independent fixtures accepted a fresh matching observation even when the helper held a socket on a different port. They held visible and observer-detected shared ownership, loss of the wrapper descriptor, listener change before and during observation, route-only evidence, wrong inode or port, stale challenge or process identity, an unknown role, and a missing descriptor inventory on a still-present process. [Independent fixtures](/tmp/jsh-s4-listener-independent.TZp0LEwj/test_listener_review.py:41)

The first run exposed the live-PID metadata hole in source and an order-sensitive fixture. The final pins include the corrections. Two unchanged native Unix socket tests returned `Operation not permitted` in this test environment and were deselected for the final combined run. The independent fixtures use synthetic process metadata and a simulated observer connection that runs the real listener table and descriptor checks.
