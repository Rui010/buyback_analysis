import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.processing_run import ProcessingRun
from tdnet_provenance.usecase.aggregate_usage import aggregate_document_usage

A = "https://x/a.pdf"
B = "https://x/b.pdf"


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    ProvenanceBase.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        yield s


def _run(session, run_id, url, status="succeeded", tokens=(100, 10), cost=None, currency=None,
         started="2026-11-08T00:00:00+00:00", run_kind="extract"):
    session.add(ProcessingRun(
        run_id=run_id, url=url, input_locator=url, input_hash="h", run_kind=run_kind, stage="metrics",
        code_commit="c", generation_config="{}", reuse_key="k", status=status, started_at=started,
        completed_at=started, input_tokens=tokens[0] if tokens else None, output_tokens=tokens[1] if tokens else None,
        estimated_cost=cost, estimated_cost_currency=currency,
    ))
    session.commit()


def test_sums_per_document_and_excludes_reused_cost(session):
    _run(session, "1", A, cost=1.5, currency="JPY")
    _run(session, "2", A, status="failed", tokens=(50, 0), cost=0.5, currency="JPY")
    _run(session, "3", A, status="reused", tokens=(0, 0), cost=0.0, currency="JPY")
    _run(session, "4", B, tokens=(10, 1))

    a, b = aggregate_document_usage(session)
    assert a["url"] == A
    assert (a["runs"], a["input_tokens"], a["output_tokens"]) == (3, 150, 10)
    assert (a["estimated_cost"], a["currency"]) == (2.0, "JPY")
    assert a["statuses"] == {"succeeded": 1, "failed": 1, "reused": 1}
    assert a["cost_missing_runs"] == 0
    assert (b["currency"], b["cost_missing_runs"]) == (None, 1)  # 単価未指定のrun


def test_filters_by_url_and_since(session):
    _run(session, "1", A, started="2026-11-01T00:00:00+00:00")
    _run(session, "2", A, started="2026-11-08T00:00:00+00:00")
    _run(session, "3", B)
    [row] = aggregate_document_usage(session, urls=[A], since="2026-11-05")
    assert row["runs"] == 1


def test_mixed_currency_is_rejected(session):
    _run(session, "1", A, cost=1.0, currency="JPY")
    _run(session, "2", A, cost=1.0, currency="USD")
    with pytest.raises(ValueError, match="通貨"):
        aggregate_document_usage(session)


def test_reused_only_document_keeps_currency(session):
    _run(session, "1", A, status="reused", tokens=(0, 0), cost=0.0, currency="JPY")
    [row] = aggregate_document_usage(session)
    assert (row["estimated_cost"], row["currency"]) == (0.0, "JPY")


def test_zero_cost_runs_with_mixed_currency_are_rejected(session):
    _run(session, "1", A, status="reused", tokens=(0, 0), cost=0.0, currency="JPY")
    _run(session, "2", A, status="reused", tokens=(0, 0), cost=0.0, currency="USD")
    with pytest.raises(ValueError, match="通貨"):
        aggregate_document_usage(session)


def test_decision_runs_are_not_counted_as_missing_cost(session):
    _run(session, "1", A, run_kind="route", tokens=None)
    [row] = aggregate_document_usage(session)
    assert row["cost_missing_runs"] == 0
