import datetime
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from buyback_analysis.models.base import Base
from forecast_revision_analysis.models.forecast_revision_detail import ForecastRevisionDetail
from forecast_revision_analysis.models.forecast_revision_metric import ForecastRevisionMetric
from forecast_revision_analysis.usecase.save_forecast_result import save_forecast_result
from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.result_adoption import ResultAdoption
from tdnet_provenance.models.result_version import ResultVersion
from tdnet_provenance.usecase.provenance_recorder import ProvenanceRecorder

URL = "https://www.release.tdnet.info/inbs/140120260218512345.pdf"
NOW = datetime.datetime(2026, 2, 19, 8, 0, tzinfo=datetime.timezone.utc)


def _data(curr, metric_name="売上高"):
    return {"data": {"periods": [{
        "period_type": "4q", "fiscal_year": 2026, "consolidation_type": "consolidated",
        "metric_name": metric_name, "prev_value": 100, "curr_value": curr,
    }]}}


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[ForecastRevisionDetail.__table__, ForecastRevisionMetric.__table__])
    ProvenanceBase.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False, future=True)() as s:
        yield s


@pytest.fixture
def recorder(session):
    r = ProvenanceRecorder(session, code_commit="0" * 40, clock=lambda: NOW)
    r.start_document(URL)
    return r


def _save(session, recorder, status="ok", data=None):
    return save_forecast_result(
        session, recorder, code="1234", url=URL, disclosure_date="2026-02-19",
        data=_data(120) if data is None else data, extraction_status=status,
    )


def test_disabled_saves_like_before(session):
    assert _save(session, None) is True
    assert session.query(ForecastRevisionMetric).one().curr_value == 120
    assert session.query(ResultVersion).count() == 0


def test_rerun_replaces_current_and_keeps_old_as_legacy(session, recorder):
    _save(session, None)
    assert _save(session, recorder, data=_data(150)) is True

    assert session.query(ForecastRevisionMetric).one().curr_value == 150
    versions = {v.origin: json.loads(v.payload) for v in session.query(ResultVersion).all()}
    assert versions["legacy"]["forecast_revision_metrics"][0]["curr_value"] == 120
    assert versions["run"]["forecast_revision_metrics"][0]["curr_value"] == 150
    assert session.query(ResultAdoption).count() == 1


def test_failure_keeps_old_adoption(session, recorder):
    _save(session, None)
    assert _save(session, recorder, status="failed", data={}) is True
    assert session.query(ForecastRevisionDetail).one().extraction_status == "ok"
    assert session.query(ForecastRevisionMetric).one().curr_value == 120


def test_retry_of_failed_row_is_adopted_without_legacy_snapshot(session, recorder):
    _save(session, recorder, status="failed", data={})
    assert _save(session, recorder) is True
    assert session.query(ForecastRevisionDetail).one().extraction_status == "ok"
    assert [v.origin for v in session.query(ResultVersion).all()] == ["run"]


def test_withdrawn_is_adopted(session, recorder):
    assert _save(session, recorder, status="withdrawn", data={}) is True
    [version] = session.query(ResultVersion).all()
    assert version.extraction_status == "withdrawn"


def test_write_failure_aborts_and_keeps_old(session, recorder):
    _save(session, None)
    # metric_nameはNOT NULLのため、新しい結果の書き込みが失敗する
    assert _save(session, recorder, data=_data(150, metric_name=None)) is False
    assert session.query(ForecastRevisionMetric).one().curr_value == 120
    assert session.query(ResultVersion).count() == 0
