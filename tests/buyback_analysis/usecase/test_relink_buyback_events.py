from itertools import count

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from buyback_analysis.models.base import Base
from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import BuybackEventLinkDecision
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.models.buyback_plan_projection import BuybackPlanProjection
from buyback_analysis.usecase.relink_buyback_events import relink_buyback_events


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _ids(prefix="generated"):
    sequence = count(1)
    return lambda: f"{prefix}-{next(sequence)}"


def _event(uid, event_type, payload, **overrides):
    values = {
        "event_uid": uid,
        "version_id": "version-1",
        "url": f"https://example.test/{uid}.pdf",
        "document_title": f"document-{uid}",
        "code": "1234",
        "event_type": event_type,
        "event_fingerprint": f"fingerprint-{uid}",
        "source_quote": "判定根拠となる原文",
        "source_quote_verified": True,
        "payload": payload,
        "is_active": True,
    }
    values.update(overrides)
    return BuybackEvent(**values)


def test_new_plan_affects_progress_on_next_run_from_fixed_snapshot():
    session = _session()
    session.add_all(
        [
            _event(
                "progress-1",
                "progress",
                {"cumulative_shares_acquired": 400},
                resolution_date="2026-01-01",
            ),
            _event(
                "new-plan-1",
                "new_plan",
                {
                    "company_own_transaction": True,
                    "independent_resolution": True,
                    "buyback_shares": 1000,
                    "buyback_amount_yen": 5_000_000,
                    "start_date": "2026-01-02",
                    "end_date": "2026-12-31",
                },
                resolution_date="2026-01-01",
            ),
        ]
    )
    session.commit()

    first = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids()
    )

    assert first.evaluated == 2
    assert first.linked == 1
    assert first.unresolved == 1
    plan = session.query(BuybackPlan).one()
    session.commit()

    second = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids("second")
    )

    assert second.evaluated == 1
    assert second.linked == 1
    current_progress = (
        session.query(BuybackEventLinkDecision)
        .filter(
            BuybackEventLinkDecision.event_uid == "progress-1",
            BuybackEventLinkDecision.is_current.is_(True),
        )
        .one()
    )
    assert current_progress.linked_plan_id == plan.buyback_plan_id
    projection = session.get(BuybackPlanProjection, plan.buyback_plan_id)
    assert projection.is_publishable is True
    assert projection.cumulative_shares_acquired == 400


def test_current_linked_event_is_skipped_on_next_run():
    session = _session()
    session.add(
        _event(
            "new-plan-1",
            "new_plan",
            {
                "company_own_transaction": True,
                "independent_resolution": True,
                "buyback_shares": 1000,
            },
            resolution_date="2026-01-01",
        )
    )
    session.commit()
    relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids("first")
    )
    session.commit()

    result = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids("second")
    )

    assert result.evaluated == 0
    assert result.skipped_linked == 1
    assert session.query(BuybackEventLinkDecision).count() == 1


def test_unresolved_event_is_rechecked_without_duplicate_decision():
    session = _session()
    session.add(
        _event(
            "progress-1",
            "progress",
            {"cumulative_shares_acquired": 100},
        )
    )
    session.commit()
    first = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids("first")
    )
    session.commit()

    second = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids("second")
    )

    assert first.unresolved == 1
    assert second.evaluated == 1
    assert second.unresolved == 1
    assert session.query(BuybackEventLinkDecision).count() == 1


def test_inactive_event_and_other_code_are_not_evaluated():
    session = _session()
    session.add_all(
        [
            _event(
                "inactive",
                "progress",
                {"cumulative_shares_acquired": 100},
                is_active=False,
            ),
            _event(
                "other-code",
                "progress",
                {"cumulative_shares_acquired": 100},
                code="9999",
            ),
        ]
    )
    session.commit()

    result = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids()
    )

    assert result.evaluated == 0
    assert session.query(BuybackEventLinkDecision).count() == 0


def test_two_matching_plans_make_progress_ambiguous():
    session = _session()
    for suffix in ("a", "b"):
        origin_uid = f"origin-{suffix}"
        plan_id = f"plan-{suffix}"
        session.add(
            _event(
                origin_uid,
                "new_plan",
                {"buyback_shares": 1000},
                resolution_date="2026-01-01",
            )
        )
        session.add(
            BuybackPlan(
                buyback_plan_id=plan_id,
                code="1234",
                origin_event_uid=origin_uid,
                lifecycle_status="ACTIVE",
            )
        )
        session.add(
            BuybackEventLinkDecision(
                decision_id=f"decision-{suffix}",
                event_uid=origin_uid,
                status="LINKED",
                decision_kind="NORMAL",
                linked_plan_id=plan_id,
                candidates=[{"plan_id": plan_id}],
                reason_codes=["NEW_PLAN_EVIDENCE_COMPLETE"],
                rule_version="link:v1",
                input_fingerprint=f"origin-input-{suffix}",
                is_current=True,
            )
        )
    session.add(
        _event(
            "progress-1",
            "progress",
            {"cumulative_shares_acquired": 100},
            resolution_date="2026-01-01",
        )
    )
    session.commit()

    result = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids()
    )

    assert result.evaluated == 1
    assert result.ambiguous == 1
    decision = (
        session.query(BuybackEventLinkDecision)
        .filter(BuybackEventLinkDecision.event_uid == "progress-1")
        .one()
    )
    assert decision.status == "AMBIGUOUS"
    assert {item["plan_id"] for item in decision.candidates} == {
        "plan-a",
        "plan-b",
    }


def test_active_event_with_expiration_is_normally_redecided():
    session = _session()
    session.add(
        _event(
            "origin-1",
            "new_plan",
            {"buyback_shares": 1000},
            resolution_date="2026-01-01",
        )
    )
    session.add(
        _event(
            "progress-1",
            "progress",
            {"cumulative_shares_acquired": 100},
            resolution_date="2026-01-01",
        )
    )
    session.add(
        BuybackPlan(
            buyback_plan_id="plan-1",
            code="1234",
            origin_event_uid="origin-1",
            lifecycle_status="ACTIVE",
        )
    )
    session.add_all(
        [
            BuybackEventLinkDecision(
                decision_id="origin-decision",
                event_uid="origin-1",
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
                decision_id="expiration-1",
                event_uid="progress-1",
                status="UNRESOLVED",
                decision_kind="EXPIRATION",
                linked_plan_id=None,
                candidates=[],
                reason_codes=["EXPIRED_BY_CONTENT_CHANGE"],
                rule_version="expire:v1",
                input_fingerprint=None,
                is_current=True,
            ),
        ]
    )
    session.commit()

    result = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids()
    )

    assert result.evaluated == 1
    assert result.linked == 1
    assert session.get(BuybackEventLinkDecision, "expiration-1").is_current is False
    current = (
        session.query(BuybackEventLinkDecision)
        .filter(
            BuybackEventLinkDecision.event_uid == "progress-1",
            BuybackEventLinkDecision.is_current.is_(True),
        )
        .one()
    )
    assert current.decision_kind == "NORMAL"
    assert current.linked_plan_id == "plan-1"


def test_duplicate_new_plans_in_same_run_do_not_create_duplicate_plans():
    session = _session()
    payload = {
        "company_own_transaction": True,
        "independent_resolution": True,
        "buyback_shares": 200_000_000,
        "buyback_amount_yen": 60_000_000_000,
        "start_date": "2026-10-14",
        "end_date": "2027-10-13",
    }
    session.add_all(
        [
            _event("new-plan-a", "new_plan", payload, resolution_date="2026-10-13"),
            _event("new-plan-b", "new_plan", payload, resolution_date="2026-10-13"),
        ]
    )
    session.commit()

    result = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids()
    )

    assert result.linked == 1
    assert result.unresolved == 1
    assert session.query(BuybackPlan).count() == 1
    session.commit()

    second = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids("second")
    )

    assert second.linked == 1
    assert session.query(BuybackPlan).count() == 1
    decisions = [
        _current
        for _current in session.query(BuybackEventLinkDecision)
        .filter(BuybackEventLinkDecision.is_current.is_(True))
        .all()
        if _current.event_uid in {"new-plan-a", "new-plan-b"}
    ]
    assert {decision.linked_plan_id for decision in decisions} == {
        session.query(BuybackPlan).one().buyback_plan_id
    }


def test_same_resolution_date_with_different_frames_creates_separate_plans():
    session = _session()
    common = {
        "company_own_transaction": True,
        "independent_resolution": True,
    }
    session.add_all(
        [
            _event(
                "relative",
                "new_plan",
                {**common, "buyback_shares": 37_289_600, "buyback_amount_yen": 3_728_960_000},
                resolution_date="2026-09-30",
            ),
            _event(
                "market",
                "new_plan",
                {
                    **common,
                    "buyback_shares": 7_710_400,
                    "buyback_amount_yen": 771_040_000,
                    "start_date": "2026-10-01",
                    "end_date": "2027-03-31",
                },
                resolution_date="2026-09-30",
            ),
        ]
    )
    session.commit()

    result = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids()
    )

    assert result.linked == 2
    assert session.query(BuybackPlan).count() == 2


def test_repeated_new_plan_with_missing_amount_reuses_existing_plan():
    session = _session()
    full_payload = {
        "company_own_transaction": True,
        "independent_resolution": True,
        "buyback_shares": 1000,
        "buyback_amount_yen": 5_000_000,
        "start_date": "2026-01-02",
        "end_date": "2026-12-31",
    }
    session.add(
        _event("origin", "new_plan", full_payload, resolution_date="2026-01-01")
    )
    session.commit()
    relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids("first")
    )
    session.commit()
    session.add(
        _event(
            "repeat",
            "new_plan",
            {**full_payload, "buyback_amount_yen": None},
            resolution_date="2026-01-01",
        )
    )
    session.commit()

    result = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids("second")
    )

    assert result.linked == 1
    assert session.query(BuybackPlan).count() == 1
    assert (
        session.query(BuybackEventLinkDecision)
        .filter(
            BuybackEventLinkDecision.event_uid == "repeat",
            BuybackEventLinkDecision.is_current.is_(True),
        )
        .one()
        .linked_plan_id
        == session.query(BuybackPlan).one().buyback_plan_id
    )


def test_repeated_original_terms_after_amendment_reuses_existing_plan():
    session = _session()
    original = {
        "company_own_transaction": True,
        "independent_resolution": True,
        "buyback_shares": 1000,
        "buyback_amount_yen": 5_000_000,
    }
    session.add(_event("origin", "new_plan", original, resolution_date="2026-01-01"))
    session.commit()
    relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids("first")
    )
    session.commit()
    plan_id = session.query(BuybackPlan).one().buyback_plan_id
    session.add(
        _event(
            "amendment",
            "amendment",
            {"changed_buyback_shares": 1500},
            resolution_date="2026-01-01",
        )
    )
    session.commit()
    relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids("amend")
    )
    session.commit()
    session.add(_event("repeat", "new_plan", original, resolution_date="2026-01-01"))
    session.commit()

    relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids("repeat")
    )

    assert session.query(BuybackPlan).count() == 1
    assert (
        session.query(BuybackEventLinkDecision)
        .filter(
            BuybackEventLinkDecision.event_uid == "repeat",
            BuybackEventLinkDecision.is_current.is_(True),
        )
        .one()
        .linked_plan_id
        == plan_id
    )


def test_same_resolution_with_no_comparable_terms_is_unresolved():
    session = _session()
    session.add(
        _event(
            "origin",
            "new_plan",
            {
                "company_own_transaction": True,
                "independent_resolution": True,
                "buyback_shares": 1000,
            },
            resolution_date="2026-01-01",
        )
    )
    session.commit()
    relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids("first")
    )
    session.commit()
    session.add(
        _event(
            "unknown-repeat",
            "new_plan",
            {
                "company_own_transaction": True,
                "independent_resolution": True,
            },
            resolution_date="2026-01-01",
        )
    )
    session.commit()

    result = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids("second")
    )

    assert result.unresolved == 1
    assert session.query(BuybackPlan).count() == 1


def test_complete_duplicate_is_canonical_when_earlier_event_lacks_evidence():
    session = _session()
    common = {
        "company_own_transaction": True,
        "buyback_shares": 1000,
        "buyback_amount_yen": 5_000_000,
    }
    session.add_all(
        [
            _event(
                "earlier-incomplete",
                "new_plan",
                {**common, "independent_resolution": None},
                resolution_date="2026-01-01",
                disclosure_datetime="2026-01-02T09:00:00+09:00",
            ),
            _event(
                "later-complete",
                "new_plan",
                {**common, "independent_resolution": True},
                resolution_date="2026-01-01",
                disclosure_datetime="2026-01-02T10:00:00+09:00",
            ),
        ]
    )
    session.commit()

    first = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids("first")
    )

    assert first.linked == 1
    assert first.unresolved == 1
    assert session.query(BuybackPlan).count() == 1
    assert session.query(BuybackPlan).one().origin_event_uid == "later-complete"
    session.commit()

    second = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids("second")
    )

    assert second.unresolved == 1
    assert session.query(BuybackPlan).count() == 1


def test_unverified_quote_is_saved_as_unresolved_and_never_creates_plan():
    session = _session()
    session.add(
        _event(
            "unverified-origin",
            "new_plan",
            {
                "company_own_transaction": True,
                "independent_resolution": True,
                "buyback_shares": 1000,
            },
            resolution_date="2026-01-01",
            source_quote_verified=False,
        )
    )
    session.commit()

    result = relink_buyback_events(
        session, code="1234", rule_version="link:v1", uid_factory=_ids()
    )

    assert result.unresolved == 1
    assert session.query(BuybackPlan).count() == 0
    decision = session.query(BuybackEventLinkDecision).one()
    assert decision.reason_codes == ["SOURCE_QUOTE_NOT_FOUND"]
