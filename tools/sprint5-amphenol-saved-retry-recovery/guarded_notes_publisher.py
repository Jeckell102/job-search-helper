"""Private, opt-in exact publisher adapter for sealed Job History notes.

The normal synchronizer is deliberately unchanged.  This adapter exists only
for an already-sealed exact projection whose Job History ``Review Notes`` was
locally materialized as an append.  It restores that append representation
after the base planner has done all of its ordinary identity, dirty, guard,
and projection checks.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Mapping

from job_search_helper.repository import _identity_key
from job_search_helper.sheets_sync import SheetsSynchronizer, _digest, _required_id


_NOTE = "Review Notes"


def _append_once(prefix, suffix):
    """Match repository.py's append-only normalization exactly."""
    if suffix in prefix:
        return prefix
    return prefix + ("\n\n" if prefix else "") + suffix


class GuardedJobHistoryNotesSynchronizer(SheetsSynchronizer):
    """Narrow opt-in adapter; all non-note exact rows use the base result."""

    def _plan_exact_row(self, item, frozen_operation=None, *,
                        delivery_mode="write_once"):
        result = super()._plan_exact_row(
            item, frozen_operation, delivery_mode=delivery_mode)
        if not self._is_sealed_history_note(item, frozen_operation):
            return result

        frozen = frozen_operation
        sealed_notes = frozen["append_notes"]
        suffix = sealed_notes[_NOTE]
        if not isinstance(suffix, str) or not suffix.strip():
            raise ValueError("Guarded Job History note suffix is invalid.")
        if frozen.get("append_if_missing") is not False:
            raise ValueError("Guarded Job History note must update an existing row.")
        if set(sealed_notes) != {_NOTE}:
            raise ValueError("Guarded publisher only supports sealed Review Notes.")

        values = frozen.get("values", {})
        inserted = frozen.get("on_insert", {})
        expected = frozen.get("expected", {})
        if not all(isinstance(group, Mapping)
                   for group in (values, inserted, expected)):
            raise ValueError("Guarded Job History note mappings are invalid.")
        # Existing-row append semantics in repository.py use an explicit
        # replacement only when present; otherwise its expected preimage is
        # the only deterministic safe prefix.  A sealed note cannot also be
        # a replacement or insert value for the same field.
        if _NOTE in values or _NOTE in inserted or _NOTE not in expected:
            raise ValueError("Guarded Job History note lacks an exact prefix.")
        prefix = str(expected[_NOTE] or "")
        target = _append_once(prefix, suffix)

        operation = result["operation"]
        sent = result["sent"]
        if (result["tab"] != "Job History"
                or operation.get("tab") != "Job History"
                or result["identity"] != item["identity"]
                or sent.get(_NOTE, "") != target
                or operation.get("values", {}).get(_NOTE, "") != target
                or operation.get("append_notes", {})
                or operation.get("expected", {}).get(_NOTE) != expected[_NOTE]):
            raise ValueError("Guarded Job History note no longer matches sealed prefix and suffix.")

        # Do not alter any normal values/guards/identity.  Reconstitute only
        # this explicitly sealed note representation, so base plan equality
        # compares against the frozen remote projection byte-for-byte.
        operation = copy.deepcopy(operation)
        del operation["values"][_NOTE]
        operation["append_notes"] = {_NOTE: suffix}
        result = copy.deepcopy(result)
        result["operation"] = operation
        return result

    def _durable_exact_plan(self, inbox, *, cycle_id, company_id, plan_digest,
                            receipt_id, intent_id):
        """Rebuild the exact scope exclusively from durable trusted records."""
        inbox = self._require_exact_inbox(inbox)
        cycle_id = _required_id(cycle_id, 'cycle ID')
        company_id = _required_id(company_id, 'Company ID')
        plan_digest = _required_id(plan_digest, 'plan digest')
        receipt_id = _required_id(receipt_id, 'receipt ID')
        intent_id = _required_id(intent_id, 'intent ID')
        with inbox.lock:
            remote = inbox.connection.execute(
                'SELECT local_plan_digest,projection,projection_digest,'
                'receipt_id,intent_id,delivery_mode FROM exact_remote_plans '
                'WHERE cycle=? AND company=?', (cycle_id, company_id)).fetchone()
            delivery = inbox.connection.execute(
                'SELECT delivery_mode,plan_digest,state,evidence '
                'FROM exact_legacy_delivery_evidence '
                'WHERE cycle=? AND company=?',
                (cycle_id, company_id)).fetchone()
            frozen = inbox.connection.execute(
                'SELECT p.payload,l.plan_digest,l.state FROM sync_plans p '
                'JOIN exact_plan_local_state l '
                'ON l.cycle=p.cycle AND l.company=p.company '
                'WHERE p.cycle=? AND p.company=?',
                (cycle_id, company_id)).fetchone()
        if remote is None or (remote[0], remote[3], remote[4]) != (
                plan_digest, receipt_id, intent_id):
            raise ValueError('Exact Sheets durable remote binding is unavailable.')
        try:
            projection = json.loads(remote[1])
        except (TypeError, ValueError) as error:
            raise ValueError('Exact Sheets durable projection is invalid.') from error
        if not isinstance(projection, list) or _digest(projection) != remote[2]:
            raise ValueError('Exact Sheets durable projection is invalid.')
        if frozen is None or frozen[1:] != (plan_digest, 'LOCAL_VERIFIED'):
            raise ValueError('Exact Sheets durable local plan is unavailable.')
        try:
            plan = json.loads(frozen[0])
        except (TypeError, ValueError) as error:
            raise ValueError('Exact Sheets durable local plan is invalid.') from error
        from job_search_helper.exact_cycle_planner import _exact_plan_digest
        if (not isinstance(plan, Mapping)
                or plan.get('plan_digest') != plan_digest
                or _exact_plan_digest(plan) != plan_digest
                or not isinstance(plan.get('local_operations'), list)):
            raise ValueError('Exact Sheets durable local plan is invalid.')
        stored_projection = plan.get('remote_projection', plan.get('operations'))
        if stored_projection != projection:
            raise ValueError('Exact Sheets durable projection conflicts with its local plan.')
        delivery_mode = remote[5]
        if delivery_mode not in {'write_once', 'observation_only'}:
            raise ValueError('Exact Sheets durable delivery mode is invalid.')
        if delivery_mode == 'observation_only':
            if (delivery is None
                    or tuple(delivery[:3]) != (
                        'observation_only', plan_digest, 'BOUND')):
                raise ValueError('Exact Sheets observation evidence is unavailable.')
        elif delivery is not None and delivery[0] != 'write_once':
            raise ValueError('Exact Sheets delivery evidence conflicts with its mode.')
        if not self.local.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='exact_local_applications'").fetchone():
            raise ValueError('Exact Sheets durable row scope is unavailable.')
        parent = self.local.db.execute(
            'SELECT plan_digest,row_scope,state FROM exact_local_applications '
            'WHERE cycle=? AND company=?', (cycle_id, company_id)).fetchone()
        if parent is None or parent[0] != plan_digest or parent[2] != 'VERIFIED':
            raise ValueError('Exact Sheets durable row scope is unavailable.')
        try:
            row_scope = json.loads(parent[1])
        except (TypeError, ValueError) as error:
            raise ValueError('Exact Sheets durable row scope is invalid.') from error
        normalized = self._normalize_exact_scope(row_scope)
        if len(normalized) != len(projection):
            raise ValueError('Exact Sheets durable scope changed after registration.')

        def final_identity(operation):
            identity = dict(operation.get('identity', {}))
            for values in (operation.get('on_insert', {}), operation.get('values', {})):
                for key in tuple(identity):
                    if key in values:
                        identity[key] = values[key]
            return identity

        def key(tab, identity):
            return tab, tuple(sorted((header, _identity_key(header, value))
                                     for header, value in identity.items()))

        by_identity = {key(item['tab'], item['identity']): item for item in normalized}
        projected = [key(operation['tab'], final_identity(operation)) for operation in projection]
        if (len(by_identity) != len(normalized) or len(set(projected)) != len(projected)
                or set(by_identity) != set(projected)):
            raise ValueError('Exact Sheets durable scope/projection identities differ.')

        rows = []
        for operation, selected in zip(projection, projected):
            item = by_identity[selected]
            candidates = [candidate for candidate in plan['local_operations']
                          if candidate.get('tab') == item['tab']
                          and final_identity(candidate) == item['identity']]
            if len(candidates) != 1 or operation.get('tab') != item['tab']:
                raise ValueError('Exact Sheets durable row evidence is ambiguous.')
            local_operation = candidates[0]
            frozen_values = dict(local_operation.get('expected', {}))
            frozen_values.update(local_operation.get('on_insert', {}))
            frozen_values.update(local_operation.get('values', {}))
            if self._is_sealed_history_note(item, operation):
                expected = local_operation.get('expected', {})
                notes = operation['append_notes']
                suffix = notes[_NOTE]
                if (operation.get('append_if_missing') is not False or set(notes) != {_NOTE}
                        or local_operation.get('append_notes') != notes or _NOTE not in expected
                        or expected[_NOTE] != operation.get('expected', {}).get(_NOTE)
                        or _NOTE in local_operation.get('on_insert', {})
                        or _NOTE in local_operation.get('values', {})
                        or not isinstance(suffix, str) or not suffix.strip()):
                    raise ValueError('Guarded Job History durable note differs from the sealed append.')
                frozen_values[_NOTE] = _append_once(str(expected[_NOTE] or ''), suffix)
            if any(header not in frozen_values for header in item['fields']):
                raise ValueError('Exact Sheets durable row evidence is incomplete.')
            rows.append({**copy.deepcopy(item),
                         'sent': {header: copy.deepcopy(frozen_values[header])
                                  for header in item['fields']},
                         'operation': copy.deepcopy(operation)})
        exact_plan = {'operations': copy.deepcopy(projection), 'rows': rows,
                      'projection_digest': remote[2],
                      'delivery_mode': delivery_mode,
                      'record_fingerprint_version': plan.get(
                          'record_fingerprint_version', 1)}
        self._validate_exact_plan(exact_plan)
        if delivery_mode == 'observation_only':
            # Observation has no write claim to define a point of no return;
            # local selected values and manual/source guards must therefore
            # remain exact on both sides of every remote read.
            self._revalidate_exact_rows(exact_plan)
            try:
                delivery_evidence = json.loads(delivery[3])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    'Exact Sheets observation evidence is invalid.') from error
            from job_search_helper.exact_legacy_migration import validate_legacy_delivery_evidence
            validate_legacy_delivery_evidence(
                self.local, exact_plan['operations'], delivery_evidence)
        return exact_plan

    @staticmethod
    def _is_sealed_history_note(item, frozen_operation):
        return (
            isinstance(item, Mapping)
            and item.get("tab") == "Job History"
            and isinstance(frozen_operation, Mapping)
            and frozen_operation.get("tab") == "Job History"
            and isinstance(frozen_operation.get("append_notes"), Mapping)
            and _NOTE in frozen_operation["append_notes"]
        )
