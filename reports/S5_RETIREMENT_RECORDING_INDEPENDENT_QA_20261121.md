# Independent retirement marker recording recheck

**ACCEPT** for recording one already approved archive-scoped retirement marker under the existing SQLite ownership leases.

| Candidate | SHA-256 |
|---|---|
| `retained_cycle_retirement_control.py` | `4977f8a8fce2bee25e01789a1698da8afc736cee619b25a39430e38070f782ef` |
| `retained_cycle_retirement.py` | `5178bd1f9a0d844d137cab9c0e65933cc5a2835ed479d73a2850b84990a6aa8e` |
| `tests/test_retained_cycle_retirement.py` | `b5c900f9af6c523661a076f350685605a506a1588e354df63291992e112f1282` |

The corrected recorder checks the SQLite backend before path resolution and lock entry. It takes the normal scraper, Sheets writer and review writer leases in that order and holds them across archive verification and the State transaction. The independent original regression kept the actual review writer lease open. The corrected recorder raised the existing busy exception and created no retirement table. The separate non-SQLite fixture refused before creating or touching any lease, State, Jobs, or Inbox file.

The exact successful path recorded one marker, retained the original State cycle row, and left Jobs and Inbox bytes unchanged. The archive proof compared literal saved inventory, plan and historical receipt bytes. Incorrect scope and changed replay reason refused, and exact replay recovered the first marker. The combined disposable suite passed 13 tests under a socket audit guard. Scope is marker recording. Runtime retirement consumers and live operation remain separate acceptance gates.
