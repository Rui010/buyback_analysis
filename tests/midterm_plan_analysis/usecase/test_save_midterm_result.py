import datetime
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from buyback_analysis.models.base import Base
from midterm_plan_analysis.models.midterm_plan import MidtermPlan
from midterm_plan_analysis.models.midterm_plan_keyword import MidtermPlanKeyword
from midterm_plan_analysis.usecase.save_midterm_result import save_backfilled_keywords, save_midterm_result
from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.result_adoption import ResultAdoption
from tdnet_provenance.models.result_version import ResultVersion
from tdnet_provenance.usecase.provenance_recorder import ProvenanceRecorder

URL = "https://www.release.tdnet.info/inbs/140120260218512345.pdf"
NOW = datetime.datetime(2026, 2, 19, 8, 0, tzinfo=datetime.timezone.utc)
DATA = {"data": {"plan_name": "新計画", "metrics": [{"metric_name": "売上高", "value": 100}]}}


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[MidtermPlan.__table__, MidtermPlanKeyword.__table__])
    ProvenanceBase.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False, future=True)() as s:
        yield s


@pytest.fixture
def recorder(session):
    r = ProvenanceRecorder(session, code_commit="0" * 40, clock=lambda: NOW)
    r.start_document(URL)
    # 採用される版の前には必ずrunがある（版のrun_idsになる）
    r.record_decision(url=URL, stage="eligibility", outcome="test", outcome_reason="test", input_payload={})
    return r


def _save(session, recorder, status="ok", data=DATA, **kwargs):
    return save_midterm_result(
        session, recorder, code="1234", url=URL, disclosure_date="2026-02-19",
        data=data, extraction_status=status, **kwargs,
    )


def test_disabled_saves_like_before(session):
    assert _save(session, None, keywords=[{"keyword": "DX"}]) is True
    assert session.query(MidtermPlan).one().plan_name == "新計画"
    assert session.query(MidtermPlanKeyword).one().keyword == "DX"
    assert session.query(ResultVersion).count() == 0


def test_enabled_saves_version_with_plan_and_keywords(session, recorder):
    assert _save(session, recorder, keywords=[{"keyword": "DX"}]) is True
    [version] = session.query(ResultVersion).all()
    payload = json.loads(version.payload)
    assert payload["midterm_plans"][0]["plan_name"] == "新計画"
    assert payload["midterm_plan_keywords"][0]["keyword"] == "DX"
    assert session.query(ResultAdoption).count() == 1


def test_keywords_not_requested_leaves_keywords_untouched(session, recorder):
    assert _save(session, recorder) is True
    assert session.query(MidtermPlanKeyword).count() == 0


def test_rerun_failure_keeps_old_result(session, recorder):
    _save(session, None)
    assert _save(session, recorder, status="failed", data={}) is True
    assert session.query(MidtermPlan).one().extraction_status == "ok"
    assert session.query(ResultVersion).count() == 0


def test_failure_on_new_url_writes_failed_row(session, recorder):
    assert _save(session, recorder, status="failed", data={}) is True
    assert session.query(MidtermPlan).one().extraction_status == "failed"
    assert session.query(ResultVersion).count() == 0


def test_invalid_status_aborts_adoption_and_keeps_old(session, recorder):
    _save(session, None)
    assert _save(session, recorder, status="bogus") is False
    assert session.query(MidtermPlan).one().plan_name == "新計画"
    assert session.query(ResultVersion).count() == 0


def test_backfilled_keywords_become_new_version(session, recorder):
    _save(session, None)
    plan = SimpleNamespace(code="1234", url=URL, disclosure_date="2026-02-19", extraction_status="ok")

    assert save_backfilled_keywords(session, recorder, plan=plan, keywords=[{"keyword": "GX"}]) is True

    assert session.query(MidtermPlan).one().plan_name == "新計画"
    assert session.query(MidtermPlanKeyword).one().keyword == "GX"
    assert sorted(v.origin for v in session.query(ResultVersion).all()) == ["legacy", "run"]


def test_backfilled_keywords_disabled(session):
    _save(session, None)
    plan = SimpleNamespace(code="1234", url=URL, disclosure_date="2026-02-19", extraction_status="ok")
    assert save_backfilled_keywords(session, None, plan=plan, keywords=[{"keyword": "GX"}]) is True
    assert session.query(MidtermPlanKeyword).count() == 1
    assert session.query(ResultVersion).count() == 0


def test_keyword_save_failure_aborts_adoption(session, recorder):
    from unittest.mock import patch

    _save(session, None)
    with patch("midterm_plan_analysis.usecase.save_midterm_result.post_midterm_keywords", return_value=False):
        assert _save(session, recorder, data={"data": {"plan_name": "別計画"}}, keywords=[{"keyword": "X"}]) is False
    assert session.query(MidtermPlan).one().plan_name == "新計画"
    assert session.query(ResultVersion).count() == 0
