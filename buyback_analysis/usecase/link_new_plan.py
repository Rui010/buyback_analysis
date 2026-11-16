"""Evidence-based linking and idempotent plan creation for new-plan events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable, Literal, Sequence

from sqlalchemy.orm import Session

from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import BuybackEventLinkDecision
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.usecase.event_schemas import NewPlanEvent


LinkStatus = Literal["LINKED", "UNRESOLVED", "AMBIGUOUS"]


@dataclass(frozen=True)
class NewPlanEvaluation:
    status: LinkStatus
    reason_codes: tuple[str, ...]
    candidate_plan_ids: tuple[str, ...] = ()


def evaluate_new_plan(
    event: NewPlanEvent,
    *,
    candidate_plan_ids: Sequence[str] = (),
) -> NewPlanEvaluation:
    """Evaluate explicit evidence; no LLM confidence participates."""

    if event.event_type.value != "new_plan":
        raise ValueError("event must be new_plan")

    candidates = tuple(sorted(set(candidate_plan_ids)))
    if len(candidates) >= 2:
        return NewPlanEvaluation(
            "AMBIGUOUS", ("MULTIPLE_ORIGIN_CANDIDATES",), candidates
        )
    if len(candidates) == 1:
        return NewPlanEvaluation(
            "UNRESOLVED", ("CONFLICTING_ORIGIN_CANDIDATE",), candidates
        )

    reasons: list[str] = []
    if event.payload.company_own_transaction is not True:
        reasons.append("COMPANY_OWN_TRANSACTION_UNCONFIRMED")
    if event.payload.independent_resolution is not True:
        reasons.append("INDEPENDENT_RESOLUTION_UNCONFIRMED")
    if not event.resolution_date:
        reasons.append("MISSING_RESOLUTION_DATE")
    has_frame = (
        event.payload.buyback_shares is not None
        or event.payload.buyback_amount_yen is not None
    )
    has_period = bool(event.payload.start_date and event.payload.end_date)
    if not (has_frame or has_period):
        reasons.append("MISSING_IDENTIFYING_FRAME_OR_PERIOD")
    if reasons:
        return NewPlanEvaluation("UNRESOLVED", tuple(reasons))
    return NewPlanEvaluation("LINKED", ("NEW_PLAN_EVIDENCE_COMPLETE",))


def _event_from_row(row: BuybackEvent) -> NewPlanEvent:
    return NewPlanEvent.model_validate(
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
    )


def decide_new_plan(
    session: Session,
    *,
    event_uid: str,
    candidate_plan_ids: Sequence[str],
    rule_version: str,
    input_fingerprint: str,
    uid_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> BuybackEventLinkDecision:
    """Persist or reuse one normal decision without committing the session."""

    event_row = session.get(BuybackEvent, event_uid)
    if event_row is None or not event_row.is_active:
        raise ValueError("active event not found")
    if event_row.event_type != "new_plan":
        raise ValueError("event must be new_plan")

    existing = (
        session.query(BuybackEventLinkDecision)
        .filter(
            BuybackEventLinkDecision.event_uid == event_uid,
            BuybackEventLinkDecision.decision_kind == "NORMAL",
            BuybackEventLinkDecision.rule_version == rule_version,
            BuybackEventLinkDecision.input_fingerprint == input_fingerprint,
        )
        .one_or_none()
    )
    if existing is not None:
        if not existing.is_current:
            current = (
                session.query(BuybackEventLinkDecision)
                .filter(
                    BuybackEventLinkDecision.event_uid == event_uid,
                    BuybackEventLinkDecision.is_current.is_(True),
                )
                .one_or_none()
            )
            if current is not None:
                current.is_current = False
                session.flush()
            existing.is_current = True
        if existing.linked_plan_id:
            plan = session.get(BuybackPlan, existing.linked_plan_id)
            if plan is not None:
                plan.lifecycle_status = "ACTIVE"
        session.flush()
        return existing

    evaluation = evaluate_new_plan(
        _event_from_row(event_row), candidate_plan_ids=candidate_plan_ids
    )
    linked_plan_id = None
    if evaluation.status == "LINKED":
        plan = (
            session.query(BuybackPlan)
            .filter(BuybackPlan.origin_event_uid == event_uid)
            .one_or_none()
        )
        if plan is None:
            plan = BuybackPlan(
                buyback_plan_id=uid_factory(),
                code=event_row.code,
                origin_event_uid=event_uid,
                lifecycle_status="ACTIVE",
            )
            session.add(plan)
        else:
            plan.lifecycle_status = "ACTIVE"
        linked_plan_id = plan.buyback_plan_id

    current = (
        session.query(BuybackEventLinkDecision)
        .filter(
            BuybackEventLinkDecision.event_uid == event_uid,
            BuybackEventLinkDecision.is_current.is_(True),
        )
        .one_or_none()
    )
    supersedes_id = current.decision_id if current is not None else None
    if current is not None:
        current.is_current = False
        session.flush()

    decision = BuybackEventLinkDecision(
        decision_id=uid_factory(),
        event_uid=event_uid,
        status=evaluation.status,
        decision_kind="NORMAL",
        linked_plan_id=linked_plan_id,
        candidates=[{"plan_id": plan_id} for plan_id in evaluation.candidate_plan_ids],
        reason_codes=list(evaluation.reason_codes),
        rule_version=rule_version,
        input_fingerprint=input_fingerprint,
        supersedes_decision_id=supersedes_id,
        is_current=True,
    )
    session.add(decision)
    session.flush()
    return decision
