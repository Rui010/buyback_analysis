import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from buyback_analysis.models.base import Base
from forecast_revision_analysis.models.forecast_revision_detail import ForecastRevisionDetail as Detail
from forecast_revision_analysis.models.forecast_revision_metric import ForecastRevisionMetric as Metric
from forecast_revision_analysis.usecase.post_forecast_revision import post_forecast_revision


@pytest.fixture
def session():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def seed(session, status='failed'):
    session.add(Detail(code='3512', url='source', extraction_status=status, disclosure_date='2020-01-01'))
    session.commit()


def test_failed_can_be_replaced(session):
    seed(session)
    assert post_forecast_revision(session, {'data': {'reason_raw': 'new'}}, '3512', 'source', '2020-01-01', 'ok')
    assert session.get(Detail, ('3512', 'source')).extraction_status == 'ok'


def test_bad_replacement_rolls_back_to_failed(session):
    seed(session)
    data = {'data': {'periods': [{'prev_value': 'bad'}]}}
    assert not post_forecast_revision(session, data, '3512', 'source', '2020-01-01', 'ok')
    assert session.get(Detail, ('3512', 'source')).extraction_status == 'failed'


def test_ok_is_not_overwritten(session):
    seed(session, 'ok')
    assert not post_forecast_revision(session, {}, '3512', 'source', '2020-01-01', 'failed')
    assert session.get(Detail, ('3512', 'source')).extraction_status == 'ok'


def test_failed_urls_include_old_disclosures(session):
    from forecast_revision_analysis.usecase.retry_failed import get_failed_urls, already_processed
    seed(session)
    assert get_failed_urls(session) == ['source']
    assert not already_processed(session, '3512', 'source')
    assert not already_processed(session, 'other', 'source')
    session.get(Detail, ('3512', 'source')).extraction_status = 'ok'
    session.commit()
    assert already_processed(session, '3512', 'source')
    assert get_failed_urls(session) == []
