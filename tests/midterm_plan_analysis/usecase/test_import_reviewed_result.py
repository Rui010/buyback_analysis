import copy
import datetime
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from buyback_analysis.models.base import Base
from midterm_plan_analysis.models.midterm_plan import MidtermPlan
from midterm_plan_analysis.models.midterm_plan_keyword import MidtermPlanKeyword
from midterm_plan_analysis.usecase.import_reviewed_result import (
    import_reviewed_entry,
    prepare_reviewed_entry,
    validate_reviewed_result,
)
from midterm_plan_analysis.usecase.review_duplicate_candidates import build_review_entries
from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.result_adoption import ResultAdoption
from tdnet_provenance.models.result_version import ResultVersion
from tdnet_provenance.models.tdnet_source_document import TdnetSourceDocument

URL = "https://www.release.tdnet.info/inbs/140120250430500001.pdf"
SOURCE_HASH = "a" * 64
NOW = datetime.datetime(2026, 11, 13, 12, 0, tzinfo=datetime.timezone.utc)


def _metric(**overrides):
    metric = {
        "name": "売上高", "value": 13000, "unit": "百万円", "target_year": 2031,
        "target_period_label": "2031年3月期（計画）", "target_fiscal_end": "2031/03",
        "target_scope": "plan_final", "revision_role": "current", "consolidation_label": None,
        "bound": "exact", "value_upper": None, "value_text": "13,000", "page": 1,
    }
    metric.update(overrides)
    return metric


def _p10(**overrides):
    values = {"target_year": 2030, "target_period_label": "2030年度", "target_fiscal_end": None, "page": 10}
    values.update(overrides)
    return _metric(**values)


OPERATING = {"name": "営業利益", "value": 1940, "value_text": "1,940"}
METRICS = [_metric(), _metric(**OPERATING), _p10(), _p10(**OPERATING),
           _p10(name="ROE", value=7, unit="%", bound="lower", target_scope="plan_interim",
                target_period_label="2027年度", target_year=2027, value_text="7%以上")]


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[MidtermPlan.__table__, MidtermPlanKeyword.__table__])
    ProvenanceBase.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False, future=True)() as s:
        yield s


def _seed(session, with_version=True):
    session.add(MidtermPlan(
        code="5367", url=URL, plan_name="中期経営計画2030", plan_end_year=2030, plan_end_period_label="2031年3月期",
        plan_end_fiscal_end="2031/03", disclosure_date="2025-05-01",
        metrics=json.dumps(METRICS, ensure_ascii=False), reference_values="[]", extraction_status="ok",
    ))
    session.add(MidtermPlanKeyword(code="5367", url=URL, keyword="住宅", context_raw="文脈", disclosure_date="2025-05-01"))
    session.add(TdnetSourceDocument(
        url=URL, source_document_id="sd-1", external_document_id="140120250430500001", disclosure_date="2025-05-01",
        storage_uri="tdnet-pdf://20250501/140120250430500001.pdf", source_hash=SOURCE_HASH, file_size=1,
        observed_at="2026-11-01T00:00:00",
    ))
    if with_version:
        session.add(ResultVersion(version_id="v-1", url=URL, code="5367", result_type="midterm_plan",
                                  extraction_status="ok", payload="{}", run_ids="[]", origin="unrecorded",
                                  created_at="2026-11-10T00:00:00"))
        session.add(ResultAdoption(adoption_id="a-1", url=URL, result_type="midterm_plan", version_id="v-1",
                                   adopted_at="2026-11-10T00:00:00"))
    session.commit()


def _entry(session):
    return copy.deepcopy(build_review_entries(session)[0])


def _merge(entry):
    """p.10の2行を削除し、両候補をmergedにする（レビューで直した想定）。"""
    entry["result"]["data"]["metrics"] = [m for i, m in enumerate(entry["result"]["data"]["metrics"]) if i not in (2, 3)]
    for candidate in entry["candidates"]:
        candidate["resolution"] = "merged"
    return entry


class TestImportReviewedEntry:
    def test_merged_entry_is_adopted_as_new_version(self, session):
        _seed(session)
        ok, errors = import_reviewed_entry(session, _merge(_entry(session)), clock=lambda: NOW)

        assert (ok, errors) == (True, [])
        metrics = json.loads(session.query(MidtermPlan).one().metrics)
        assert [(m["name"], m["page"]) for m in metrics] == [("売上高", 1), ("営業利益", 1), ("ROE", 10)]
        assert session.query(MidtermPlanKeyword).count() == 1  # キーワードは引き継ぐ
        new = session.query(ResultVersion).filter(ResultVersion.version_id != "v-1").one()
        assert new.origin == "unrecorded"
        latest = session.query(ResultAdoption).order_by(ResultAdoption.adopted_at.desc()).first()
        assert latest.version_id == new.version_id

    def test_existing_versions_are_not_changed(self, session):
        _seed(session)
        import_reviewed_entry(session, _merge(_entry(session)), clock=lambda: NOW)
        old = session.get(ResultVersion, "v-1")
        assert (old.payload, old.created_at) == ("{}", "2026-11-10T00:00:00")
        assert session.get(ResultAdoption, "a-1").version_id == "v-1"

    def test_same_review_cannot_be_imported_twice(self, session):
        _seed(session)
        entry = _merge(_entry(session))
        assert import_reviewed_entry(session, copy.deepcopy(entry), clock=lambda: NOW)[0] is True
        ok, errors = import_reviewed_entry(session, entry, clock=lambda: NOW)
        assert ok is False
        assert any("adopted_version_id" in e for e in errors)

    def test_rejected_entry_keeps_current(self, session):
        _seed(session)
        entry = _entry(session)  # 直していない（resolution=null）
        ok, errors = import_reviewed_entry(session, entry, clock=lambda: NOW)
        assert ok is False
        assert len([e for e in errors if "possible_duplicate_target" in e]) == 2
        assert json.loads(session.query(MidtermPlan).one().metrics) == METRICS
        assert session.query(ResultVersion).count() == 1


class TestPreconditions:
    def test_version_mismatch(self, session):
        _seed(session)
        entry = _merge(_entry(session))
        entry["adopted_version_id"] = "v-other"
        _, errors = prepare_reviewed_entry(session, entry)
        assert any("adopted_version_id" in e for e in errors)

    def test_source_hash_mismatch(self, session):
        _seed(session)
        entry = _merge(_entry(session))
        entry["source_hash"] = "b" * 64
        _, errors = prepare_reviewed_entry(session, entry)
        assert any("source_hash" in e for e in errors)

    def test_missing_keys_are_rejected(self, session):
        _seed(session)
        entry = _merge(_entry(session))
        del entry["adopted_version_id"]
        _, errors = prepare_reviewed_entry(session, entry)
        assert any("adopted_version_id" in e for e in errors)

    def test_null_version_matches_when_no_adoption_exists(self, session):
        _seed(session, with_version=False)
        entry = _merge(_entry(session))
        assert entry["adopted_version_id"] is None
        result, errors = prepare_reviewed_entry(session, entry)
        assert errors == [] and result is not None

    def test_missing_current_row(self, session):
        _seed(session)
        entry = _merge(_entry(session))
        session.query(MidtermPlan).delete()
        session.commit()
        _, errors = prepare_reviewed_entry(session, entry)
        assert any("midterm_plans" in e for e in errors)

    def test_code_mismatch(self, session):
        _seed(session)
        entry = _merge(_entry(session))
        entry["code"] = "9999"
        _, errors = prepare_reviewed_entry(session, entry)
        assert any("code" in e for e in errors)

    @pytest.mark.parametrize("status", ["failed", "bogus", None])
    def test_invalid_status(self, session, status):
        _seed(session)
        entry = _merge(_entry(session))
        entry["extraction_status"] = status
        _, errors = prepare_reviewed_entry(session, entry)
        assert any("extraction_status" in e for e in errors)

    def test_invalid_resolution(self, session):
        _seed(session)
        entry = _merge(_entry(session))
        entry["candidates"][0]["resolution"] = "keep"
        _, errors = prepare_reviewed_entry(session, entry)
        assert any("resolution" in e for e in errors)


class TestDuplicateRecheck:
    def test_distinct_candidates_are_accepted(self, session):
        _seed(session)
        entry = _entry(session)
        for candidate in entry["candidates"]:
            candidate["resolution"] = "distinct"
        entry["result"]["data"]["metrics"][4]["value_text"] = "7％以上"  # 内容は変える
        result, errors = prepare_reviewed_entry(session, entry)
        assert errors == []
        assert len(result["data"]["metrics"]) == 5

    def test_merged_label_but_rows_left_is_rejected(self, session):
        _seed(session)
        entry = _entry(session)
        for candidate in entry["candidates"]:
            candidate["resolution"] = "merged"
        _, errors = prepare_reviewed_entry(session, entry)
        assert len([e for e in errors if "possible_duplicate_target" in e]) == 2

    def test_new_candidate_introduced_by_edit_is_rejected(self, session):
        _seed(session)
        entry = _merge(_entry(session))
        entry["result"]["data"]["metrics"].append(_p10(name="ROE", value=7, unit="%", bound="lower",
                                                       target_scope="plan_interim", target_period_label="2028年3月期",
                                                       target_fiscal_end="2028/03", target_year=2027, page=12,
                                                       value_text="7%以上"))
        _, errors = prepare_reviewed_entry(session, entry)
        assert any("possible_duplicate_target" in e for e in errors)

    def test_exact_duplicate_is_merged_automatically(self, session):
        _seed(session)
        entry = _merge(_entry(session))
        entry["result"]["data"]["metrics"].append(_metric(page=10, target_period_label="2030年度（2031年3月期）"))
        result, errors = prepare_reviewed_entry(session, entry)
        assert errors == []
        assert [m["name"] for m in result["data"]["metrics"]] == ["売上高", "営業利益", "ROE"]

    def test_unchanged_result_is_not_imported(self, session):
        _seed(session)
        entry = _entry(session)
        for candidate in entry["candidates"]:
            candidate["resolution"] = "distinct"
        result, errors = prepare_reviewed_entry(session, entry)
        assert result is None
        assert any("変更なし" in e for e in errors)


class TestValidateReviewedResult:
    def _result(self, metrics=None, **data):
        payload = {"plan_end_fiscal_end": "2031/03", "plan_end_year": 2030,
                   "metrics": [_metric()] if metrics is None else metrics, "reference_values": []}
        payload.update(data)
        return {"type": "MIDTERM_PLAN", "data": payload}

    def test_valid(self):
        assert validate_reviewed_result(self._result()) == []

    @pytest.mark.parametrize("result", [None, [], {"data": None}, {"data": {"metrics": "x"}}, {"data": {}}])
    def test_shape(self, result):
        assert validate_reviewed_result(result) != []

    @pytest.mark.parametrize("overrides,word", [
        ({"name": ""}, "name"),
        ({"value": "13,000"}, "value"),
        ({"value": True}, "value"),
        ({"target_scope": "final"}, "target_scope"),
        ({"revision_role": "old"}, "revision_role"),
        ({"consolidation_label": "連結"}, "consolidation_label"),
        ({"bound": "min"}, "bound"),
        ({"page": 0}, "page"),
        ({"page": "1"}, "page"),
        ({"unit": 1}, "unit"),
        ({"segment": ""}, "segment"),
        ({"target_year": "2031"}, "target_year"),
        ({"target_fiscal_end": "2031-03"}, "target_fiscal_end"),
        ({"target_fiscal_end": "2031/13"}, "target_fiscal_end"),
        ({"target_fiscal_end": "2030/03"}, "target_fiscal_end"),  # ラベル「2031年3月期」と矛盾
        ({"bound": "range", "value_upper": None}, "value_upper"),
        ({"bound": "range", "value_upper": 12000}, "value_upper"),
        ({"bound": "exact", "value_upper": 14000}, "value_upper"),
    ])
    def test_metric_errors(self, overrides, word):
        errors = validate_reviewed_result(self._result([_metric(**overrides)]))
        assert errors and any(word in e for e in errors)
        assert "metrics[0]" in errors[0]

    def test_fiscal_year_label_accepts_either_year(self):
        assert validate_reviewed_result(self._result([_p10(target_fiscal_end="2031/03")])) == []
        assert validate_reviewed_result(self._result([_p10(target_fiscal_end="2030/12")])) == []

    def test_range_is_valid(self):
        assert validate_reviewed_result(self._result([_metric(bound="range", value_upper=14000)])) == []

    def test_null_value_is_allowed(self):
        assert validate_reviewed_result(self._result([_metric(value=None, value_text="未定")])) == []

    @pytest.mark.parametrize("data,word", [
        ({"plan_end_fiscal_end": "2031"}, "plan_end_fiscal_end"),
        ({"plan_start_year": "2026"}, "plan_start_year"),
        ({"reference_values": "x"}, "reference_values"),
        ({"reference_values": [{"name": "売上高", "value": "9,000", "kind": "actual"}]}, "value"),
        ({"reference_values": [{"name": "売上高", "value": 9000, "kind": "実績"}]}, "kind"),
        ({"reference_values": [{"name": "売上高", "value": 9000, "kind": "actual",
                                "period_fiscal_end": "2025年3月"}]}, "period_fiscal_end"),
    ])
    def test_plan_and_reference_errors(self, data, word):
        errors = validate_reviewed_result(self._result(**data))
        assert errors and any(word in e for e in errors)

    def test_reference_values_may_be_null(self):
        assert validate_reviewed_result(self._result(reference_values=None)) == []
