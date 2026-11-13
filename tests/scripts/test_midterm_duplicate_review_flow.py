"""重複候補のレビュー用JSON出力を、ファイルのSQLiteで通す（SQLiteには書かない）。"""

import datetime
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from buyback_analysis.models.base import Base
from midterm_plan_analysis.models.midterm_plan import MidtermPlan
from midterm_plan_analysis.models.midterm_plan_keyword import MidtermPlanKeyword
from scripts.review_midterm_duplicate_candidates import default_out_path, export_review
from tdnet_provenance.models.base import ProvenanceBase
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


def test_export_does_not_write_and_lists_5367_candidates(db_path, tmp_path):
    before = db_path.read_bytes()
    document, out_path = export_review(db_path, tmp_path / "out" / "review.json", clock=lambda: NOW)
    assert out_path == tmp_path / "out" / "review.json"

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


def test_default_output_is_next_to_sqlite(db_path):
    document, out_path = export_review(db_path, clock=lambda: NOW)
    assert out_path.parent == db_path.parent / "midterm_duplicate_review"
    assert out_path.name.startswith("review_") and out_path.suffix == ".json"
    assert json.loads(out_path.read_text(encoding="utf-8")) == document


def test_default_out_path_uses_local_time():
    now = datetime.datetime(2026, 11, 13, 6, 30, 0, tzinfo=datetime.timezone.utc)
    db = Path("//host/share/sqlite_db/buyback.db")  # サーバーのUNCパス
    path = default_out_path(db, now)
    assert path.parent == Path("//host/share/sqlite_db/midterm_duplicate_review")
    assert path.name == f"review_{now.astimezone():%Y%m%d_%H%M%S}.json"
