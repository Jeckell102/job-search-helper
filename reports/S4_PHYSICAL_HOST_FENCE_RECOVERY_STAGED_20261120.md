# Physical wrapper refusal recovery and site witness

November 20, 2026. Source-only repaired tool candidate:
`/tmp/jsh-s4-combined-host-fence-recovery.fOcKhtD5`. Previous physical
tool QA held on post-reopen refusal, closure order and journal write
failure, and the inability to choose rollback after a refused release.

The repaired controller now includes reopen in refusal recovery and
attempts the independently pinned direct entry closure before potentially
slow service closure, even if the refusal journal write raises an
ordinary error. The marker, unit and canonical-host drain checks are
attempted independently. An explicit rollback from HOST_REOPEN or
RELEASE_REFUSED first re-establishes the holds and then uses the saved
before image. Three new targeted cases failed at the previous pin and
passed with the two earlier payload/projection checks at this pin.
Independent source recovery QA and repaired controller rollback fixture
are running. The older fixture verified twelve cases across staged runs
and corrected negative controls. It remains evidence for the older pin.

The alternate-route architecture review found both known same-workbook
copies launchable and the migration fallback unresolved. It recommended
administrator-controlled, per-checkout pathname covers spanning the
install and one approved pilot, with actual namespace and stale/open
worker checks. The read-only staged witness helper validates a precise
mount identity and flags under the known launch UID and namespace, then
checks that exact launcher paths cannot be opened. Five helper tests
passed using disposable inputs. This is part of a future approved
host-backed checker and has not been applied to any real cover.
No non-interactive administrator authorization was established at
preflight. Nothing was mounted, stopped, installed, or changed on
MuleLab production or the Jetson.
