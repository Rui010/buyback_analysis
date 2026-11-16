from itertools import count

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from buyback_analysis.models.base import Base
from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import (
    BuybackEventLinkDecision,
)
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.models.buyback_plan_projection import BuybackPlanProjection
from buyback_analysis.usecase.adopt_buyback_events import adopt_buyback_events
from buyback_analysis.usecase.event_schemas import BuybackEventExtraction


URL = "https://example.test/buyback.pdf"


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _new_plan(amount=5_000_000):
    return BuybackEventExtraction.model_validate(
        {
            "events": [
                {
                    "event_type": "new_plan",
                    "event_date": "2026-01-01",
                    "resolution_date": "2026-01-01",
                    "source_quote": "自己株式取得を決議した。",
                    "source_page": 1,
                    "payload": {
                        "buyback_shares": 1000,
                        "buyback_amount_yen": amount,
                        "start_date": "2026-01-02",
                        "end_date": "2026-12-31",
                    },
                }
            ]
        }
    ).events[0]


def _uid_factory(prefix):
    sequence = count(1)
    return lambda: f"{prefix}-{next(sequence)}"


def _adopt(session, events, version="version-1", uid_factory=None):
    return adopt_buyback_events(
        session,
        version_id=version,
        url=URL,
        code="1234",
        document_title="自己株式取得に係る事項の決定",
        events=events,
        uid_factory=uid_factory or _uid_factory("id"),
    )


def test_first_adoption_inserts_active_event_without_committing(session):
    result = _adopt(session, [_new_plan()], uid_factory=lambda: "event-1")

    assert result.assigned_event_uids == ("event-1",)
    assert result.content_changed_uids == ()
    assert result.removed_event_uids == ()
    stored = session.get(BuybackEvent, "event-1")
    assert stored.version_id == "version-1"
    assert stored.document_title == "自己株式取得に係る事項の決定"
    assert stored.payload["buyback_amount_yen"] == 5_000_000
    assert stored.is_active is True

    session.rollback()
    assert session.get(BuybackEvent, "event-1") is None


def test_exact_readoption_keeps_uid_and_updates_version(session):
    _adopt(session, [_new_plan()], uid_factory=lambda: "event-1")
    session.commit()

    result = _adopt(
        session,
        [_new_plan()],
        version="version-2",
        uid_factory=lambda: "must-not-be-used",
    )

    assert result.assigned_event_uids == ("event-1",)
    assert session.get(BuybackEvent, "event-1").version_id == "version-2"
    assert session.query(BuybackEvent).count() == 1
    assert session.query(BuybackEventLinkDecision).count() == 0


def test_corrected_single_event_keeps_uid_and_adds_content_expiration(session):
    _adopt(session, [_new_plan()], uid_factory=lambda: "event-1")
    session.add(
        BuybackEventLinkDecision(
            decision_id="decision-old",
            event_uid="event-1",
            status="LINKED",
            decision_kind="NORMAL",
            linked_plan_id="plan-1",
            candidates=[],
            reason_codes=["EXACT_RESOLUTION_DATE"],
            rule_version="link:v1",
            input_fingerprint="input-old",
            is_current=True,
        )
    )
    # SQLite does not enforce foreign keys unless PRAGMA is enabled in this unit test.
    session.commit()

    result = _adopt(
        session,
        [_new_plan(amount=6_000_000)],
        version="version-2",
        uid_factory=_uid_factory("decision"),
    )

    assert result.assigned_event_uids == ("event-1",)
    assert result.content_changed_uids == ("event-1",)
    assert session.get(BuybackEvent, "event-1").payload["buyback_amount_yen"] == 6_000_000
    decisions = {
        decision.decision_id: decision
        for decision in session.query(BuybackEventLinkDecision).all()
    }
    assert decisions["decision-old"].is_current is False
    expiration = next(
        decision
        for decision in decisions.values()
        if decision.decision_kind == "EXPIRATION"
    )
    assert expiration.is_current is True
    assert expiration.status == "UNRESOLVED"
    assert expiration.linked_plan_id is None
    assert expiration.reason_codes == ["EXPIRED_BY_CONTENT_CHANGE"]
    assert expiration.supersedes_decision_id == "decision-old"


def test_removed_active_event_is_inactivated_and_expired_once(session):
    _adopt(session, [_new_plan()], uid_factory=lambda: "event-1")
    session.commit()

    first = _adopt(session, [], version="version-2", uid_factory=_uid_factory("decision"))
    session.commit()
    second = _adopt(session, [], version="version-3", uid_factory=_uid_factory("again"))

    assert first.removed_event_uids == ("event-1",)
    assert second.removed_event_uids == ()
    assert session.get(BuybackEvent, "event-1").is_active is False
    decisions = session.query(BuybackEventLinkDecision).all()
    assert len(decisions) == 1
    assert decisions[0].reason_codes == ["EXPIRED_BY_REMOVAL"]
    assert decisions[0].is_current is True


def test_exact_match_reactivates_previously_removed_event(session):
    _adopt(session, [_new_plan()], uid_factory=lambda: "event-1")
    session.commit()
    _adopt(session, [], version="version-2", uid_factory=_uid_factory("decision"))
    session.commit()

    result = _adopt(
        session,
        [_new_plan()],
        version="version-3",
        uid_factory=lambda: "must-not-be-used",
    )

    assert result.reactivated_event_uids == ("event-1",)
    assert session.get(BuybackEvent, "event-1").is_active is True


def test_flush_failure_can_roll_back_entire_adoption(session):
    duplicate_uid = lambda: "same-event"
    events = [_new_plan(), _new_plan(amount=7_000_000)]

    with pytest.raises(IntegrityError):
        with session.begin():
            _adopt(session, events, uid_factory=duplicate_uid)

    assert session.query(BuybackEvent).count() == 0


def test_origin_content_change_invalidates_plan_and_downstream_links(session):
    _adopt(session, [_new_plan()], uid_factory=lambda: "event-1")
    progress = BuybackEvent(
        event_uid="progress-1",
        version_id="version-1",
        url="https://example.test/progress.pdf",
        code="1234",
        event_type="progress",
        event_fingerprint="progress-fingerprint",
        source_quote="取得状況",
        payload={"cumulative_shares_acquired": 100},
        is_active=True,
    )
    session.add(progress)
    session.add(
        BuybackPlan(
            buyback_plan_id="plan-1",
            code="1234",
            origin_event_uid="event-1",
            lifecycle_status="ACTIVE",
        )
    )
    session.add_all(
        [
            BuybackEventLinkDecision(
                decision_id="origin-linked",
                event_uid="event-1",
                status="LINKED",
                decision_kind="NORMAL",
                linked_plan_id="plan-1",
                candidates=[{"plan_id": "plan-1"}],
                reason_codes=["NEW_PLAN_EVIDENCE_COMPLETE"],
                rule_version="link:v1",
                input_fingerprint="origin-input",
                is_current=True,
            ),
            BuybackEventLinkDecision(
                decision_id="progress-linked",
                event_uid="progress-1",
                status="LINKED",
                decision_kind="NORMAL",
                linked_plan_id="plan-1",
                candidates=[{"plan_id": "plan-1"}],
                reason_codes=["EXPLICIT_RESOLUTION_REFERENCE"],
                rule_version="link:v1",
                input_fingerprint="progress-input",
                is_current=True,
            ),
        ]
    )
    session.commit()

    result = _adopt(
        session,
        [_new_plan(amount=6_000_000)],
        version="version-2",
        uid_factory=_uid_factory("generated"),
    )

    assert result.content_changed_uids == ("event-1",)
    assert session.get(BuybackPlan, "plan-1").lifecycle_status == "INVALIDATED_ORIGIN"
    progress_current = (
        session.query(BuybackEventLinkDecision)
        .filter(
            BuybackEventLinkDecision.event_uid == "progress-1",
            BuybackEventLinkDecision.is_current.is_(True),
        )
        .one()
    )
    assert progress_current.decision_kind == "EXPIRATION"
    assert progress_current.reason_codes == ["EXPIRED_BY_ORIGIN_INVALIDATION"]
    assert progress_current.linked_plan_id is None
    projection = session.get(BuybackPlanProjection, "plan-1")
    assert projection.lifecycle_status == "INVALIDATED_ORIGIN"
    assert projection.is_publishable is False
