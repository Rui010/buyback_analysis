import datetime
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from buyback_analysis.models.base import Base
from midterm_plan_analysis.models.midterm_plan import MidtermPlan
from midterm_plan_analysis.models.midterm_plan_keyword import MidtermPlanKeyword
from midterm_plan_analysis.usecase.import_verified_result import import_verified_result
from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.result_adoption import ResultAdoption
from tdnet_provenance.models.result_version import ResultVersion

URL = "https://www.release.tdnet.info/inbs/140120260218512345.pdf"
NOW = datetime.datetime(2026, 11, 10, 12, 0, tzinfo=datetime.timezone.utc)
RESULT = {"type": "MIDTERM_PLAN", "data": {
    "plan_name": "新計画", "plan_end_year": 2027,
    "metrics": [{"name": "売上高", "value": 500, "unit": "億円", "target_scope": "plan_final"}],
    "reference_values": [{"name": "売上高", "value": 450, "unit": "億円", "kind": "actual"}],
}}


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[MidtermPlan.__table__, MidtermPlanKeyword.__table__])
    ProvenanceBase.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False, future=True)() as s:
        yield s


def _seed(session, keywords=()):
    session.add(MidtermPlan(code="1234", url=URL, plan_name="旧計画", disclosure_date="2026-02-19",
                            metrics='[{"name": "売上高", "value": 400}]', extraction_status="ok"))
    for keyword in keywords:
        session.add(MidtermPlanKeyword(code="1234", url=URL, keyword=keyword, context_raw="文脈",
                                       disclosure_date="2026-02-19", normalized_keyword=f"n-{keyword}"))
    session.commit()


def _import(session, status="ok", result=RESULT):
    return import_verified_result(session, url=URL, result=result, extraction_status=status, clock=lambda: NOW)


def test_replaces_current_row_with_verified_result(session):
    _seed(session)
    assert _import(session) is True

    plan = session.query(MidtermPlan).one()
    assert plan.plan_name == "新計画"
    assert plan.code == "1234"
    assert plan.disclosure_date == "2026-02-19"  # 既存行の開示日を引き継ぐ
    assert json.loads(plan.reference_values) == RESULT["data"]["reference_values"]
    assert json.loads(plan.metrics) == RESULT["data"]["metrics"]


def test_keeps_old_result_as_legacy_version_and_adopts_unrecorded(session):
    _seed(session)
    _import(session)

    versions = {v.origin: v for v in session.query(ResultVersion).all()}
    assert set(versions) == {"legacy", "unrecorded"}
    legacy = json.loads(versions["legacy"].payload)
    assert legacy["midterm_plans"][0]["plan_name"] == "旧計画"
    assert json.loads(versions["unrecorded"].run_ids) == []
    assert session.query(ResultAdoption).one().version_id == versions["unrecorded"].version_id


def test_existing_keywords_are_carried_over(session):
    _seed(session, keywords=["DX", "海外"])
    _import(session)

    rows = sorted((k.keyword, k.context_raw, k.normalized_keyword, k.disclosure_date)
                  for k in session.query(MidtermPlanKeyword).all())
    assert rows == [("DX", "文脈", "n-DX", "2026-02-19"), ("海外", "文脈", "n-海外", "2026-02-19")]
    adopted = session.query(ResultVersion).filter(ResultVersion.origin == "unrecorded").one()
    assert len(json.loads(adopted.payload)["midterm_plan_keywords"]) == 2


def test_status_is_saved(session):
    _seed(session)
    _import(session, status="withdrawn", result={"type": "MIDTERM_PLAN", "data": {"metrics": []}})
    assert session.query(MidtermPlan).one().extraction_status == "withdrawn"


def test_missing_current_row_is_not_created(session):
    assert _import(session) is False
    assert session.query(MidtermPlan).count() == 0
    assert session.query(ResultVersion).count() == 0


@pytest.mark.parametrize("result,status", [(None, "ok"), (RESULT, "failed")])
def test_unusable_result_keeps_current(session, result, status):
    _seed(session)
    assert _import(session, status=status, result=result) is False
    assert session.query(MidtermPlan).one().plan_name == "旧計画"
    assert session.query(ResultVersion).count() == 0


def test_write_failure_rolls_back_and_keeps_current(session):
    _seed(session, keywords=["DX"])
    assert _import(session, status="invalid") is False  # post_midterm_planが不正なstatusを拒否
    assert session.query(MidtermPlan).one().plan_name == "旧計画"
    assert session.query(MidtermPlanKeyword).count() == 1
    assert session.query(ResultVersion).count() == 0
