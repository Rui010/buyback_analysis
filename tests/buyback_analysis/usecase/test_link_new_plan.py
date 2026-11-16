from itertools import count

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from buyback_analysis.models.base import Base
from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import BuybackEventLinkDecision
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.usecase.adopt_buyback_events import adopt_buyback_events
from buyback_analysis.usecase.event_schemas import BuybackEventExtraction
from buyback_analysis.usecase.link_new_plan import decide_new_plan, evaluate_new_plan


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _event(**payload_overrides):
    payload = {
        "company_own_transaction": True,
        "independent_resolution": True,
        "buyback_shares": 1000,
        "buyback_amount_yen": 5_000_000,
        "start_date": "2026-01-02",
        "end_date": "2026-12-31",
        **payload_overrides,
    }
    return BuybackEventExtraction.model_validate(
        {
            "events": [
                {
                    "event_type": "new_plan",
                    "resolution_date": "2026-01-01",
                    "source_quote": "自己株式取得を決議した。",
                    "payload": payload,
                }
            ]
        }
    ).events[0]


def _ids(prefix):
    sequence = count(1)
    return lambda: f"{prefix}-{next(sequence)}"


def _store_event(session, event=None):
    event = event or _event()
    adopt_buyback_events(
        session,
        version_id="version-1",
        url="https://example.test/new-plan.pdf",
        code="1234",
        events=[event],
        uid_factory=lambda: "event-1",
    )
    session.commit()
    return session.get(BuybackEvent, "event-1")


def test_new_plan_is_linkable_only_with_all_required_evidence():
    result = evaluate_new_plan(_event())

    assert result.status == "LINKED"
    assert result.reason_codes == ("NEW_PLAN_EVIDENCE_COMPLETE",)


@pytest.mark.parametrize(
    ("event", "reason"),
    [
        (_event(company_own_transaction=None), "COMPANY_OWN_TRANSACTION_UNCONFIRMED"),
        (_event(independent_resolution=None), "INDEPENDENT_RESOLUTION_UNCONFIRMED"),
        (
            BuybackEventExtraction.model_validate(
                {
                    "events": [
                        {
                            "event_type": "new_plan",
                            "source_quote": "取得を検討する。",
                            "payload": {
                                "company_own_transaction": True,
                                "independent_resolution": True,
                                "buyback_shares": 1000,
                            },
                        }
                    ]
                }
            ).events[0],
            "MISSING_RESOLUTION_DATE",
        ),
        (
            _event(
                buyback_shares=None,
                buyback_amount_yen=None,
                start_date=None,
                end_date=None,
            ),
            "MISSING_IDENTIFYING_FRAME_OR_PERIOD",
        ),
    ],
)
def test_missing_new_plan_evidence_is_unresolved(event, reason):
    result = evaluate_new_plan(event)

    assert result.status == "UNRESOLVED"
    assert reason in result.reason_codes


def test_one_other_origin_candidate_is_unresolved_and_two_are_ambiguous():
    one = evaluate_new_plan(_event(), candidate_plan_ids=["plan-a"])
    two = evaluate_new_plan(_event(), candidate_plan_ids=["plan-a", "plan-b"])

    assert one.status == "UNRESOLVED"
    assert one.reason_codes == ("CONFLICTING_ORIGIN_CANDIDATE",)
    assert two.status == "AMBIGUOUS"
    assert two.reason_codes == ("MULTIPLE_ORIGIN_CANDIDATES",)


def test_linked_new_plan_creates_plan_and_current_decision(session):
    _store_event(session)

    result = decide_new_plan(
        session,
        event_uid="event-1",
        candidate_plan_ids=[],
        rule_version="new-plan:v1",
        input_fingerprint="input-1",
        uid_factory=_ids("generated"),
    )

    plan = session.query(BuybackPlan).one()
    decision = session.query(BuybackEventLinkDecision).one()
    assert result.status == "LINKED"
    assert plan.origin_event_uid == "event-1"
    assert plan.lifecycle_status == "ACTIVE"
    assert decision.linked_plan_id == plan.buyback_plan_id
    assert decision.is_current is True


def test_same_origin_and_same_input_reuses_plan_and_decision(session):
    _store_event(session)
    first = decide_new_plan(
        session,
        event_uid="event-1",
        candidate_plan_ids=[],
        rule_version="new-plan:v1",
        input_fingerprint="input-1",
        uid_factory=_ids("first"),
    )
    session.commit()

    second = decide_new_plan(
        session,
        event_uid="event-1",
        candidate_plan_ids=[],
        rule_version="new-plan:v1",
        input_fingerprint="input-1",
        uid_factory=_ids("must-not-be-used"),
    )

    assert second.decision_id == first.decision_id
    assert second.linked_plan_id == first.linked_plan_id
    assert session.query(BuybackPlan).count() == 1
    assert session.query(BuybackEventLinkDecision).count() == 1


def test_redecision_reactivates_existing_origin_plan(session):
    _store_event(session)
    plan = BuybackPlan(
        buyback_plan_id="plan-existing",
        code="1234",
        origin_event_uid="event-1",
        lifecycle_status="INVALIDATED_ORIGIN",
    )
    session.add(plan)
    session.commit()

    result = decide_new_plan(
        session,
        event_uid="event-1",
        candidate_plan_ids=[],
        rule_version="new-plan:v2",
        input_fingerprint="input-2",
        uid_factory=_ids("decision"),
    )

    assert result.linked_plan_id == "plan-existing"
    assert plan.lifecycle_status == "ACTIVE"


def test_unresolved_new_plan_does_not_create_plan(session):
    _store_event(session, _event(independent_resolution=None))

    result = decide_new_plan(
        session,
        event_uid="event-1",
        candidate_plan_ids=[],
        rule_version="new-plan:v1",
        input_fingerprint="input-1",
        uid_factory=_ids("decision"),
    )

    assert result.status == "UNRESOLVED"
    assert result.linked_plan_id is None
    assert session.query(BuybackPlan).count() == 0


def test_existing_normal_decision_can_be_made_current_after_expiration(session):
    _store_event(session)
    normal = decide_new_plan(
        session,
        event_uid="event-1",
        candidate_plan_ids=[],
        rule_version="new-plan:v1",
        input_fingerprint="input-1",
        uid_factory=_ids("first"),
    )
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

    restored = decide_new_plan(
        session,
        event_uid="event-1",
        candidate_plan_ids=[],
        rule_version="new-plan:v1",
        input_fingerprint="input-1",
        uid_factory=_ids("unused"),
    )

    assert restored.decision_id == normal.decision_id
    assert restored.is_current is True
    assert expiration.is_current is False
    assert session.query(BuybackEventLinkDecision).count() == 2


def test_new_input_appends_decision_and_supersedes_current(session):
    _store_event(session)
    first = decide_new_plan(
        session,
        event_uid="event-1",
        candidate_plan_ids=[],
        rule_version="new-plan:v1",
        input_fingerprint="input-1",
        uid_factory=_ids("first"),
    )
    session.commit()

    second = decide_new_plan(
        session,
        event_uid="event-1",
        candidate_plan_ids=[],
        rule_version="new-plan:v1",
        input_fingerprint="input-2",
        uid_factory=_ids("second"),
    )

    assert first.is_current is False
    assert second.is_current is True
    assert second.supersedes_decision_id == first.decision_id
    assert second.linked_plan_id == first.linked_plan_id


def test_inactive_event_is_not_decided(session):
    stored = _store_event(session)
    stored.is_active = False
    session.commit()

    with pytest.raises(ValueError, match="active event not found"):
        decide_new_plan(
            session,
            event_uid="event-1",
            candidate_plan_ids=[],
            rule_version="new-plan:v1",
            input_fingerprint="input-1",
        )
