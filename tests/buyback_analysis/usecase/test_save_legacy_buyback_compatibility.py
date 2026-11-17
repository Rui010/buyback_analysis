from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from buyback_analysis.models.announcement import Announcement
from buyback_analysis.models.base import Base
from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.completion import Completion
from buyback_analysis.models.is_checked import IsChecked
from buyback_analysis.models.progress import Progress
from buyback_analysis.models.retirement import Retirement
from buyback_analysis.usecase.save_legacy_buyback_compatibility import (
    requires_legacy_llm,
    save_legacy_buyback_compatibility,
)
from tdnet_provenance.models.base import ProvenanceBase


URL = "https://example.test/compound.pdf"


def test_only_correction_titles_require_the_legacy_llm_path():
    assert requires_legacy_llm("自己株式取得に関するお知らせの一部訂正") is True
    assert requires_legacy_llm("自己株式取得に関するお知らせ") is False


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    ProvenanceBase.metadata.create_all(engine)
    return Session(engine)


def _event(event_uid, event_type, payload, resolution_date):
    return BuybackEvent(
        event_uid=event_uid,
        version_id="version-1",
        url=URL,
        code="3350",
        event_type=event_type,
        event_fingerprint=event_uid,
        resolution_date=resolution_date,
        source_quote="十分に長い原文引用です。",
        source_quote_verified=True,
        payload=payload,
        is_active=True,
    )


def test_compound_events_write_announcement_and_completion_without_llm():
    session = _session()
    session.add_all(
        [
            _event(
                "new",
                "new_plan",
                {
                    "buyback_shares": 200_000_000,
                    "buyback_amount_yen": 60_000_000_000,
                    "start_date": "2026-10-14",
                    "end_date": "2027-10-13",
                    "buyback_method": "market_purchase",
                },
                "2026-10-13",
            ),
            _event(
                "old-completion",
                "completion",
                {"shares_acquired": 0, "amount_spent_yen": 0},
                "2025-10-28",
            ),
        ]
    )
    session.flush()

    saved = save_legacy_buyback_compatibility(
        session,
        code="3350",
        url=URL,
        disclosure_date="2026-10-13",
        company_name="メタプラネット",
        rerun=False,
    )

    assert saved is True
    assert session.get(Announcement, URL).buyback_shares == 200_000_000
    assert session.get(Completion, URL).amount_spent_yen == 0
    checked = session.query(IsChecked).filter(IsChecked.url == URL).one()
    assert checked.detected_type == "buyback_announcement"
    assert checked.parse_status == "saved"


def test_execution_notice_only_is_marked_skipped_in_legacy_tables():
    session = _session()
    session.add(
        _event(
            "execution",
            "execution_notice",
            {"subtype": "planned", "planned_buyback_shares": 100},
            "2026-10-13",
        )
    )
    session.flush()

    saved = save_legacy_buyback_compatibility(
        session,
        code="3350",
        url=URL,
        disclosure_date="2026-10-13",
        company_name="メタプラネット",
        rerun=False,
    )

    assert saved is True
    assert session.get(Announcement, URL) is None
    assert session.query(IsChecked).filter(IsChecked.url == URL).one().parse_status == "skipped"


def test_progress_and_retirement_payloads_are_materialized():
    session = _session()
    session.add_all(
        [
            _event(
                "progress",
                "progress",
                {
                    "cumulative_shares_acquired": 50,
                    "cumulative_amount_spent_yen": 5000,
                    "period_start": "2026-10-01",
                    "period_end": "2026-10-31",
                },
                "2026-01-01",
            ),
            _event(
                "retirement",
                "retirement",
                {
                    "retirement_date": "2026-11-01",
                    "retirement_shares": 10,
                    "share_type": "common",
                },
                "2026-01-01",
            ),
        ]
    )
    session.flush()

    assert save_legacy_buyback_compatibility(
        session,
        code="3350",
        url=URL,
        disclosure_date="2026-10-31",
        company_name="メタプラネット",
        rerun=False,
    )

    assert session.get(Progress, URL).cumulative_shares_acquired == 50
    assert session.get(Retirement, URL).retirement_shares == 10


def test_rerun_replaces_legacy_current_rows_and_versions_result():
    session = _session()
    event = _event(
        "new",
        "new_plan",
        {"buyback_shares": 100, "buyback_amount_yen": 1000},
        "2026-10-13",
    )
    session.add(event)
    session.flush()
    assert save_legacy_buyback_compatibility(
        session, code="3350", url=URL, disclosure_date="2026-10-13",
        company_name="メタプラネット", rerun=False,
    )

    event.payload = {"buyback_shares": 200, "buyback_amount_yen": 2000}
    session.commit()

    assert save_legacy_buyback_compatibility(
        session, code="3350", url=URL, disclosure_date="2026-10-13",
        company_name="メタプラネット", rerun=True,
    )
    assert session.get(Announcement, URL).buyback_shares == 200
