from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from buyback_analysis.models.base import Base
from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import BuybackEventLinkDecision
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.usecase.build_plan_link_candidates import (
    build_plan_link_candidates,
)


def _event(uid, event_type, payload, *, event_date, active=True, title=None):
    return BuybackEvent(
        event_uid=uid,
        version_id="version-1",
        url=f"https://example.test/{uid}.pdf",
        document_title=title,
        code="1234",
        event_type=event_type,
        event_fingerprint=f"fingerprint-{uid}",
        event_date=event_date,
        resolution_date="2026-01-01" if event_type == "new_plan" else None,
        source_quote="根拠原文",
        payload=payload,
        is_active=active,
    )


def _decision(decision_id, event_uid, plan_id, *, status="LINKED", current=True):
    return BuybackEventLinkDecision(
        decision_id=decision_id,
        event_uid=event_uid,
        status=status,
        decision_kind="NORMAL",
        linked_plan_id=plan_id if status == "LINKED" else None,
        candidates=[{"plan_id": plan_id}],
        reason_codes=["TEST_EVIDENCE"],
        rule_version="test:v1",
        input_fingerprint=f"input-{decision_id}",
        is_current=current,
    )


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_candidate_is_derived_from_current_linked_new_plan():
    session = _session()
    session.add(BuybackPlan(buyback_plan_id="plan-1", code="1234", origin_event_uid="event-new", lifecycle_status="ACTIVE"))
    session.add(
        _event(
            "event-new",
            "new_plan",
            {
                "buyback_shares": 1000,
                "buyback_amount_yen": 5_000_000,
                "start_date": "2026-01-02",
                "end_date": "2026-12-31",
                "buyback_method": "market_purchase",
            },
            event_date="2026-01-01",
            title="自己株式取得に係る事項の決定",
        )
    )
    session.add(_decision("decision-1", "event-new", "plan-1"))
    session.commit()

    candidates = build_plan_link_candidates(session, code="1234")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.plan_id == "plan-1"
    assert candidate.resolution_date == "2026-01-01"
    assert candidate.current_shares == 1000
    assert candidate.current_amount_yen == 5_000_000
    assert candidate.start_date == "2026-01-02"
    assert candidate.end_date == "2026-12-31"
    assert candidate.current_method == "market_purchase"
    assert candidate.origin_document_title == "自己株式取得に係る事項の決定"


def test_linked_amendments_are_applied_in_effective_date_order():
    session = _session()
    session.add(BuybackPlan(buyback_plan_id="plan-1", code="1234", origin_event_uid="event-new", lifecycle_status="ACTIVE"))
    session.add(
        _event(
            "event-new",
            "new_plan",
            {"buyback_shares": 1000, "buyback_amount_yen": 5_000_000},
            event_date="2026-01-01",
        )
    )
    session.add(
        _event(
            "amend-later",
            "amendment",
            {"changed_buyback_amount_yen": 7_000_000},
            event_date="2026-03-01",
        )
    )
    session.add(
        _event(
            "amend-earlier",
            "amendment",
            {
                "changed_buyback_shares": 1200,
                "changed_buyback_amount_yen": 6_000_000,
            },
            event_date="2026-02-01",
        )
    )
    session.add_all(
        [
            _decision("decision-new", "event-new", "plan-1"),
            _decision("decision-later", "amend-later", "plan-1"),
            _decision("decision-earlier", "amend-earlier", "plan-1"),
        ]
    )
    session.commit()

    candidate = build_plan_link_candidates(session, code="1234")[0]

    assert candidate.current_shares == 1200
    assert candidate.current_amount_yen == 7_000_000


def test_unresolved_inactive_and_noncurrent_events_do_not_change_candidate():
    session = _session()
    session.add(BuybackPlan(buyback_plan_id="plan-1", code="1234", origin_event_uid="event-new", lifecycle_status="ACTIVE"))
    session.add(_event("event-new", "new_plan", {"buyback_shares": 1000}, event_date="2026-01-01"))
    session.add(_event("amend-unresolved", "amendment", {"changed_buyback_shares": 2000}, event_date="2026-02-01"))
    session.add(_event("amend-inactive", "amendment", {"changed_buyback_shares": 3000}, event_date="2026-03-01", active=False))
    session.add(_event("amend-old", "amendment", {"changed_buyback_shares": 4000}, event_date="2026-04-01"))
    session.add_all(
        [
            _decision("decision-new", "event-new", "plan-1"),
            _decision("decision-unresolved", "amend-unresolved", "plan-1", status="UNRESOLVED"),
            _decision("decision-inactive", "amend-inactive", "plan-1"),
            _decision("decision-old", "amend-old", "plan-1", current=False),
        ]
    )
    session.commit()

    candidate = build_plan_link_candidates(session, code="1234")[0]

    assert candidate.current_shares == 1000


def test_plan_without_current_linked_origin_is_not_a_candidate():
    session = _session()
    session.add_all(
        [
            BuybackPlan(buyback_plan_id="plan-missing", code="1234", origin_event_uid="missing", lifecycle_status="ACTIVE"),
            BuybackPlan(buyback_plan_id="plan-invalid", code="1234", origin_event_uid="invalid-origin", lifecycle_status="INVALIDATED_ORIGIN"),
            BuybackPlan(buyback_plan_id="plan-other", code="9999", origin_event_uid="other-origin", lifecycle_status="ACTIVE"),
        ]
    )
    session.commit()

    assert build_plan_link_candidates(session, code="1234") == []
