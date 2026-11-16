"""Build current plan-link candidates from current LINKED events."""

from __future__ import annotations

from sqlalchemy.orm import Session

from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import BuybackEventLinkDecision
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.usecase.link_existing_plan_events import PlanLinkCandidate


def _current_linked_events(
    session: Session, plan_id: str
) -> list[BuybackEvent]:
    return (
        session.query(BuybackEvent)
        .join(
            BuybackEventLinkDecision,
            BuybackEventLinkDecision.event_uid == BuybackEvent.event_uid,
        )
        .filter(
            BuybackEventLinkDecision.linked_plan_id == plan_id,
            BuybackEventLinkDecision.status == "LINKED",
            BuybackEventLinkDecision.is_current.is_(True),
            BuybackEvent.is_active.is_(True),
        )
        .all()
    )


def build_plan_link_candidates(
    session: Session, *, code: str
) -> list[PlanLinkCandidate]:
    """Derive effective plan terms; projections are not required as input."""

    plans = (
        session.query(BuybackPlan)
        .filter(
            BuybackPlan.code == code,
            BuybackPlan.lifecycle_status == "ACTIVE",
        )
        .order_by(BuybackPlan.buyback_plan_id)
        .all()
    )
    candidates: list[PlanLinkCandidate] = []
    for plan in plans:
        events = _current_linked_events(session, plan.buyback_plan_id)
        origin = next(
            (
                event
                for event in events
                if event.event_uid == plan.origin_event_uid
                and event.event_type == "new_plan"
            ),
            None,
        )
        if origin is None:
            continue

        payload = origin.payload
        current_shares = payload.get("buyback_shares")
        current_amount = payload.get("buyback_amount_yen")
        start_date = payload.get("start_date")
        end_date = payload.get("end_date")
        current_method = payload.get("buyback_method")

        amendments = sorted(
            (event for event in events if event.event_type == "amendment"),
            key=lambda event: (
                event.event_date or event.resolution_date or "",
                event.event_uid,
            ),
        )
        for amendment in amendments:
            changed = amendment.payload
            if changed.get("changed_buyback_shares") is not None:
                current_shares = changed["changed_buyback_shares"]
            if changed.get("changed_buyback_amount_yen") is not None:
                current_amount = changed["changed_buyback_amount_yen"]
            if changed.get("changed_start_date") is not None:
                start_date = changed["changed_start_date"]
            if changed.get("changed_end_date") is not None:
                end_date = changed["changed_end_date"]
            if changed.get("changed_buyback_method") is not None:
                current_method = changed["changed_buyback_method"]

        candidates.append(
            PlanLinkCandidate(
                plan_id=plan.buyback_plan_id,
                resolution_date=origin.resolution_date,
                start_date=start_date,
                end_date=end_date,
                current_shares=current_shares,
                current_amount_yen=current_amount,
                current_method=current_method,
                origin_document_title=origin.document_title,
                lifecycle_status=plan.lifecycle_status,
                origin_document_date=origin.disclosure_datetime,
                original_shares=payload.get("buyback_shares"),
                original_amount_yen=payload.get("buyback_amount_yen"),
                original_start_date=payload.get("start_date"),
                original_end_date=payload.get("end_date"),
            )
        )
    return candidates
