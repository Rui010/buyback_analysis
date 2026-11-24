from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from buyback_analysis.models.announcement_plan_status import AnnouncementPlanStatus
from buyback_analysis.models.base import Base
from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import BuybackEventLinkDecision
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.models.buyback_plan_projection import BuybackPlanProjection
from buyback_analysis.usecase.rebuild_announcement_plan_status import (
    rebuild_announcement_plan_status,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _event(uid, event_type="new_plan", *, url=None, event_date=None, is_active=True):
    return BuybackEvent(
        event_uid=uid,
        version_id="version-1",
        url=url or f"https://example.test/{uid}.pdf",
        code="1234",
        event_type=event_type,
        event_fingerprint=f"fingerprint-{uid}",
        event_date=event_date,
        source_quote="根拠原文",
        payload={},
        is_active=is_active,
    )


def _linked(event_uid, plan_id, *, is_current=True, decision_id=None):
    return BuybackEventLinkDecision(
        decision_id=decision_id or f"decision-{event_uid}",
        event_uid=event_uid,
        status="LINKED",
        decision_kind="NORMAL",
        linked_plan_id=plan_id,
        candidates=[{"plan_id": plan_id}],
        reason_codes=["TEST_EVIDENCE"],
        rule_version="link:v1",
        input_fingerprint=f"input-{decision_id or event_uid}",
        is_current=is_current,
    )


def _plan(session, plan_id, origin_uid, *, url=None, publishable=True, **projection):
    session.add(_event(origin_uid, url=url, event_date="2026-01-01"))
    session.add(_linked(origin_uid, plan_id))
    session.add(
        BuybackPlan(
            buyback_plan_id=plan_id,
            code="1234",
            origin_event_uid=origin_uid,
            lifecycle_status="ACTIVE" if publishable else "INVALIDATED_ORIGIN",
        )
    )
    values = {
        "current_shares": 1000,
        "current_amount_yen": 5_000_000,
        "current_start_date": "2026-01-02",
        "current_end_date": "2026-12-31",
        "cumulative_shares_acquired": None,
        "cumulative_amount_spent_yen": None,
        "completion_shares_acquired": None,
        "completion_amount_spent_yen": None,
        "plan_status": "planned",
    }
    values.update(projection)
    session.add(
        BuybackPlanProjection(
            buyback_plan_id=plan_id,
            lifecycle_status="ACTIVE" if publishable else "INVALIDATED_ORIGIN",
            is_publishable=publishable,
            input_fingerprint=f"fp-{plan_id}",
            aggregation_rule_version="projection:v1",
            **values,
        )
    )


def _rows(session):
    return {
        row.buyback_plan_id: row
        for row in session.query(AnnouncementPlanStatus).all()
    }


def test_derives_columns_from_plan_projection_and_origin_event():
    session = _session()
    _plan(
        session,
        "plan-1",
        "origin-1",
        url="https://example.test/announce.pdf",
        cumulative_shares_acquired=250,
        cumulative_amount_spent_yen=2_000_000,
        plan_status="in_progress",
    )
    session.add(_event("progress-1", "progress", event_date="2026-03-05"))
    session.add(_linked("progress-1", "plan-1"))
    session.commit()

    count = rebuild_announcement_plan_status(session)

    assert count == 1
    row = _rows(session)["plan-1"]
    projection = session.get(BuybackPlanProjection, "plan-1")
    assert row.announcement_url == "https://example.test/announce.pdf"
    assert row.code == "1234"
    assert row.plan_status == "in_progress"
    assert row.current_shares == 1000
    assert row.current_amount_yen == 5_000_000
    assert row.current_start_date == "2026-01-02"
    assert row.current_end_date == "2026-12-31"
    assert row.cumulative_shares_acquired == 250
    assert row.cumulative_amount_spent_yen == 2_000_000
    assert row.completion_shares_acquired is None
    assert row.completion_amount_spent_yen is None
    assert row.progress_rate_shares == 0.25
    assert row.progress_rate_amount == 0.4
    assert row.latest_progress_date == "2026-03-05"
    assert row.aggregation_rule_version == "projection:v1"
    assert row.calculated_at == projection.calculated_at


def test_progress_rate_is_null_when_limit_or_cumulative_is_missing():
    session = _session()
    # 上限なし・累計あり
    _plan(
        session,
        "no-limit",
        "origin-a",
        current_shares=None,
        current_amount_yen=None,
        cumulative_shares_acquired=100,
        cumulative_amount_spent_yen=500_000,
    )
    # 上限あり・累計なし
    _plan(session, "no-cumulative", "origin-b")
    # 上限0（ゼロ除算はNULL）
    _plan(
        session,
        "zero-limit",
        "origin-c",
        current_shares=0,
        current_amount_yen=0,
        cumulative_shares_acquired=100,
        cumulative_amount_spent_yen=500_000,
    )
    session.commit()

    rebuild_announcement_plan_status(session)

    rows = _rows(session)
    for plan_id in ("no-limit", "no-cumulative", "zero-limit"):
        assert rows[plan_id].progress_rate_shares is None
        assert rows[plan_id].progress_rate_amount is None


def test_progress_rate_is_computed_per_metric_independently():
    session = _session()
    _plan(
        session,
        "plan-1",
        "origin-1",
        current_amount_yen=None,
        cumulative_shares_acquired=500,
        cumulative_amount_spent_yen=1_000_000,
    )
    session.commit()

    rebuild_announcement_plan_status(session)

    row = _rows(session)["plan-1"]
    assert row.progress_rate_shares == 0.5
    assert row.progress_rate_amount is None


def test_only_publishable_plans_are_included():
    session = _session()
    _plan(session, "public", "origin-public")
    _plan(session, "hidden", "origin-hidden", publishable=False)
    session.commit()

    count = rebuild_announcement_plan_status(session)

    assert count == 1
    assert set(_rows(session)) == {"public"}


def test_one_document_with_multiple_plans_produces_one_row_per_plan():
    session = _session()
    url = "https://example.test/two-plans.pdf"
    _plan(session, "plan-a", "origin-a", url=url)
    _plan(session, "plan-b", "origin-b", url=url)
    session.commit()

    count = rebuild_announcement_plan_status(session)

    assert count == 2
    rows = _rows(session)
    assert rows["plan-a"].announcement_url == url
    assert rows["plan-b"].announcement_url == url


def test_latest_progress_date_uses_only_current_linked_active_progress_events():
    session = _session()
    _plan(session, "plan-1", "origin-1")
    _plan(session, "plan-2", "origin-2")
    session.add_all(
        [
            _event("p-old", "progress", event_date="2026-02-01"),
            _event("p-new", "progress", event_date="2026-04-01"),
            _event("p-no-date", "progress", event_date=None),
            # 採用されていない（失効した）イベント
            _event("p-inactive", "progress", event_date="2026-09-01", is_active=False),
            # 現行でない判定
            _event("p-superseded", "progress", event_date="2026-08-01"),
            # 別案件の進捗
            _event("p-other", "progress", event_date="2026-07-01"),
            # 進捗以外の種別
            _event("completion-1", "completion", event_date="2026-10-01"),
        ]
    )
    session.add_all(
        [
            _linked("p-old", "plan-1"),
            _linked("p-new", "plan-1"),
            _linked("p-no-date", "plan-1"),
            _linked("p-inactive", "plan-1"),
            _linked("p-superseded", "plan-1", is_current=False),
            _linked("p-other", "plan-2"),
            _linked("completion-1", "plan-1"),
        ]
    )
    session.commit()

    rebuild_announcement_plan_status(session)

    rows = _rows(session)
    assert rows["plan-1"].latest_progress_date == "2026-04-01"
    assert rows["plan-2"].latest_progress_date == "2026-07-01"


def test_latest_progress_date_is_null_without_progress_events():
    session = _session()
    _plan(session, "plan-1", "origin-1")
    session.commit()

    rebuild_announcement_plan_status(session)

    assert _rows(session)["plan-1"].latest_progress_date is None


def test_rebuild_is_idempotent_and_removes_rows_that_are_no_longer_publishable():
    session = _session()
    _plan(session, "plan-1", "origin-1")
    _plan(session, "plan-2", "origin-2")
    session.commit()

    assert rebuild_announcement_plan_status(session) == 2
    session.commit()
    assert rebuild_announcement_plan_status(session) == 2
    session.commit()
    assert set(_rows(session)) == {"plan-1", "plan-2"}

    session.get(BuybackPlanProjection, "plan-2").is_publishable = False
    session.commit()

    assert rebuild_announcement_plan_status(session) == 1
    session.commit()
    assert set(_rows(session)) == {"plan-1"}


def test_rebuild_flushes_without_committing():
    session = _session()
    _plan(session, "plan-1", "origin-1")
    session.commit()

    rebuild_announcement_plan_status(session)
    session.rollback()

    assert _rows(session) == {}
