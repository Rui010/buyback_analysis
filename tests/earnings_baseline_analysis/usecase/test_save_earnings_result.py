import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from buyback_analysis.models.base import Base
from earnings_baseline_analysis.models.earnings_baseline import EarningsBaseline
from earnings_baseline_analysis.models.earnings_baseline_metric import EarningsBaselineMetric
from earnings_baseline_analysis.usecase.save_earnings_result import save_earnings_result
from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.result_version import ResultVersion

URL = "https://www.release.tdnet.info/inbs/140120260218512345.pdf"


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[EarningsBaseline.__table__, EarningsBaselineMetric.__table__])
    ProvenanceBase.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False, future=True)() as s:
        yield s


def _save(session, rerun, status="ok", data=None):
    return save_earnings_result(
        session, rerun=rerun, code="1234", url=URL, disclosure_date="2026-02-19",
        data={"data": {"fiscal_year_actual": 2026}} if data is None else data, extraction_status=status,
    )


def test_normal_mode_saves_like_before(session):
    assert _save(session, rerun=False) is True
    assert session.query(EarningsBaseline).one().fiscal_year_actual == 2026
    assert session.query(ResultVersion).count() == 0


def test_rerun_success_keeps_old_as_legacy(session):
    _save(session, rerun=False)
    assert _save(session, rerun=True, data={"data": {"fiscal_year_actual": 2027}}) is True

    assert session.query(EarningsBaseline).one().fiscal_year_actual == 2027
    versions = {v.origin: json.loads(v.payload) for v in session.query(ResultVersion).all()}
    assert versions["legacy"]["earnings_baselines"][0]["fiscal_year_actual"] == 2026
    assert versions["unrecorded"]["earnings_baselines"][0]["fiscal_year_actual"] == 2027


def test_rerun_failure_keeps_old(session):
    _save(session, rerun=False)
    assert _save(session, rerun=True, status="failed", data={}) is True
    assert session.query(EarningsBaseline).one().extraction_status == "ok"
    assert session.query(ResultVersion).count() == 0
