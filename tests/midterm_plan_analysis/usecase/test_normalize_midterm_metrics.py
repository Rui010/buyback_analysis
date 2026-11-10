from unittest.mock import patch

import pytest

from midterm_plan_analysis.usecase.normalize_midterm_metrics import (
    normalize_midterm_result,
    parse_number,
)

MODULE = "midterm_plan_analysis.usecase.normalize_midterm_metrics"


def _result(metrics=None, reference_values=None, **plan):
    data = {"plan_end_year": 2027, "plan_end_period_label": "2027年度", "plan_end_fiscal_end": "2028/03"}
    data.update(plan)
    if metrics is not None:
        data["metrics"] = metrics
    if reference_values is not None:
        data["reference_values"] = reference_values
    return {"type": "MIDTERM_PLAN", "data": data}


def _metric(**overrides):
    metric = {
        "name": "売上高", "value": 500, "unit": "億円", "target_year": 2027,
        "target_period_label": "2027年度", "target_fiscal_end": "2028/03",
        "target_scope": "plan_final", "revision_role": "current", "consolidation_label": None,
        "bound": "exact", "value_upper": None, "value_text": "500", "page": 3,
    }
    metric.update(overrides)
    return metric


def _normalize_one(page_available=True, **overrides):
    result = normalize_midterm_result(_result(metrics=[_metric(**overrides)]), page_available=page_available)
    return result["data"]["metrics"][0]


class TestParseNumber:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (500, 500), (12.5, 12.5), ("500", 500), ("1,234", 1234), ("１８0", 180),
            ("12.5", 12.5), ("△9", -9), ("▲9", -9), ("-9", -9), ("−9", -9), (" 7.0 ", 7.0),
        ],
    )
    def test_parses_plain_numbers(self, raw, expected):
        assert parse_number(raw) == expected

    @pytest.mark.parametrize("raw", [None, True, "", "未定", "7.0以上", "5〜7", "約100", "abc"])
    def test_returns_none_for_non_numbers(self, raw):
        assert parse_number(raw) is None


class TestValueNormalization:
    def test_numeric_value_is_kept(self):
        assert _normalize_one(value=500)["value"] == 500

    def test_numeric_string_is_converted_and_text_kept(self):
        metric = _normalize_one(value="１８0", value_text=None)
        assert metric["value"] == 180
        assert metric["value_text"] == "１８0"

    def test_existing_value_text_is_not_overwritten(self):
        metric = _normalize_one(value="1,000", value_text="1,000億円")
        assert metric["value"] == 1000
        assert metric["value_text"] == "1,000億円"

    @pytest.mark.parametrize(
        "raw,value,bound",
        [("7.0以上", 7.0, "lower"), ("10%以下", 10, "upper"), ("5未満", 5, "upper"),
         ("100程度", 100, "approx"), ("約100", 100, "approx")],
    )
    def test_qualified_string_sets_value_and_missing_bound(self, raw, value, bound):
        metric = _normalize_one(value=raw, value_text=None, bound=None)
        assert metric["value"] == value
        assert metric["bound"] == bound
        assert metric["value_text"] == raw

    def test_qualified_string_keeps_valid_llm_bound(self):
        assert _normalize_one(value="7.0以上", bound="approx")["bound"] == "approx"

    def test_range_string_sets_lower_and_upper(self):
        metric = _normalize_one(value="5〜7", value_text=None, bound=None, value_upper=None)
        assert (metric["value"], metric["value_upper"], metric["bound"]) == (5, 7, "range")

    def test_unparseable_string_becomes_null_and_text_kept(self):
        metric = _normalize_one(value="未定", value_text=None)
        assert metric["value"] is None
        assert metric["value_text"] == "未定"

    def test_bool_value_becomes_null(self):
        assert _normalize_one(value=True)["value"] is None


class TestAttributeNormalization:
    def test_valid_attributes_are_kept(self):
        metric = _normalize_one(target_scope="long_term", revision_role="previous",
                                consolidation_label="consolidated", bound="lower")
        assert (metric["target_scope"], metric["revision_role"], metric["consolidation_label"], metric["bound"]) == (
            "long_term", "previous", "consolidated", "lower"
        )

    def test_missing_attributes_are_filled(self):
        metric = normalize_midterm_result(
            _result(metrics=[{"name": "売上高", "value": 500, "unit": "億円"}]), page_available=True
        )["data"]["metrics"][0]
        assert metric["target_scope"] == "unknown"
        assert metric["revision_role"] == "current"
        assert metric["consolidation_label"] is None
        assert metric["bound"] is None
        assert metric["value_upper"] is None
        assert metric["value_text"] is None
        assert metric["page"] is None

    @pytest.mark.parametrize(
        "field,raw,expected",
        [("target_scope", "final", "unknown"), ("revision_role", "old", "current"),
         ("consolidation_label", "group", None),
         ("bound", "min", "exact")],  # 不正なboundはvalue_text（"500"）から導く
    )
    def test_invalid_attributes_are_replaced(self, field, raw, expected):
        assert _normalize_one(**{field: raw})[field] == expected

    @pytest.mark.parametrize("raw,expected", [("連結", "consolidated"), ("単体", "non_consolidated"),
                                              ("個別", "non_consolidated")])
    def test_japanese_consolidation_label_is_mapped(self, raw, expected):
        assert _normalize_one(consolidation_label=raw)["consolidation_label"] == expected

    def test_value_upper_is_cleared_unless_range(self):
        assert _normalize_one(bound="lower", value_upper=10)["value_upper"] is None
        assert _normalize_one(bound="range", value_upper="１０")["value_upper"] == 10

    @pytest.mark.parametrize("scope", ["plan_final", "plan_interim", "long_term"])
    def test_scope_is_unknown_without_plan_period(self, scope):
        result = normalize_midterm_result(
            _result(metrics=[_metric(target_scope=scope)], plan_end_year=None,
                    plan_end_period_label=None, plan_end_fiscal_end=None),
            page_available=True,
        )
        assert result["data"]["metrics"][0]["target_scope"] == "unknown"

    def test_cumulative_scope_is_kept_without_plan_period(self):
        result = normalize_midterm_result(
            _result(metrics=[_metric(target_scope="cumulative")], plan_end_year=None,
                    plan_end_period_label=None, plan_end_fiscal_end=None),
            page_available=True,
        )
        assert result["data"]["metrics"][0]["target_scope"] == "cumulative"

    def test_page_is_kept_when_available(self):
        assert _normalize_one(page="3")["page"] == 3

    @pytest.mark.parametrize("raw", [0, -1, "p.3", 2.5, True])
    def test_invalid_page_becomes_null(self, raw):
        assert _normalize_one(page=raw)["page"] is None

    def test_page_is_null_when_input_has_no_page_breaks(self):
        assert _normalize_one(page_available=False, page=3)["page"] is None

    @pytest.mark.parametrize("raw", [None, ""])
    def test_empty_segment_is_removed(self, raw):
        assert "segment" not in _normalize_one(segment=raw)

    def test_segment_name_is_kept(self):
        assert _normalize_one(segment="デジタル事業")["segment"] == "デジタル事業"

    def test_unknown_extra_fields_are_kept(self):
        assert _normalize_one(note="注記")["note"] == "注記"


class TestReferenceValues:
    def _reference(self, **overrides):
        ref = {"name": "売上高", "value": 450, "unit": "億円", "kind": "actual",
               "period_label": "2024年度実績", "period_fiscal_end": "2025/03",
               "consolidation_label": None, "value_text": "450", "page": 3}
        ref.update(overrides)
        return ref

    def _normalize(self, page_available=True, **overrides):
        result = normalize_midterm_result(
            _result(metrics=[], reference_values=[self._reference(**overrides)]), page_available=page_available
        )
        return result["data"]["reference_values"][0]

    def test_missing_reference_values_become_empty_list(self):
        assert normalize_midterm_result(_result(metrics=[]), page_available=True)["data"]["reference_values"] == []

    def test_non_list_reference_values_become_empty_list(self):
        result = normalize_midterm_result(_result(metrics=[], reference_values="なし"), page_available=True)
        assert result["data"]["reference_values"] == []

    @pytest.mark.parametrize("raw,expected", [("actual", "actual"), ("estimate", "estimate"),
                                              ("forecast", "forecast"), ("実績", "actual"),
                                              ("見込", "estimate"), ("予想", "forecast"),
                                              (None, "unknown"), ("budget", "unknown")])
    def test_kind_is_normalized(self, raw, expected):
        assert self._normalize(kind=raw)["kind"] == expected

    def test_value_and_page_are_normalized(self):
        ref = self._normalize(value="△9", value_text=None, page="11")
        assert (ref["value"], ref["value_text"], ref["page"]) == (-9, "△9", 11)

    def test_page_is_null_without_page_breaks(self):
        assert self._normalize(page_available=False)["page"] is None

    def test_missing_fields_are_filled(self):
        result = normalize_midterm_result(
            _result(metrics=[], reference_values=[{"name": "売上高", "value": 450}]), page_available=True
        )
        ref = result["data"]["reference_values"][0]
        for field in ("unit", "consolidation_label", "page", "value_text", "period_label", "period_fiscal_end"):
            assert ref[field] is None
        assert ref["kind"] == "unknown"
        assert "segment" not in ref


class TestResultShape:
    def test_none_result_is_returned_as_is(self):
        assert normalize_midterm_result(None, page_available=True) is None

    def test_original_result_is_not_mutated(self):
        original = _result(metrics=[_metric(value="500")])
        normalize_midterm_result(original, page_available=True)
        assert original["data"]["metrics"][0]["value"] == "500"
        assert "reference_values" not in original["data"]

    def test_null_metrics_stay_null(self):
        result = normalize_midterm_result({"type": "MIDTERM_PLAN", "data": {"metrics": None}}, page_available=True)
        assert result["data"]["metrics"] is None
        assert result["data"]["reference_values"] == []

    def test_non_dict_metric_items_are_dropped(self):
        result = normalize_midterm_result(_result(metrics=["売上高500億円", _metric()]), page_available=True)
        assert len(result["data"]["metrics"]) == 1

    def test_plan_fields_are_unchanged(self):
        result = normalize_midterm_result(_result(metrics=[], plan_name="中計2027"), page_available=True)
        assert result["data"]["plan_name"] == "中計2027"
        assert result["type"] == "MIDTERM_PLAN"


class TestDuplicateWarning:
    def test_warns_when_same_value_is_in_both_arrays(self):
        result = _result(
            metrics=[_metric(name="売上高", value=500, unit="億円", target_period_label="2027年度")],
            reference_values=[{"name": "売上高", "value": 500, "unit": "億円", "period_label": "2027年度",
                               "kind": "forecast"}],
        )
        with patch(f"{MODULE}.logger") as logger:
            normalize_midterm_result(result, page_available=True, log_context="1234 - https://x/a.pdf")
        logger.info.assert_called_once()
        message = logger.info.call_args[0][0]
        assert message.startswith("[WARNING]") and "https://x/a.pdf" in message

    def test_no_warning_for_different_periods(self):
        result = _result(
            metrics=[_metric(name="売上高", value=500, unit="億円", target_period_label="2027年度")],
            reference_values=[{"name": "売上高", "value": 500, "unit": "億円", "period_label": "2024年度",
                               "kind": "actual"}],
        )
        with patch(f"{MODULE}.logger") as logger:
            normalize_midterm_result(result, page_available=True)
        logger.info.assert_not_called()
