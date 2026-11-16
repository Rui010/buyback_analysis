"""Rebuild a plan projection from current active LINKED events only."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import BuybackEventLinkDecision
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.models.buyback_plan_projection import BuybackPlanProjection


def _linked_events(session: Session, plan_id: str) -> list[BuybackEvent]:
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


def _event_order(event: BuybackEvent):
    return (event.event_date or event.resolution_date or "", event.event_uid)


def _fingerprint(plan: BuybackPlan, events, rule_version: str) -> str:
    value = {
        "plan_id": plan.buyback_plan_id,
        "lifecycle_status": plan.lifecycle_status,
        "rule_version": rule_version,
        "events": sorted(
            (event.event_uid, event.event_fingerprint) for event in events
        ),
    }
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def rebuild_plan_projection(
    session: Session,
    *,
    plan_id: str,
    aggregation_rule_version: str,
) -> BuybackPlanProjection:
    """Upsert the derived projection and flush without committing."""

    plan = session.get(BuybackPlan, plan_id)
    if plan is None:
        raise ValueError("plan not found")
    events = _linked_events(session, plan_id)
    origin = next(
        (
            event
            for event in events
            if event.event_uid == plan.origin_event_uid
            and event.event_type == "new_plan"
        ),
        None,
    )

    values = {
        "original_shares": None,
        "original_amount_yen": None,
        "original_start_date": None,
        "original_end_date": None,
        "original_method": None,
        "current_shares": None,
        "current_amount_yen": None,
        "current_start_date": None,
        "current_end_date": None,
        "current_method": None,
        "cumulative_shares_acquired": None,
        "cumulative_amount_spent_yen": None,
        "completion_shares_acquired": None,
        "completion_amount_spent_yen": None,
    }
    if origin is not None:
        payload = origin.payload
        values.update(
            original_shares=payload.get("buyback_shares"),
            original_amount_yen=payload.get("buyback_amount_yen"),
            original_start_date=payload.get("start_date"),
            original_end_date=payload.get("end_date"),
            original_method=payload.get("buyback_method"),
            current_shares=payload.get("buyback_shares"),
            current_amount_yen=payload.get("buyback_amount_yen"),
            current_start_date=payload.get("start_date"),
            current_end_date=payload.get("end_date"),
            current_method=payload.get("buyback_method"),
        )
        for amendment in sorted(
            (event for event in events if event.event_type == "amendment"),
            key=_event_order,
        ):
            changed = amendment.payload
            mapping = {
                "changed_buyback_shares": "current_shares",
                "changed_buyback_amount_yen": "current_amount_yen",
                "changed_start_date": "current_start_date",
                "changed_end_date": "current_end_date",
                "changed_buyback_method": "current_method",
            }
            for source, target in mapping.items():
                if changed.get(source) is not None:
                    values[target] = changed[source]

        for progress in sorted(
            (event for event in events if event.event_type == "progress"),
            key=_event_order,
        ):
            if progress.payload.get("cumulative_shares_acquired") is not None:
                values["cumulative_shares_acquired"] = progress.payload[
                    "cumulative_shares_acquired"
                ]
            if progress.payload.get("cumulative_amount_spent_yen") is not None:
                values["cumulative_amount_spent_yen"] = progress.payload[
                    "cumulative_amount_spent_yen"
                ]

        completions = sorted(
            (event for event in events if event.event_type == "completion"),
            key=_event_order,
        )
        if completions:
            completion = completions[-1].payload
            values["completion_shares_acquired"] = completion.get(
                "shares_acquired"
            )
            values["completion_amount_spent_yen"] = completion.get(
                "amount_spent_yen"
            )

    has_completion = origin is not None and any(
        event.event_type == "completion" for event in events
    )
    has_progress = origin is not None and any(
        event.event_type == "progress"
        or (
            event.event_type == "execution_notice"
            and event.payload.get("subtype") == "result"
        )
        for event in events
    )
    plan_status = (
        "completed"
        if has_completion
        else "in_progress"
        if has_progress
        else "planned"
    )

    projection = session.get(BuybackPlanProjection, plan_id)
    if projection is None:
        projection = BuybackPlanProjection(buyback_plan_id=plan_id)
        session.add(projection)
    for name, value in values.items():
        setattr(projection, name, value)
    projection.lifecycle_status = plan.lifecycle_status
    projection.plan_status = plan_status
    projection.is_publishable = bool(
        plan.lifecycle_status == "ACTIVE" and origin is not None
    )
    projection.input_fingerprint = _fingerprint(
        plan, events, aggregation_rule_version
    )
    projection.aggregation_rule_version = aggregation_rule_version
    projection.calculated_at = datetime.now(timezone.utc)
    session.flush()
    return projection
