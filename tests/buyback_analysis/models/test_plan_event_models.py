import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from buyback_analysis.models.base import Base
from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import (
    BuybackEventLinkDecision,
)
from buyback_analysis.models.buyback_plan import BuybackPlan


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _event(uid="event-1"):
    return BuybackEvent(
        event_uid=uid,
        version_id="version-1",
        url="https://example.test/document.pdf",
        code="1234",
        event_type="new_plan",
        event_fingerprint=f"fingerprint-{uid}",
        source_quote="自己株式取得を決議した。",
        payload={"buyback_shares": 1000},
        is_active=True,
    )


def _decision(decision_id="decision-1", **overrides):
    values = {
        "decision_id": decision_id,
        "event_uid": "event-1",
        "status": "UNRESOLVED",
        "decision_kind": "NORMAL",
        "linked_plan_id": None,
        "candidates": [],
        "reason_codes": ["MISSING_RESOLUTION_DATE"],
        "rule_version": "link:v1",
        "input_fingerprint": "input-1",
        "is_current": True,
    }
    values.update(overrides)
    return BuybackEventLinkDecision(**values)


def test_plan_model_has_immutable_id_and_unique_origin_event():
    mapper = inspect(BuybackPlan)

    assert [column.name for column in mapper.primary_key] == ["buyback_plan_id"]
    assert BuybackPlan.code.nullable is False
    assert BuybackPlan.origin_event_uid.nullable is False
    assert BuybackPlan.origin_event_uid.unique is True
    assert BuybackPlan.lifecycle_status.nullable is False


def test_event_model_keeps_extracted_payload_and_active_state():
    mapper = inspect(BuybackEvent)
    columns = {column.name for column in mapper.columns}

    assert [column.name for column in mapper.primary_key] == ["event_uid"]
    assert {
        "version_id",
        "url",
        "document_title",
        "disclosure_datetime",
        "code",
        "event_type",
        "event_fingerprint",
        "event_date",
        "resolution_date",
        "referenced_document_date",
        "referenced_document_title",
        "source_quote",
        "source_quote_verified",
        "source_page",
        "source_section",
        "payload",
        "is_active",
    } <= columns


def test_decision_model_defines_two_partial_unique_indexes():
    indexes = {index.name: index for index in BuybackEventLinkDecision.__table__.indexes}

    assert set(indexes) >= {
        "uq_buyback_event_normal_decision_input",
        "uq_buyback_event_current_decision",
    }
    assert indexes["uq_buyback_event_normal_decision_input"].unique is True
    assert indexes["uq_buyback_event_current_decision"].unique is True
    assert str(
        indexes["uq_buyback_event_normal_decision_input"].dialect_options[
            "sqlite"
        ]["where"]
    ) == "decision_kind = 'NORMAL'"
    assert str(
        indexes["uq_buyback_event_current_decision"].dialect_options["sqlite"][
            "where"
        ]
    ) == "is_current = 1"


def test_normal_decision_is_idempotent_for_same_rule_and_input(session):
    session.add(_event())
    session.add(_decision())
    session.commit()
    session.add(
        _decision(
            "decision-2",
            status="AMBIGUOUS",
            is_current=False,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_only_one_current_decision_is_allowed_per_event(session):
    session.add(_event())
    session.add(_decision())
    session.commit()
    session.add(
        _decision(
            "decision-2",
            rule_version="link:v2",
            input_fingerprint="input-2",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "LINKED", "linked_plan_id": None},
        {"status": "UNRESOLVED", "linked_plan_id": "plan-1"},
        {
            "decision_kind": "EXPIRATION",
            "status": "LINKED",
            "linked_plan_id": "plan-1",
            "rule_version": "expire:v1",
            "input_fingerprint": None,
        },
        {
            "decision_kind": "NORMAL",
            "input_fingerprint": None,
        },
    ],
)
def test_invalid_decision_state_is_rejected_by_database(session, overrides):
    session.add(_event())
    session.add(_decision(**overrides))

    with pytest.raises(IntegrityError):
        session.commit()


def test_expiration_decisions_do_not_conflict_with_normal_idempotency_index(session):
    session.add(_event())
    session.add(
        _decision(
            "expiration-1",
            decision_kind="EXPIRATION",
            rule_version="expire:v1",
            input_fingerprint=None,
        )
    )
    session.commit()
    session.add(
        _decision(
            "expiration-2",
            decision_kind="EXPIRATION",
            rule_version="expire:v1",
            input_fingerprint=None,
            is_current=False,
        )
    )

    session.commit()

    assert session.query(BuybackEventLinkDecision).count() == 2
