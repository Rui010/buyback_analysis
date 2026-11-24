"""Rebuild announcement_plan_status from publishable plan projections."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from buyback_analysis.models.announcement_plan_status import AnnouncementPlanStatus
from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import BuybackEventLinkDecision
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.models.buyback_plan_projection import BuybackPlanProjection


def _progress_rate(cumulative, limit):
    if cumulative is None or not limit:
        return None
    return cumulative / limit


def _latest_progress_dates(session: Session) -> dict[str, str]:
    rows = (
        session.query(
            BuybackEventLinkDecision.linked_plan_id,
            func.max(BuybackEvent.event_date),
        )
        .join(
            BuybackEvent,
            BuybackEvent.event_uid == BuybackEventLinkDecision.event_uid,
        )
        .filter(
            BuybackEventLinkDecision.status == "LINKED",
            BuybackEventLinkDecision.is_current.is_(True),
            BuybackEvent.is_active.is_(True),
            BuybackEvent.event_type == "progress",
            BuybackEvent.event_date.isnot(None),
        )
        .group_by(BuybackEventLinkDecision.linked_plan_id)
        .all()
    )
    return {plan_id: latest for plan_id, latest in rows}


def rebuild_announcement_plan_status(session: Session) -> int:
    """Replace all rows and flush without committing. Returns the row count."""

    sources = (
        session.query(BuybackPlan, BuybackPlanProjection, BuybackEvent.url)
        .join(
            BuybackPlanProjection,
            BuybackPlanProjection.buyback_plan_id == BuybackPlan.buyback_plan_id,
        )
        .join(BuybackEvent, BuybackEvent.event_uid == BuybackPlan.origin_event_uid)
        .filter(BuybackPlanProjection.is_publishable.is_(True))
        .all()
    )
    latest_dates = _latest_progress_dates(session)

    # 削除済み行と同じ主キーで追加するため、ID mapを同期させて消しておく
    session.query(AnnouncementPlanStatus).delete(synchronize_session="fetch")
    for plan, projection, url in sources:
        session.add(
            AnnouncementPlanStatus(
                buyback_plan_id=plan.buyback_plan_id,
                announcement_url=url,
                code=plan.code,
                plan_status=projection.plan_status,
                current_shares=projection.current_shares,
                current_amount_yen=projection.current_amount_yen,
                current_start_date=projection.current_start_date,
                current_end_date=projection.current_end_date,
                cumulative_shares_acquired=projection.cumulative_shares_acquired,
                cumulative_amount_spent_yen=projection.cumulative_amount_spent_yen,
                completion_shares_acquired=projection.completion_shares_acquired,
                completion_amount_spent_yen=projection.completion_amount_spent_yen,
                progress_rate_amount=_progress_rate(
                    projection.cumulative_amount_spent_yen,
                    projection.current_amount_yen,
                ),
                progress_rate_shares=_progress_rate(
                    projection.cumulative_shares_acquired,
                    projection.current_shares,
                ),
                latest_progress_date=latest_dates.get(plan.buyback_plan_id),
                aggregation_rule_version=projection.aggregation_rule_version,
                calculated_at=projection.calculated_at,
            )
        )
    session.flush()
    return len(sources)
