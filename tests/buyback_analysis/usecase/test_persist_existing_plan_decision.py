from itertools import count

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from buyback_analysis.models.base import Base
from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import BuybackEventLinkDecision
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.usecase.link_existing_plan_events import ExistingPlanEvaluation
from buyback_analysis.usecase.persist_existing_plan_decision import (
    persist_existing_plan_decision,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            BuybackEvent(
                event_uid="event-1",
                version_id="version-1",
                url="https://example.test/progress.pdf",
                code="1234",
                event_type="progress",
                event_fingerprint="event-fingerprint",
                source_quote="取得状況",
                payload={"cumulative_shares_acquired": 100},
                is_active=True,
            )
        )
        db.add(
            BuybackPlan(
                buyback_plan_id="plan-1",
                code="1234",
                origin_event_uid="origin-1",
                lifecycle_status="ACTIVE",
            )
        )
        db.commit()
        yield db


def _ids(prefix="decision"):
    sequence = count(1)
    return lambda: f"{prefix}-{next(sequence)}"


def _persist(session, evaluation, fingerprint="input-1", uid_factory=None):
    return persist_existing_plan_decision(
        session,
        event_uid="event-1",
        evaluation=evaluation,
        rule_version="existing-plan:v1",
        input_fingerprint=fingerprint,
        uid_factory=uid_factory or _ids(),
    )


def test_linked_evaluation_is_saved_with_candidate_and_reason(session):
    evaluation = ExistingPlanEvaluation(
        "LINKED", "plan-1", ("plan-1",), ("EXPLICIT_RESOLUTION_REFERENCE",)
    )

    decision = _persist(session, evaluation)

    assert decision.status == "LINKED"
    assert decision.linked_plan_id == "plan-1"
    assert decision.candidates == [
        {
            "plan_id": "plan-1",
            "reason_codes": ["EXPLICIT_RESOLUTION_REFERENCE"],
        }
    ]
    assert decision.reason_codes == ["EXPLICIT_RESOLUTION_REFERENCE"]
    assert decision.is_current is True


def test_unresolved_evaluation_preserves_considered_candidate(session):
    evaluation = ExistingPlanEvaluation(
        "UNRESOLVED", None, ("plan-1",), ("CUMULATIVE_VALUE_CONFLICT",)
    )

    decision = _persist(session, evaluation)

    assert decision.linked_plan_id is None
    assert decision.candidates[0]["plan_id"] == "plan-1"
    assert decision.candidates[0]["reason_codes"] == ["CUMULATIVE_VALUE_CONFLICT"]


def test_same_rule_and_input_reuses_existing_decision(session):
    evaluation = ExistingPlanEvaluation(
        "LINKED", "plan-1", ("plan-1",), ("REPORTING_PERIOD_WITHIN_PLAN",)
    )
    first = _persist(session, evaluation, uid_factory=_ids("first"))
    session.commit()

    second = _persist(session, evaluation, uid_factory=_ids("unused"))

    assert second.decision_id == first.decision_id
    assert session.query(BuybackEventLinkDecision).count() == 1


def test_new_input_appends_and_supersedes_current_decision(session):
    linked = ExistingPlanEvaluation(
        "LINKED", "plan-1", ("plan-1",), ("REPORTING_PERIOD_WITHIN_PLAN",)
    )
    unresolved = ExistingPlanEvaluation(
        "UNRESOLVED", None, ("plan-1",), ("CUMULATIVE_VALUE_CONFLICT",)
    )
    first = _persist(session, linked, uid_factory=_ids("first"))
    session.commit()

    second = _persist(
        session, unresolved, fingerprint="input-2", uid_factory=_ids("second")
    )

    assert first.is_current is False
    assert second.is_current is True
    assert second.supersedes_decision_id == first.decision_id


def test_existing_normal_decision_is_restored_after_expiration(session):
    evaluation = ExistingPlanEvaluation(
        "LINKED", "plan-1", ("plan-1",), ("REPORTING_PERIOD_WITHIN_PLAN",)
    )
    normal = _persist(session, evaluation, uid_factory=_ids("normal"))
    normal.is_current = False
    expiration = BuybackEventLinkDecision(
        decision_id="expiration-1",
        event_uid="event-1",
        status="UNRESOLVED",
        decision_kind="EXPIRATION",
        linked_plan_id=None,
        candidates=[],
        reason_codes=["EXPIRED_BY_CONTENT_CHANGE"],
        rule_version="expire:v1",
        input_fingerprint=None,
        supersedes_decision_id=normal.decision_id,
        is_current=True,
    )
    session.add(expiration)
    session.commit()

    restored = _persist(session, evaluation, uid_factory=_ids("unused"))

    assert restored.decision_id == normal.decision_id
    assert restored.is_current is True
    assert expiration.is_current is False


def test_linked_decision_rejects_missing_or_inactive_plan(session):
    session.get(BuybackPlan, "plan-1").lifecycle_status = "INVALIDATED_ORIGIN"
    session.commit()
    evaluation = ExistingPlanEvaluation(
        "LINKED", "plan-1", ("plan-1",), ("EXPLICIT_RESOLUTION_REFERENCE",)
    )

    with pytest.raises(ValueError, match="active linked plan not found"):
        _persist(session, evaluation)
