import pytest

from midterm_plan_analysis.usecase.compare_midterm_fixture import (
    compare_document,
    fiscal_end,
    metric_code,
    summarize,
    to_yen,
)


def _doc(values, code="1234", status="ok", plan_end="2028-03-31", raw_unit="oku_yen"):
    return {"security_code": code, "db_extraction_status": status, "plan_period_end": plan_end,
            "raw_unit": raw_unit, "values": values}


def _value(kind="plan_target", code="revenue", period_end="2028-03-31", value=1000, **extra):
    return {"metric_code": code, "value_kind": kind, "period_end": period_end, "value": value,
            "consolidation": "unknown", "page": 2, **extra}


def _metric(name="売上高", value=1000, unit="億円", fiscal="2028/03", **extra):
    return {"name": name, "value": value, "unit": unit, "target_fiscal_end": fiscal,
            "target_scope": "plan_final", "revision_role": "current", "page": 2, **extra}


def _ref(name="売上高", value=900, unit="億円", fiscal="2025/03", kind="actual", **extra):
    return {"name": name, "value": value, "unit": unit, "period_fiscal_end": fiscal, "kind": kind, **extra}


def _failures(result, number):
    return result["conditions"][number]["failures"]


@pytest.mark.parametrize("name,expected", [
    ("売上高", "revenue"), ("連結売上収益", "revenue"), ("営業収益", "revenue"), ("営業利益", "operating_profit"),
    ("事業利益", "business_profit"), ("営業利益率", None), ("売上高成長率", None), ("ROE", None), (None, None),
])
def test_metric_code(name, expected):
    assert metric_code(name) == expected


def test_fiscal_end_and_to_yen():
    assert fiscal_end("2026-03-31") == "2026/03"
    assert fiscal_end(None) is None
    assert to_yen(1.5, "億円") == 1.5e8
    assert to_yen(1500, "百万円") == 1.5e9
    assert to_yen("1500", "百万円") is None
    assert to_yen(10, "%") is None


def test_target_found_with_matching_period_passes():
    result = compare_document(_doc([_value()]), {"data": {"metrics": [_metric()]}}, "ok")
    assert result["conditions"]["1"] == {"checked": 1, "failures": []}


def test_target_matched_across_units():
    doc = _doc([_value(value=86000)], raw_unit="million_yen")
    result = compare_document(doc, {"data": {"metrics": [_metric(value=860, unit="億円")]}}, "ok")
    assert _failures(result, "1") == []


def test_target_with_null_period_passes_with_note():
    result = compare_document(_doc([_value()]), {"data": {"metrics": [_metric(fiscal=None)]}}, "ok")
    assert _failures(result, "1") == []
    assert any("target_fiscal_endがnull" in note for note in result["notes"])


@pytest.mark.parametrize("metric,reason", [
    ([], "missing"), ([_metric(fiscal="2027/03")], "period_mismatch"),
    ([_metric(segment="A事業")], "segment_attached"), ([_metric(value=999)], "missing"),
])
def test_target_failures(metric, reason):
    result = compare_document(_doc([_value()]), {"data": {"metrics": metric}}, "ok")
    assert reason in _failures(result, "1")[0]


def test_long_term_scope_is_checked_after_plan_end():
    doc = _doc([_value(period_end="2031-03-31")])
    ok = compare_document(doc, {"data": {"metrics": [_metric(fiscal="2031/03", target_scope="long_term")]}}, "ok")
    ng = compare_document(doc, {"data": {"metrics": [_metric(fiscal="2031/03")]}}, "ok")
    assert ok["conditions"]["2"] == {"checked": 1, "failures": []}
    assert "target_scope=plan_final" in _failures(ng, "2")[0]


def test_previous_target_requires_previous_role():
    doc = _doc([_value(kind="previous_target")])
    ok = compare_document(doc, {"data": {"metrics": [_metric(revision_role="previous")]}}, "ok")
    ng = compare_document(doc, {"data": {"metrics": [_metric()]}}, "ok")
    assert _failures(ok, "3") == []
    assert "revision_role=current" in _failures(ng, "3")[0]
    assert ok["conditions"]["1"]["checked"] == 0  # 見直し前の目標は条件1の対象外


def test_actual_in_metrics_fails_condition_4_and_reference_is_checked():
    doc = _doc([_value(kind="actual", period_end="2025-03-31", value=900)])
    contaminated = {"data": {"metrics": [_metric(value=900, fiscal="2025/03")], "reference_values": []}}
    clean = {"data": {"metrics": [], "reference_values": [_ref()]}}
    assert _failures(compare_document(doc, contaminated, "ok"), "4")
    result = compare_document(doc, clean, "ok")
    assert _failures(result, "4") == []
    assert result["conditions"]["5"] == {"checked": 1, "failures": []}


def test_reference_kind_mismatch_fails_condition_5():
    doc = _doc([_value(kind="estimate", period_end="2026-03-31", value=900)])
    result = compare_document(doc, {"data": {"reference_values": [_ref(fiscal="2026/03", kind="actual")]}}, "ok")
    assert "kind=actual" in _failures(result, "5")[0]


def test_forecast_maps_to_forecast_kind():
    doc = _doc([_value(kind="company_forecast", period_end="2026-03-31", value=900)])
    result = compare_document(doc, {"data": {"reference_values": [_ref(fiscal="2026/03", kind="forecast")]}}, "ok")
    assert _failures(result, "5") == []


def test_8185_consolidation_is_checked():
    doc = _doc([_value(consolidation="non_consolidated")], code="8185")
    ng = compare_document(doc, {"data": {"metrics": [_metric(consolidation_label="consolidated")]}}, "ok")
    ok = compare_document(doc, {"data": {"metrics": [_metric(consolidation_label="non_consolidated")]}}, "ok")
    assert _failures(ng, "6") and _failures(ok, "6") == []


def test_segment_on_company_target_fails_condition_7_for_listed_codes():
    doc = _doc([_value()], code="4042")
    result = compare_document(doc, {"data": {"metrics": [_metric(segment="全社")]}}, "ok")
    assert _failures(result, "7")


@pytest.mark.parametrize("status,expected_failures", [("withdrawn", 0), ("ok", 1)])
def test_withdrawn_status_is_checked(status, expected_failures):
    result = compare_document(_doc([], status="withdrawn"), {"data": {"metrics": []}}, status)
    assert len(_failures(result, "8")) == expected_failures


def test_unmatched_company_metrics_are_listed():
    result = compare_document(_doc([_value()]), {"data": {"metrics": [_metric(), _metric(value=50, name="営業利益")]}}, "ok")
    assert len(result["unmatched_company_metrics"]) == 1
    assert "営業利益 50" in result["unmatched_company_metrics"][0]


def test_none_result_reports_missing():
    result = compare_document(_doc([_value()]), None, "failed")
    assert "missing" in _failures(result, "1")[0]


def test_summarize_counts_failures():
    docs = [{"comparison": compare_document(_doc([_value()]), {"data": {"metrics": []}}, "ok")}]
    assert summarize(docs)["1"] == {"checked": 1, "failed": 1}


def test_null_period_uses_label_year_to_separate_same_values():
    # 1941の見直し資料: 2027年度の現行目標と2030年度の見直し前目標が同じ2600
    doc = _doc([_value(period_end="2028-03-31", value=2600),
                _value(kind="previous_target", period_end="2031-03-31", value=2600)])
    metrics = [
        _metric(value=2600, fiscal=None, target_year=2027),
        _metric(value=2600, fiscal=None, target_year=2030, revision_role="previous", target_scope="long_term"),
    ]
    result = compare_document(doc, {"data": {"metrics": metrics}}, "ok")
    assert _failures(result, "1") == []
    assert _failures(result, "3") == []
    assert result["unmatched_company_metrics"] == []


def test_null_period_with_other_year_is_period_mismatch():
    doc = _doc([_value(period_end="2028-03-31")])
    result = compare_document(doc, {"data": {"metrics": [_metric(fiscal=None, target_year=2030)]}}, "ok")
    assert "period_mismatch" in _failures(result, "1")[0]


def test_reference_null_period_uses_period_label_year():
    doc = _doc([_value(kind="actual", period_end="2025-03-31", value=900)])
    ok = {"data": {"reference_values": [_ref(fiscal=None, period_label="2024年度実績")]}}
    ng = {"data": {"reference_values": [_ref(fiscal=None, period_label="2021年度実績")]}}
    assert _failures(compare_document(doc, ok, "ok"), "5") == []
    assert _failures(compare_document(doc, ng, "ok"), "5")
