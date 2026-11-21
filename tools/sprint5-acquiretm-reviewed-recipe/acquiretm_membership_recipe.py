"""Trusted, source-only AcquireTM readiness repair recipe.

The caller may select the sole independently observed witness, but cannot select
an alternate strategy or mutate the source outside the pinned transformation.
"""
import difflib
import hashlib
import json


VERSION = "acquiretm-listing-membership-v1"
TARGET_PATH = "src/job_search_helper/acquiretm.py"
SOURCE_SHA256 = "a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61"
WITNESS_SHA256 = "d10331c3e89b63ef00a8a26af7ac4c69f66beb95167e3b2005b4d9e101cd0602"
SELECTION = {"strategy": "listing_membership_change", "evidence": "W1"}
W1 = {
    "source": "https://amphenol-aerospace.acquiretm.com/home.aspx",
    "state": "partial",
    "reason": "AcquireTM total changed or pagination repeated.",
    "same_board": True,
    "failure": {
        "category": "pagination_regression",
        "evidence_code": "acquiretm_updatepanel_premature_read",
        "evidence": {
            "page": 2, "advertised_total": 39, "first_page_count": 25,
            "refreshed_page_count": 14, "premature_elapsed_ms": 98,
            "refreshed_elapsed_ms": 347,
            "first_page_ids_sha256": "6f7eca9ad1ac0a8b52027ff5d697b7a1abfc323bc6c9e112bcf4baf832b8a51f",
            "premature_page_ids_sha256": "6f7eca9ad1ac0a8b52027ff5d697b7a1abfc323bc6c9e112bcf4baf832b8a51f",
            "refreshed_page_ids_sha256": "a0e0d5b28e34e8acf04aba4bf800d33f752b286d5441bfaae6f10a26601aec65",
        },
    },
}

OLD_WAIT = '''def _wait_for_update(page, previous: str, timeout: int = ACQUIRETM_REFRESH_TIMEOUT_MS // 1000) -> None:
    try:
        page.wait_for_function(
            "(old) => document.body && document.body.innerHTML !== old",
            arg=previous,
            timeout=timeout * 1000,
        )
    except Exception as exc:
        raise FetchError("partial", "AcquireTM pagination did not complete its UpdatePanel refresh.") from exc
'''
NEW_WAIT = '''def _wait_for_listing_membership_change(page, known, timeout: int = ACQUIRETM_REFRESH_TIMEOUT_MS) -> None:
    """Wait for the clicked board page to expose a new validated listing ID."""
    try:
        page.wait_for_function(
            """({path, seen}) => {
                const previous = new Set(seen);
                return Array.from(document.querySelectorAll('a[href]')).some(anchor => {
                    const url = new URL(anchor.href);
                    const id = url.searchParams.get('ID');
                    return url.origin === location.origin && url.pathname === path
                        && /^[0-9]+$/.test(id || '') && !previous.has(id);
                });
            }""",
            arg={'path': DETAIL_PATH, 'seen': sorted(known)}, timeout=timeout,
        )
    except Exception as exc:
        raise FetchError("partial", "AcquireTM pagination did not expose a new same-board listing.") from exc
'''
OLD_CALL = "        _wait_for_update(page, previous)\n"
NEW_CALL = "        _wait_for_listing_membership_change(page, rows)\n"


def validate_selection(selection):
    if not isinstance(selection, dict) or selection != SELECTION:
        raise ValueError("Only the independently observed W1 membership-change strategy is supported.")
    return dict(SELECTION)


def _validate_witness(witness: bytes) -> None:
    if not isinstance(witness, bytes) or hashlib.sha256(witness).hexdigest() != WITNESS_SHA256:
        raise ValueError("W1 witness pin differs from the independently observed delayed transition.")
    decoded = json.loads(witness)
    for key in ("source", "state", "reason", "same_board"):
        if decoded.get(key) != W1[key]:
            raise ValueError("W1 witness fields are not the exact delayed same-board transition.")
    failure = decoded.get("failure")
    expected_failure = W1["failure"]
    if not isinstance(failure, dict) or any(failure.get(key) != value
                                             for key, value in expected_failure.items()):
        raise ValueError("W1 witness fields are not the exact delayed same-board transition.")


def build(source: bytes, selection, witness: bytes):
    """Return repaired source, reviewable diff, and immutable build receipt; never write."""
    selected = validate_selection(selection)
    _validate_witness(witness)
    if not isinstance(source, bytes) or hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("Source differs from the accepted typed pre-repair baseline.")
    original = source.decode("utf-8")
    if original.count(OLD_WAIT) != 1 or original.count(OLD_CALL) != 1:
        raise ValueError("Pinned pagination anchors are not unique.")
    repaired = original.replace(OLD_WAIT, NEW_WAIT, 1).replace(OLD_CALL, NEW_CALL, 1)
    compile(repaired, TARGET_PATH, "exec")
    if repaired.count("previous.has(id)") != 2 or repaired.count(NEW_CALL) != 1:
        raise ValueError("Membership readiness predicate was not installed exactly once.")
    patch = "".join(difflib.unified_diff(
        original.splitlines(True), repaired.splitlines(True),
        fromfile="a/" + TARGET_PATH, tofile="b/" + TARGET_PATH,
    ))
    return {
        "source": repaired,
        "diff": patch,
        "receipt": {
            "recipe_version": VERSION,
            "target_path": TARGET_PATH,
            "source_sha256": SOURCE_SHA256,
            "output_sha256": hashlib.sha256(repaired.encode()).hexdigest(),
            "witness_id": "W1",
            "witness_sha256": WITNESS_SHA256,
            "selected_evidence": selected,
            "installed": False,
            "live_validated": False,
            "pre_repair_diagnostic_retained": True,
            "authorship": "Host-written fixed source transformation; selection accepts only W1.",
        },
    }
