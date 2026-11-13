"""重複候補のレビュー: JSON出力 → 修正 → 既存の取込みスクリプトで採用、をファイルのSQLiteで通す。"""

import datetime
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from buyback_analysis.models.base import Base
from midterm_plan_analysis.models.midterm_plan import MidtermPlan
from midterm_plan_analysis.models.midterm_plan_keyword import MidtermPlanKeyword
from scripts.import_midterm_verified_results import run_import
from scripts.review_midterm_duplicate_candidates import export_review
from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.result_adoption import ResultAdoption
from tdnet_provenance.models.result_version import ResultVersion
from tdnet_provenance.models.tdnet_source_document import TdnetSourceDocument

URL = "https://www.release.tdnet.info/inbs/140120250430500001.pdf"
NOW = datetime.datetime(2026, 11, 13, 0, 0, tzinfo=datetime.timezone.utc)


def _metric(**overrides):
    metric = {
        "name": "売上高", "value": 13000, "unit": "百万円", "target_year": 2031,
        "target_period_label": "2031年3月期（計画）", "target_fiscal_end": "2031/03",
        "target_scope": "plan_final", "revision_role": "current", "consolidation_label": None,
        "bound": "exact", "value_upper": None, "value_text": "13,000", "page": 1,
    }
    metric.update(overrides)
    return metric


P10 = {"target_year": 2030, "target_period_label": "2030年度", "target_fiscal_end": None, "page": 10}
OPERATING = {"name": "営業利益", "value": 1940, "value_text": "1,940"}
METRICS = [_metric(), _metric(**OPERATING), _metric(**P10), _metric(**OPERATING, **P10)]


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "buyback.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}", future=True)
    Base.metadata.create_all(engine, tables=[MidtermPlan.__table__, MidtermPlanKeyword.__table__])
    ProvenanceBase.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        s.add(MidtermPlan(code="5367", url=URL, plan_end_year=2030, plan_end_fiscal_end="2031/03",
                          disclosure_date="2025-05-01", metrics=json.dumps(METRICS, ensure_ascii=False),
                          reference_values="[]", extraction_status="ok"))
        s.add(TdnetSourceDocument(
            url=URL, source_document_id="sd-1", external_document_id="140120250430500001",
            disclosure_date="2025-05-01", storage_uri="tdnet-pdf://20250501/140120250430500001.pdf",
            source_hash="a" * 64, file_size=1, observed_at="2026-11-01T00:00:00",
        ))
        s.commit()
    engine.dispose()
    return path


def _session(db_path):
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    return sessionmaker(bind=engine, future=True)()


def test_export_does_not_write_and_lists_5367_candidates(db_path, tmp_path):
    before = db_path.read_bytes()
    document = export_review(db_path, tmp_path / "out" / "review.json", clock=lambda: NOW)

    assert db_path.read_bytes() == before
    saved = json.loads((tmp_path / "out" / "review.json").read_text(encoding="utf-8"))
    assert saved == document
    entry = saved["entries"][0]
    assert (entry["code"], entry["source_hash"], entry["adopted_version_id"]) == ("5367", "a" * 64, None)
    assert [c["rows"][0]["name"] for c in entry["candidates"]] == ["売上高", "営業利益"]
    for candidate in entry["candidates"]:
        assert [r["target_period_label"] for r in candidate["rows"]] == ["2031年3月期（計画）", "2030年度"]


def test_export_requires_history_tables(tmp_path):
    path = tmp_path / "empty.db"
    create_engine(f"sqlite:///{path.as_posix()}").connect().close()
    with pytest.raises(RuntimeError):
        export_review(path, tmp_path / "review.json")


def test_reviewed_json_is_adopted_through_existing_import(db_path, tmp_path):
    review_path = tmp_path / "review.json"
    document = export_review(db_path, review_path, clock=lambda: NOW)
    entry = document["entries"][0]
    entry["result"]["data"]["metrics"] = entry["result"]["data"]["metrics"][:2]
    for candidate in entry["candidates"]:
        candidate["resolution"] = "merged"
    review_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    assert run_import(db_path, review_path, apply=False) == 1  # dry-runは書かない
    with _session(db_path) as s:
        assert s.query(ResultVersion).count() == 0

    assert run_import(db_path, review_path, apply=True) == 1
    with _session(db_path) as s:
        assert [m["page"] for m in json.loads(s.query(MidtermPlan).one().metrics)] == [1, 1]
        assert {v.origin for v in s.query(ResultVersion).all()} == {"legacy", "unrecorded"}
        assert s.query(ResultAdoption).count() == 1
    assert list(tmp_path.glob("buyback.db.bak-midterm-import-*"))

    # 採用版が変わったので、同じJSONはもう取り込めない
    assert run_import(db_path, review_path, apply=True) == 0


def test_unreviewed_json_is_rejected(db_path, tmp_path, capsys):
    review_path = tmp_path / "review.json"
    export_review(db_path, review_path, clock=lambda: NOW)
    assert run_import(db_path, review_path, apply=True) == 0
    assert "possible_duplicate_target" in capsys.readouterr().out
    with _session(db_path) as s:
        assert json.loads(s.query(MidtermPlan).one().metrics) == METRICS
        assert s.query(ResultVersion).count() == 0


def test_wrong_format_version_is_rejected(db_path, tmp_path):
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps({"kind": "midterm_duplicate_review", "format_version": 99, "entries": []}),
                           encoding="utf-8")
    with pytest.raises(ValueError):
        run_import(db_path, review_path, apply=False)
