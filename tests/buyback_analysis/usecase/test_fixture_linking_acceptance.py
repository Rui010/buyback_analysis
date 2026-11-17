from itertools import count
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from buyback_analysis.models.base import Base
from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import BuybackEventLinkDecision
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.usecase.relink_buyback_events import relink_buyback_events
from tests.buyback_analysis.fixture_manifest import MANIFEST_ROOT, load_manifest


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _ids():
    sequence = count(1)
    return lambda: f"generated-{next(sequence)}"


def _event(code, uid, event_type, payload, *, resolution_date=None, title=None):
    return BuybackEvent(
        event_uid=uid,
        version_id="fixture-version",
        url=f"https://fixture.test/{uid}.pdf",
        document_title=title,
        code=code,
        event_type=event_type,
        event_fingerprint=f"fingerprint-{uid}",
        resolution_date=resolution_date,
        source_quote="fixture evidence",
        source_quote_verified=True,
        payload=payload,
        is_active=True,
    )


def _current_decision(session, uid):
    return (
        session.query(BuybackEventLinkDecision)
        .filter(
            BuybackEventLinkDecision.event_uid == uid,
            BuybackEventLinkDecision.is_current.is_(True),
        )
        .one()
    )


def test_3350_manifest_partial_execution_links_to_new_plan():
    manifest = load_manifest(MANIFEST_ROOT / "3350" / "source_manifest.toml")
    documents = {document["role"]: document for document in manifest.documents}
    session = _session()
    uid_factory = _ids()

    old = documents["old_plan_origin"]["evidence"]
    session.add(
        _event(
            "3350",
            "old-origin",
            "new_plan",
            {
                "company_own_transaction": True,
                "independent_resolution": True,
                "buyback_shares": old["buyback_shares"],
                "buyback_amount_yen": old["buyback_amount_yen"],
                "start_date": old["start_date"],
                "end_date": old["end_date"],
            },
            resolution_date=old["resolution_date"],
        )
    )
    session.commit()
    relink_buyback_events(session, code="3350", rule_version="fixture:v1", uid_factory=uid_factory)
    session.commit()

    combined = documents["old_completion_and_new_origin"]["evidence"]
    session.add_all(
        [
            _event(
                "3350",
                "old-completion",
                "completion",
                {
                    "shares_acquired": combined["old_cumulative_shares"],
                    "amount_spent_yen": combined["old_cumulative_amount_yen"],
                },
                resolution_date=combined["old_resolution_date"],
            ),
            _event(
                "3350",
                "new-origin",
                "new_plan",
                {
                    "company_own_transaction": True,
                    "independent_resolution": True,
                    "buyback_shares": combined["new_buyback_shares"],
                    "buyback_amount_yen": combined["new_buyback_amount_yen"],
                    "start_date": combined["new_start_date"],
                    "end_date": combined["new_end_date"],
                },
                resolution_date=combined["new_resolution_date"],
            ),
        ]
    )
    session.commit()
    relink_buyback_events(session, code="3350", rule_version="fixture:v1", uid_factory=uid_factory)
    session.commit()

    execution = documents["execution_notice"]["evidence"]
    session.add(
        _event(
            "3350",
            "execution",
            "execution_notice",
            {
                "subtype": "planned",
                "planned_buyback_shares": execution["planned_buyback_shares"],
                "planned_buyback_amount_yen": execution["planned_buyback_amount_yen"],
                "buyback_method": execution["method"],
            },
            resolution_date=execution["referenced_resolution_date"],
        )
    )
    session.commit()
    relink_buyback_events(session, code="3350", rule_version="fixture:v1", uid_factory=uid_factory)

    assert session.query(BuybackPlan).count() == manifest.data["expected_relationship"]["plan_count"]
    assert _current_decision(session, "execution").status == documents["execution_notice"]["expected_link_status"]
    assert _current_decision(session, "execution").linked_plan_id == _current_decision(session, "new-origin").linked_plan_id


def test_6574_manifest_repeated_resolution_does_not_create_third_plan():
    manifest = load_manifest(MANIFEST_ROOT / "6574" / "source_manifest.toml")
    documents = {document["role"]: document for document in manifest.documents}
    session = _session()
    uid_factory = _ids()
    relative = documents["relative_acquisition_origin"]["evidence"]
    session.add(
        _event(
            "6574",
            "relative-origin",
            "new_plan",
            {
                "company_own_transaction": True,
                "independent_resolution": True,
                "buyback_shares": relative["buyback_shares"],
                "buyback_amount_yen": relative["buyback_amount_yen"],
            },
            resolution_date=relative["decision_date"],
        )
    )
    session.commit()
    relink_buyback_events(session, code="6574", rule_version="fixture:v1", uid_factory=uid_factory)
    session.commit()

    combined = documents["combined_framework_and_market_origin"]["evidence"]
    session.add_all(
        [
            _event(
                "6574",
                "relative-repeat",
                "new_plan",
                {
                    "company_own_transaction": True,
                    "independent_resolution": True,
                    "buyback_shares": combined["relative_buyback_shares"],
                    "buyback_amount_yen": combined["relative_buyback_amount_yen"],
                },
                resolution_date=combined["relative_decision_date"],
            ),
            _event(
                "6574",
                "market-origin",
                "new_plan",
                {
                    "company_own_transaction": True,
                    "independent_resolution": True,
                    "buyback_shares": combined["market_buyback_shares"],
                    "buyback_amount_yen": combined["market_buyback_amount_yen"],
                    "start_date": combined["market_start_date"],
                    "end_date": combined["market_end_date"],
                },
                resolution_date=combined["market_decision_date"],
            ),
        ]
    )
    session.commit()
    relink_buyback_events(session, code="6574", rule_version="fixture:v1", uid_factory=uid_factory)

    assert session.query(BuybackPlan).count() == manifest.data["expected_relationship"]["plan_count"]
    assert _current_decision(session, "relative-repeat").linked_plan_id == _current_decision(session, "relative-origin").linked_plan_id
    assert _current_decision(session, "market-origin").linked_plan_id != _current_decision(session, "relative-origin").linked_plan_id
