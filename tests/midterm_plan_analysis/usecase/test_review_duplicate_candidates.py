import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from buyback_analysis.models.base import Base
from midterm_plan_analysis.models.midterm_plan import MidtermPlan
from midterm_plan_analysis.models.midterm_plan_keyword import MidtermPlanKeyword
from midterm_plan_analysis.usecase.detect_duplicate_candidates import DETECTOR_VERSION
from midterm_plan_analysis.usecase.review_duplicate_candidates import (
    REVIEW_KIND,
    build_review_document,
    build_review_entries,
    current_review_state,
)
from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.processing_run import ProcessingRun
from tdnet_provenance.models.result_adoption import ResultAdoption
from tdnet_provenance.models.result_version import ResultVersion
from tdnet_provenance.models.tdnet_source_document import TdnetSourceDocument

URL = "https://www.release.tdnet.info/inbs/140120250430500001.pdf"
OTHER_URL = "https://www.release.tdnet.info/inbs/140120250430500002.pdf"
SOURCE_HASH = "a" * 64
PROMPT_HASH = "b" * 64


def _metric(**overrides):
    metric = {
        "name": "売上高", "value": 13000, "unit": "百万円", "target_year": 2031,
        "target_period_label": "2031年3月期（計画）", "target_fiscal_end": "2031/03",
        "target_scope": "plan_final", "revision_role": "current", "consolidation_label": None,
        "bound": "exact", "value_upper": None, "value_text": "13,000", "page": 1,
    }
    metric.update(overrides)
    return metric


DUPLICATED = [
    _metric(),
    _metric(name="営業利益", value=1940, value_text="1,940"),
    _metric(target_year=2030, target_period_label="2030年度", target_fiscal_end=None, page=10),
    _metric(name="営業利益", value=1940, value_text="1,940", target_year=2030,
            target_period_label="2030年度", target_fiscal_end=None, page=10),
]


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[MidtermPlan.__table__, MidtermPlanKeyword.__table__])
    ProvenanceBase.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False, future=True)() as s:
        yield s


def _plan(url=URL, metrics=DUPLICATED, status="ok", code="5367"):
    return MidtermPlan(
        code=code, url=url, plan_name="中期経営計画2030", plan_start_year=2026, plan_end_year=2030,
        plan_end_period_label="2031年3月期", plan_end_fiscal_end="2031/03", disclosure_date="2025-05-01",
        metrics=json.dumps(metrics, ensure_ascii=False) if metrics is not None else None,
        reference_values='[{"name": "売上高", "value": 9000, "unit": "百万円", "kind": "actual"}]',
        extraction_status=status,
    )


def _run(run_id, stage, prompt_hash, status="succeeded"):
    return ProcessingRun(
        run_id=run_id, url=URL, input_locator="tdnet-pdf://20250501/x.pdf", source_hash=SOURCE_HASH,
        input_hash="c" * 64, run_kind="extract", stage=stage, code_commit="d" * 40,
        prompt_name=f"{stage}.md", prompt_hash=prompt_hash, generation_config="{}", reuse_key="e" * 64,
        status=status, started_at="2026-11-12T00:00:00", completed_at="2026-11-12T00:00:01",
    )


def _seed_provenance(session, metrics_status="succeeded"):
    session.add(TdnetSourceDocument(
        url=URL, source_document_id="sd-1", external_document_id="140120250430500001", disclosure_date="2025-05-01",
        storage_uri="tdnet-pdf://20250501/140120250430500001.pdf", source_hash=SOURCE_HASH, file_size=1,
        observed_at="2026-11-01T00:00:00",
    ))
    session.add(_run("run-metrics", "metrics", PROMPT_HASH, status=metrics_status))
    session.add(_run("run-keywords", "keywords", "f" * 64))
    for version_id, adopted_at in (("v-old", "2026-11-01T00:00:00"), ("v-new", "2026-11-12T00:00:00")):
        session.add(ResultVersion(
            version_id=version_id, url=URL, code="5367", result_type="midterm_plan", extraction_status="ok",
            payload="{}", run_ids=json.dumps(["run-metrics", "run-keywords"]) if version_id == "v-new" else "[]",
            origin="run" if version_id == "v-new" else "unrecorded", created_at=adopted_at,
        ))
        session.add(ResultAdoption(adoption_id=f"a-{version_id}", url=URL, result_type="midterm_plan",
                                   version_id=version_id, adopted_at=adopted_at))


class TestCurrentReviewState:
    def test_reads_latest_adoption_source_hash_and_metrics_prompt_hash(self, session):
        _seed_provenance(session)
        session.commit()
        assert current_review_state(session, URL) == {
            "adopted_version_id": "v-new",
            "version_origin": "run",
            "source_hash": SOURCE_HASH,
            "run_ids": ["run-metrics", "run-keywords"],
            "prompt_name": "metrics.md",
            "prompt_hash": PROMPT_HASH,
        }

    def test_without_history_everything_is_null(self, session):
        assert current_review_state(session, URL) == {
            "adopted_version_id": None, "version_origin": None, "source_hash": None,
            "run_ids": [], "prompt_name": None, "prompt_hash": None,
        }

    def test_reused_metrics_run_keeps_prompt_hash(self, session):
        _seed_provenance(session, metrics_status="reused")
        session.commit()
        assert current_review_state(session, URL)["prompt_hash"] == PROMPT_HASH


class TestBuildReviewEntries:
    def test_5367_entry_has_metadata_result_and_two_candidates(self, session):
        session.add(_plan())
        _seed_provenance(session)
        session.commit()

        entries = build_review_entries(session)

        assert len(entries) == 1
        entry = entries[0]
        assert entry["url"] == URL
        assert entry["code"] == "5367"
        assert entry["disclosure_date"] == "2025-05-01"
        assert entry["extraction_status"] == "ok"
        assert entry["adopted_version_id"] == "v-new"
        assert entry["source_hash"] == SOURCE_HASH
        assert entry["prompt_hash"] == PROMPT_HASH
        assert entry["result"]["type"] == "MIDTERM_PLAN"
        data = entry["result"]["data"]
        assert data["metrics"] == DUPLICATED
        assert data["plan_end_fiscal_end"] == "2031/03"
        assert data["reference_values"][0]["value"] == 9000
        assert [(c["rows"][0]["name"], c["pages"]) for c in entry["candidates"]] == [
            ("売上高", [1, 10]), ("営業利益", [1, 10]),
        ]
        assert all(c["resolution"] is None for c in entry["candidates"])

    def test_documents_without_candidates_are_omitted(self, session):
        session.add(_plan(url=OTHER_URL, metrics=[_metric()], code="1111"))
        session.commit()
        assert build_review_entries(session) == []

    @pytest.mark.parametrize("status", ["failed", "withdrawn", "no_targets"])
    def test_non_ok_rows_are_skipped(self, session, status):
        session.add(_plan(status=status))
        session.commit()
        assert build_review_entries(session) == []

    @pytest.mark.parametrize("metrics", [None, "not json", "{}"])
    def test_unreadable_metrics_are_skipped(self, session, metrics):
        plan = _plan()
        plan.metrics = metrics
        session.add(plan)
        session.commit()
        assert build_review_entries(session) == []

    def test_url_filter(self, session):
        session.add(_plan())
        session.add(_plan(url=OTHER_URL, code="1111"))
        session.commit()
        assert [e["url"] for e in build_review_entries(session, urls=[OTHER_URL])] == [OTHER_URL]

    def test_does_not_write(self, session):
        session.add(_plan())
        _seed_provenance(session)
        session.commit()
        build_review_entries(session)
        assert not session.new and not session.dirty
        assert session.query(ResultVersion).count() == 2
        assert session.query(ResultAdoption).count() == 2


def test_build_review_document():
    document = build_review_document([{"url": URL}], generated_at="2026-11-13T00:00:00+00:00")
    assert document["kind"] == REVIEW_KIND == "midterm_duplicate_review"
    assert document["format_version"] == 1
    assert document["detector_version"] == DETECTOR_VERSION
    assert document["generated_at"] == "2026-11-13T00:00:00+00:00"
    assert document["entries"] == [{"url": URL}]
    assert "resolution" in document["instructions"]
