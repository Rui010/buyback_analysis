from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from buyback_analysis.models.base import Base
from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import BuybackEventLinkDecision
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.models.buyback_plan_projection import BuybackPlanProjection
from buyback_analysis.usecase.rebuild_plan_projection import rebuild_plan_projection


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _event(uid, event_type, payload, event_date):
    return BuybackEvent(
        event_uid=uid,
        version_id="version-1",
        url=f"https://example.test/{uid}.pdf",
        code="1234",
        event_type=event_type,
        event_fingerprint=f"fingerprint-{uid}",
        event_date=event_date,
        resolution_date="2026-01-01" if event_type == "new_plan" else None,
        source_quote="根拠原文",
        payload=payload,
        is_active=True,
    )


def _linked(decision_id, event_uid, plan_id="plan-1"):
    return BuybackEventLinkDecision(
        decision_id=decision_id,
        event_uid=event_uid,
        status="LINKED",
        decision_kind="NORMAL",
        linked_plan_id=plan_id,
        candidates=[{"plan_id": plan_id}],
        reason_codes=["TEST_EVIDENCE"],
        rule_version="link:v1",
        input_fingerprint=f"input-{decision_id}",
        is_current=True,
    )


def _seed_plan(session):
    session.add(
        BuybackPlan(
            buyback_plan_id="plan-1",
            code="1234",
            origin_event_uid="new-plan",
            lifecycle_status="ACTIVE",
        )
    )
    events = [
        _event(
            "new-plan",
            "new_plan",
            {
                "buyback_shares": 1000,
                "buyback_amount_yen": 5_000_000,
                "start_date": "2026-01-02",
                "end_date": "2026-12-31",
                "buyback_method": "market_purchase",
            },
            "2026-01-01",
        ),
        _event(
            "amendment",
            "amendment",
            {
                "changed_buyback_shares": 1200,
                "changed_buyback_amount_yen": 6_000_000,
                "changed_end_date": "2027-03-31",
            },
            "2026-02-01",
        ),
        _event(
            "progress-early",
            "progress",
            {
                "cumulative_shares_acquired": 300,
                "cumulative_amount_spent_yen": 1_500_000,
            },
            "2026-03-01",
        ),
        _event(
            "progress-late",
            "progress",
            {
                "cumulative_shares_acquired": 700,
                "cumulative_amount_spent_yen": 3_500_000,
            },
            "2026-04-01",
        ),
        _event(
            "completion",
            "completion",
            {"shares_acquired": 900, "amount_spent_yen": 4_500_000},
            "2027-04-01",
        ),
    ]
    session.add_all(events)
    session.add_all(
        [_linked(f"decision-{event.event_uid}", event.event_uid) for event in events]
    )
    session.commit()


def test_projection_rebuilds_original_current_progress_and_completion_values():
    session = _session()
    _seed_plan(session)

    projection = rebuild_plan_projection(
        session, plan_id="plan-1", aggregation_rule_version="projection:v1"
    )

    assert projection.original_shares == 1000
    assert projection.original_amount_yen == 5_000_000
    assert projection.current_shares == 1200
    assert projection.current_amount_yen == 6_000_000
    assert projection.current_end_date == "2027-03-31"
    assert projection.cumulative_shares_acquired == 700
    assert projection.cumulative_amount_spent_yen == 3_500_000
    assert projection.completion_shares_acquired == 900
    assert projection.completion_amount_spent_yen == 4_500_000
    assert projection.is_publishable is True
    assert projection.lifecycle_status == "ACTIVE"
    assert projection.plan_status == "completed"


def test_rebuild_is_idempotent_and_updates_existing_projection():
    session = _session()
    _seed_plan(session)
    first = rebuild_plan_projection(
        session, plan_id="plan-1", aggregation_rule_version="projection:v1"
    )
    first_fingerprint = first.input_fingerprint
    session.commit()
    progress = session.get(BuybackEvent, "progress-late")
    progress.payload = {
        "cumulative_shares_acquired": 800,
        "cumulative_amount_spent_yen": 4_000_000,
    }
    progress.event_fingerprint = "fingerprint-progress-late-v2"
    session.commit()

    second = rebuild_plan_projection(
        session, plan_id="plan-1", aggregation_rule_version="projection:v1"
    )

    assert second.buyback_plan_id == first.buyback_plan_id
    assert session.query(BuybackPlanProjection).count() == 1
    assert second.cumulative_shares_acquired == 800
    assert second.input_fingerprint != first_fingerprint


def test_invalidated_origin_projection_is_not_publishable():
    session = _session()
    _seed_plan(session)
    session.get(BuybackPlan, "plan-1").lifecycle_status = "INVALIDATED_ORIGIN"
    session.commit()

    projection = rebuild_plan_projection(
        session, plan_id="plan-1", aggregation_rule_version="projection:v1"
    )

    assert projection.lifecycle_status == "INVALIDATED_ORIGIN"
    assert projection.is_publishable is False


def test_missing_current_linked_origin_is_not_publishable():
    session = _session()
    _seed_plan(session)
    origin_decision = (
        session.query(BuybackEventLinkDecision)
        .filter(BuybackEventLinkDecision.event_uid == "new-plan")
        .one()
    )
    origin_decision.is_current = False
    session.commit()

    projection = rebuild_plan_projection(
        session, plan_id="plan-1", aggregation_rule_version="projection:v1"
    )

    assert projection.is_publishable is False
    assert projection.original_shares is None


def test_plan_status_moves_from_planned_to_in_progress():
    session = _session()
    session.add(
        BuybackPlan(
            buyback_plan_id="plan-1",
            code="1234",
            origin_event_uid="new-plan",
            lifecycle_status="ACTIVE",
        )
    )
    origin = _event(
        "new-plan", "new_plan", {"buyback_shares": 1000}, "2026-01-01"
    )
    session.add(origin)
    session.add(_linked("origin-decision", "new-plan"))
    session.commit()

    planned = rebuild_plan_projection(
        session, plan_id="plan-1", aggregation_rule_version="projection:v1"
    )
    assert planned.plan_status == "planned"
    session.commit()

    progress = _event(
        "progress", "progress", {"cumulative_shares_acquired": 100}, "2026-02-01"
    )
    session.add(progress)
    session.add(_linked("progress-decision", "progress"))
    session.commit()

    in_progress = rebuild_plan_projection(
        session, plan_id="plan-1", aggregation_rule_version="projection:v1"
    )
    assert in_progress.plan_status == "in_progress"
