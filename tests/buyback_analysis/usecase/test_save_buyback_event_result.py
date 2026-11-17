import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from buyback_analysis.models.base import Base
from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import BuybackEventLinkDecision
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.usecase.event_schemas import BuybackEventExtraction
from buyback_analysis.usecase.save_buyback_event_result import (
    has_buyback_event_result,
    save_buyback_event_result,
)
from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.result_adoption import ResultAdoption
from tdnet_provenance.models.result_version import ResultVersion


URL = "https://example.test/buyback.pdf"
NOW = datetime.datetime(2026, 11, 17, 0, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    ProvenanceBase.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _extraction():
    return BuybackEventExtraction.model_validate(
        {
            "events": [
                {
                    "event_type": "new_plan",
                    "event_date": "2026-11-17",
                    "resolution_date": "2026-11-17",
                    "source_quote": "当社は自己株式の取得を決議しました。",
                    "payload": {
                        "company_own_transaction": True,
                        "independent_resolution": True,
                        "buyback_shares": 1000,
                    },
                }
            ]
        }
    )


def test_save_adopts_version_and_relinks_in_one_transaction(session):
    assert has_buyback_event_result(session, URL) is False
    saved = save_buyback_event_result(
        session,
        code="1234",
        url=URL,
        document_title="自己株式取得に係る事項の決定",
        disclosure_datetime="2026-11-17T15:00:00",
        extraction=_extraction(),
        quote_verified=(True,),
        run_ids=("run-1",),
        clock=lambda: NOW,
        version_id_factory=lambda: "version-1",
        adoption_id_factory=lambda: "adoption-1",
        event_uid_factory=lambda: "event-1",
        decision_uid_factory=lambda: "decision-1",
    )

    assert saved is True
    assert session.get(ResultVersion, "version-1").run_ids == '["run-1"]'
    assert session.get(ResultAdoption, "adoption-1").version_id == "version-1"
    assert session.get(BuybackEvent, "event-1").version_id == "version-1"
    assert has_buyback_event_result(session, URL) is True
    assert session.query(BuybackPlan).count() == 1
    assert session.query(BuybackEventLinkDecision).one().status == "LINKED"


def test_save_rolls_back_version_and_events_when_relink_fails(session, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("link failed")

    monkeypatch.setattr(
        "buyback_analysis.usecase.save_buyback_event_result.relink_buyback_events",
        fail,
    )

    saved = save_buyback_event_result(
        session,
        code="1234",
        url=URL,
        document_title="title",
        disclosure_datetime="2026-11-17T15:00:00",
        extraction=_extraction(),
        quote_verified=(True,),
        run_ids=("run-1",),
        clock=lambda: NOW,
        version_id_factory=lambda: "version-1",
        adoption_id_factory=lambda: "adoption-1",
        event_uid_factory=lambda: "event-1",
    )

    assert saved is False
    assert session.query(ResultVersion).count() == 0
    assert session.query(ResultAdoption).count() == 0
    assert session.query(BuybackEvent).count() == 0
