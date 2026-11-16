"""One-pass orchestration for automatic Phase 1 event relinking."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from typing import Callable, Sequence

from sqlalchemy.orm import Session

from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import BuybackEventLinkDecision
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.usecase.build_plan_link_candidates import (
    build_plan_link_candidates,
)
from buyback_analysis.usecase.event_schemas import BuybackEventExtraction
from buyback_analysis.usecase.link_existing_plan_events import (
    ExistingPlanEvaluation,
    PlanLinkCandidate,
    evaluate_amendment,
    evaluate_completion,
    evaluate_equity_compensation,
    evaluate_execution_notice,
    evaluate_non_linkable,
    evaluate_progress,
    evaluate_retirement,
    evaluate_supplement,
)
from buyback_analysis.usecase.link_new_plan import decide_new_plan, evaluate_new_plan
from buyback_analysis.usecase.link_normalization import normalize_date
from buyback_analysis.usecase.persist_existing_plan_decision import (
    persist_existing_plan_decision,
)
from buyback_analysis.usecase.rebuild_plan_projection import rebuild_plan_projection


@dataclass(frozen=True)
class RelinkResult:
    evaluated: int = 0
    linked: int = 0
    unresolved: int = 0
    ambiguous: int = 0
    skipped_linked: int = 0


def _event_from_row(row: BuybackEvent):
    return BuybackEventExtraction.model_validate(
        {
            "events": [
                {
                    "event_type": row.event_type,
                    "event_date": row.event_date,
                    "resolution_date": row.resolution_date,
                    "referenced_document_date": row.referenced_document_date,
                    "referenced_document_title": row.referenced_document_title,
                    "source_quote": row.source_quote,
                    "source_page": row.source_page,
                    "source_section": row.source_section,
                    "payload": row.payload,
                }
            ]
        }
    ).events[0]


def _input_fingerprint(
    event_fingerprint: str,
    candidates: Sequence[PlanLinkCandidate],
    extra_candidate_refs: Sequence[str] = (),
) -> str:
    value = {
        "event_fingerprint": event_fingerprint,
        "candidates": [asdict(candidate) for candidate in candidates],
        "extra_candidate_refs": sorted(extra_candidate_refs),
    }
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _compare_new_plan_values(event, values: tuple) -> str:
    resolution_date, shares, amount, start_date, end_date = values
    if normalize_date(event.resolution_date) != normalize_date(resolution_date):
        return "DISTINCT"
    pairs = (
        (event.payload.buyback_shares, shares),
        (event.payload.buyback_amount_yen, amount),
        (normalize_date(event.payload.start_date), normalize_date(start_date)),
        (normalize_date(event.payload.end_date), normalize_date(end_date)),
    )
    comparable = [(left, right) for left, right in pairs if left is not None and right is not None]
    if any(left != right for left, right in comparable):
        return "DISTINCT"
    if comparable:
        return "SAME"
    return "AMBIGUOUS"


def _compare_new_plan_candidate(event, candidate: PlanLinkCandidate) -> str:
    return _compare_new_plan_values(
        event,
        (
            candidate.resolution_date,
            candidate.original_shares,
            candidate.original_amount_yen,
            candidate.original_start_date,
            candidate.original_end_date,
        ),
    )


def _compare_new_plan_peer(event, peer) -> str:
    return _compare_new_plan_values(
        event,
        (
            peer.resolution_date,
            peer.payload.buyback_shares,
            peer.payload.buyback_amount_yen,
            peer.payload.start_date,
            peer.payload.end_date,
        ),
    )


def _new_plan_sort_key(row: BuybackEvent) -> tuple[str, str, str]:
    return (
        row.disclosure_datetime or row.event_date or "",
        row.url,
        row.event_uid,
    )


def _evaluate_existing(event, candidates):
    evaluators = {
        "amendment": evaluate_amendment,
        "execution_notice": evaluate_execution_notice,
        "progress": evaluate_progress,
        "completion": evaluate_completion,
        "supplement": evaluate_supplement,
        "equity_compensation": evaluate_equity_compensation,
        "retirement": evaluate_retirement,
        "other_party_transaction": evaluate_non_linkable,
        "other": evaluate_non_linkable,
    }
    evaluator = evaluators.get(event.event_type.value)
    if evaluator is None:
        raise ValueError(f"unsupported event type: {event.event_type.value}")
    return evaluator(event, candidates)


def _current_decisions(session: Session, event_uids: Sequence[str]):
    if not event_uids:
        return {}
    decisions = (
        session.query(BuybackEventLinkDecision)
        .filter(
            BuybackEventLinkDecision.event_uid.in_(event_uids),
            BuybackEventLinkDecision.is_current.is_(True),
        )
        .all()
    )
    return {decision.event_uid: decision for decision in decisions}


def relink_buyback_events(
    session: Session,
    *,
    code: str,
    rule_version: str,
    aggregation_rule_version: str = "projection:v1",
    uid_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> RelinkResult:
    """Evaluate eligible active events once; never commits the transaction."""

    events = (
        session.query(BuybackEvent)
        .filter(BuybackEvent.code == code, BuybackEvent.is_active.is_(True))
        .order_by(BuybackEvent.event_uid)
        .all()
    )
    current = _current_decisions(session, [event.event_uid for event in events])
    eligible: list[BuybackEvent] = []
    skipped_linked = 0
    for event in events:
        decision = current.get(event.event_uid)
        if (
            decision is not None
            and decision.decision_kind == "NORMAL"
            and decision.status == "LINKED"
        ):
            skipped_linked += 1
            continue
        eligible.append(event)

    statuses: list[str] = []
    snapshot_candidates = build_plan_link_candidates(session, code=code)
    new_plans = [event for event in eligible if event.event_type == "new_plan"]
    remaining = [event for event in eligible if event.event_type != "new_plan"]
    parsed_new_plans = {
        row.event_uid: _event_from_row(row) for row in new_plans
    }

    for row in new_plans:
        event = parsed_new_plans[row.event_uid]
        existing_origin = (
            session.query(BuybackPlan)
            .filter(BuybackPlan.origin_event_uid == row.event_uid)
            .one_or_none()
        )
        existing_duplicate_ids = [
            candidate.plan_id
            for candidate in snapshot_candidates
            if _compare_new_plan_candidate(event, candidate) == "SAME"
            and (
                existing_origin is None
                or candidate.plan_id != existing_origin.buyback_plan_id
            )
        ]
        ambiguous_existing_ids = [
            candidate.plan_id
            for candidate in snapshot_candidates
            if _compare_new_plan_candidate(event, candidate) == "AMBIGUOUS"
        ]
        same_peer_rows = [
            peer_row
            for peer_row in new_plans
            if peer_row.event_uid != row.event_uid
            and _compare_new_plan_peer(
                event, parsed_new_plans[peer_row.event_uid]
            )
            == "SAME"
        ]
        same_group = [row, *same_peer_rows]
        qualified_rows = [
            candidate_row
            for candidate_row in same_group
            if evaluate_new_plan(
                parsed_new_plans[candidate_row.event_uid]
            ).status
            == "LINKED"
        ]
        canonical_uid = (
            min(qualified_rows, key=_new_plan_sort_key).event_uid
            if qualified_rows
            else None
        )
        if canonical_uid is None:
            peer_refs = [
                f"event:{peer_row.event_uid}" for peer_row in same_peer_rows
            ]
        else:
            peer_refs = (
                [] if row.event_uid == canonical_uid else [f"event:{canonical_uid}"]
            )
        ambiguous_peer_refs = [
            f"event:{peer_uid}"
            for peer_uid, peer in parsed_new_plans.items()
            if peer_uid != row.event_uid
            and _compare_new_plan_peer(event, peer) == "AMBIGUOUS"
        ]
        conflict_refs = [
            *existing_duplicate_ids,
            *ambiguous_existing_ids,
            *peer_refs,
            *ambiguous_peer_refs,
        ]
        input_fingerprint = _input_fingerprint(
            row.event_fingerprint, snapshot_candidates, conflict_refs
        )
        if (
            len(existing_duplicate_ids) == 1
            and not peer_refs
            and not ambiguous_existing_ids
            and not ambiguous_peer_refs
            and evaluate_new_plan(event).status == "LINKED"
        ):
            duplicate_plan_id = existing_duplicate_ids[0]
            decision = persist_existing_plan_decision(
                session,
                event_uid=row.event_uid,
                evaluation=ExistingPlanEvaluation(
                    "LINKED",
                    duplicate_plan_id,
                    (duplicate_plan_id,),
                    ("SAME_RESOLUTION_AND_TERMS",),
                ),
                rule_version=rule_version,
                input_fingerprint=input_fingerprint,
                uid_factory=uid_factory,
            )
        else:
            decision = decide_new_plan(
                session,
                event_uid=row.event_uid,
                candidate_plan_ids=conflict_refs,
                rule_version=rule_version,
                input_fingerprint=input_fingerprint,
                uid_factory=uid_factory,
            )
        statuses.append(decision.status)

    for row in remaining:
        event = _event_from_row(row)
        evaluation = _evaluate_existing(event, snapshot_candidates)
        decision = persist_existing_plan_decision(
            session,
            event_uid=row.event_uid,
            evaluation=evaluation,
            rule_version=rule_version,
            input_fingerprint=_input_fingerprint(
                row.event_fingerprint, snapshot_candidates
            ),
            uid_factory=uid_factory,
        )
        statuses.append(decision.status)

    for plan in session.query(BuybackPlan).filter(BuybackPlan.code == code).all():
        rebuild_plan_projection(
            session,
            plan_id=plan.buyback_plan_id,
            aggregation_rule_version=aggregation_rule_version,
        )
    session.flush()
    return RelinkResult(
        evaluated=len(statuses),
        linked=statuses.count("LINKED"),
        unresolved=statuses.count("UNRESOLVED"),
        ambiguous=statuses.count("AMBIGUOUS"),
        skipped_linked=skipped_linked,
    )
