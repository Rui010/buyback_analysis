"""Append or reuse normal link decisions for existing-plan events."""

from __future__ import annotations

import uuid
from typing import Callable

from sqlalchemy.orm import Session

from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import BuybackEventLinkDecision
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.usecase.link_existing_plan_events import ExistingPlanEvaluation


def persist_existing_plan_decision(
    session: Session,
    *,
    event_uid: str,
    evaluation: ExistingPlanEvaluation,
    rule_version: str,
    input_fingerprint: str,
    uid_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> BuybackEventLinkDecision:
    """Persist one evaluated decision, leaving commit/rollback to the caller."""

    event = session.get(BuybackEvent, event_uid)
    if event is None or not event.is_active:
        raise ValueError("active event not found")

    if evaluation.status == "LINKED":
        plan = session.get(BuybackPlan, evaluation.linked_plan_id)
        if (
            plan is None
            or plan.lifecycle_status != "ACTIVE"
            or plan.code != event.code
        ):
            raise ValueError("active linked plan not found")
    elif evaluation.linked_plan_id is not None:
        raise ValueError("only LINKED evaluation may have linked_plan_id")

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
        session.flush()
        return existing

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

    reason_codes = list(evaluation.reason_codes)
    decision = BuybackEventLinkDecision(
        decision_id=uid_factory(),
        event_uid=event_uid,
        status=evaluation.status,
        decision_kind="NORMAL",
        linked_plan_id=evaluation.linked_plan_id,
        candidates=[
            {"plan_id": plan_id, "reason_codes": reason_codes}
            for plan_id in evaluation.candidate_plan_ids
        ],
        reason_codes=reason_codes,
        rule_version=rule_version,
        input_fingerprint=input_fingerprint,
        supersedes_decision_id=supersedes_id,
        is_current=True,
    )
    session.add(decision)
    session.flush()
    return decision
