import json
import pytest
from unittest.mock import MagicMock
from sqlalchemy.exc import IntegrityError

from forecast_revision_analysis.usecase.post_forecast_revision import post_forecast_revision, check_missing_fields, _calc_change_pct, _to_float, _to_int
from forecast_revision_analysis.models.forecast_revision_detail import ForecastRevisionDetail
from forecast_revision_analysis.models.forecast_revision_metric import ForecastRevisionMetric


def _make_data(periods=None, reason_raw="修正理由の原文", prev_forecast_date="2026-02-13", value_unit="百万円"):
    return {
        "type": "FORECAST_REVISION",
        "data": {
            "prev_forecast_date": prev_forecast_date,
            "value_unit": value_unit,
            "periods": periods if periods is not None else [
                {
                    "period_type": "4q",
                    "fiscal_year": 2026,
                    "consolidation_type": "consolidated",
                    "metric_name": "sales",
                    "label_raw": "売上高",
                    "prev_value": 594000.0,
                    "prev_value_upper": None,
                    "curr_value": 778000.0,
                    "curr_value_upper": None,
                    "prev_year_actual": 489000.0,
                    "is_modified": 1,
                }
            ],
            "reason_raw": reason_raw,
            "direct_factors": ["受注増加"],
            "structural_vulnerability": ["光ファイバへの依存"],
            "spillover_conditions": ["光ケーブルメーカー"],
        },
    }


class TestToFloat:

    def test_int(self):
        assert _to_float(500) == 500.0

    def test_float(self):
        assert _to_float(1.5) == 1.5

    def test_string_int(self):
        assert _to_float("500") == 500.0

    def test_string_float(self):
        assert _to_float("-47.72") == -47.72

    def test_none(self):
        assert _to_float(None) is None

    def test_invalid_string(self):
        assert _to_float("abc") is None


class TestToInt:

    def test_int(self):
        assert _to_int(2026) == 2026

    def test_string_int(self):
        assert _to_int("2026") == 2026

    def test_none(self):
        assert _to_int(None) is None

    def test_invalid_string(self):
        assert _to_int("abc") is None


class TestCalcChangePct:

    def test_normal(self):
        assert _calc_change_pct(100.0, 150.0) == 40.0

    def test_decrease(self):
        assert _calc_change_pct(200.0, 150.0) == -28.6

    def test_zero_prev_returns_200(self):
        assert _calc_change_pct(0.0, 100.0) == 200.0

    def test_both_zero_returns_zero(self):
        assert _calc_change_pct(0.0, 0.0) == 0.0

    def test_sign_crossing_positive_to_negative_returns_minus_200(self):
        assert _calc_change_pct(120.0, -145.0) == -200.0

    def test_sign_crossing_negative_to_positive_returns_200(self):
        assert _calc_change_pct(-100.0, 50.0) == 200.0

    def test_both_none_returns_none(self):
        assert _calc_change_pct(None, None) is None

    def test_prev_none_returns_none(self):
        assert _calc_change_pct(None, 100.0) is None

    def test_curr_none_returns_none(self):
        assert _calc_change_pct(100.0, None) is None

    def test_both_negative_worsening(self):
        assert _calc_change_pct(-100.0, -150.0) == -40.0

    def test_large_increase_bounded_near_200(self):
        assert _calc_change_pct(300.0, 394000.0) == 199.7


class TestPostForecastRevision:

    def test_normal_save(self):
        """detail 1件 + metric 1件が保存され、Trueを返す"""
        session = MagicMock()
        result = post_forecast_revision(
            session=session,
            data=_make_data(),
            code="5803",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18",
            extraction_status="ok",
        )
        assert result is True
        assert session.add.call_count == 2  # detail + 1 metric
        assert session.flush.called
        assert session.commit.called

    def test_detail_fields(self):
        """ForecastRevisionDetail のフィールドが正しくセットされる"""
        session = MagicMock()
        post_forecast_revision(
            session=session,
            data=_make_data(),
            code="5803",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18",
            extraction_status="ok",
        )
        detail = session.add.call_args_list[0][0][0]
        assert isinstance(detail, ForecastRevisionDetail)
        assert detail.code == "5803"
        assert detail.url == "https://example.com/ir.pdf"
        assert detail.disclosure_date == "2026-06-18"
        assert detail.prev_forecast_date == "2026-02-13"
        assert detail.value_unit == "百万円"
        assert detail.extraction_status == "ok"
        assert detail.reason_raw == "修正理由の原文"

    def test_prev_forecast_date_none(self):
        """prev_forecast_date が null の場合も正しく保存される"""
        session = MagicMock()
        post_forecast_revision(
            session=session,
            data=_make_data(prev_forecast_date=None),
            code="5803",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18",
            extraction_status="ok",
        )
        detail = session.add.call_args_list[0][0][0]
        assert detail.prev_forecast_date is None

    def test_json_array_fields_are_serialized(self):
        """direct_factors / structural_vulnerability / spillover_conditions がJSON文字列になる"""
        session = MagicMock()
        post_forecast_revision(
            session=session,
            data=_make_data(),
            code="5803",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18",
            extraction_status="ok",
        )
        detail = session.add.call_args_list[0][0][0]
        assert json.loads(detail.direct_factors) == ["受注増加"]
        assert json.loads(detail.structural_vulnerability) == ["光ファイバへの依存"]
        assert json.loads(detail.spillover_conditions) == ["光ケーブルメーカー"]

    def test_metric_fields(self):
        """ForecastRevisionMetric のフィールドが正しくセットされる"""
        session = MagicMock()
        post_forecast_revision(
            session=session,
            data=_make_data(),
            code="5803",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18",
            extraction_status="ok",
        )
        metric = session.add.call_args_list[1][0][0]
        assert isinstance(metric, ForecastRevisionMetric)
        assert metric.url == "https://example.com/ir.pdf"
        assert metric.period_type == "4q"
        assert metric.fiscal_year == 2026
        assert metric.consolidation_type == "consolidated"
        assert metric.metric_name == "sales"
        assert metric.prev_value == 594000.0
        assert metric.prev_value_upper is None
        assert metric.curr_value == 778000.0
        assert metric.curr_value_upper is None
        assert metric.prev_year_actual == 489000.0
        assert metric.change_pct == 26.8  # 2*(778000-594000)/(778000+594000)*100 = 26.8
        assert metric.is_modified == 1

    def test_range_forecast_metric_fields(self):
        """レンジ予想の upper フィールドが正しくセットされる"""
        session = MagicMock()
        periods = [
            {
                "period_type": "4q",
                "metric_name": "net_income",
                "label_raw": "当期純利益",
                "prev_value": 50000.0,
                "prev_value_upper": 60000.0,
                "curr_value": 55000.0,
                "curr_value_upper": 65000.0,
                "change_pct": 10.0,
                "is_modified": 1,
            }
        ]
        post_forecast_revision(
            session=session,
            data=_make_data(periods=periods),
            code="5803",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18",
            extraction_status="ok",
        )
        metric = session.add.call_args_list[1][0][0]
        assert metric.prev_value_upper == 60000.0
        assert metric.curr_value_upper == 65000.0

    def test_multiple_periods_saved(self):
        """periods が複数件あれば metric が同数保存される"""
        session = MagicMock()
        periods = [
            {"period_type": "2q", "metric_name": "sales", "label_raw": "売上高",
             "prev_value": 594000.0, "prev_value_upper": None,
             "curr_value": 778000.0, "curr_value_upper": None,
             "is_modified": 1},
            {"period_type": "4q", "metric_name": "bussiness_income", "label_raw": "営業利益",
             "prev_value": 92000.0, "prev_value_upper": None,
             "curr_value": 174000.0, "curr_value_upper": None,
             "is_modified": 1},
        ]
        post_forecast_revision(
            session=session,
            data=_make_data(periods=periods),
            code="5803",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18",
            extraction_status="ok",
        )
        assert session.add.call_count == 3  # detail + 2 metrics

    def test_no_periods_saves_detail_only(self):
        """periods が空でも detail は保存される"""
        session = MagicMock()
        post_forecast_revision(
            session=session,
            data=_make_data(periods=[]),
            code="5803",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18",
            extraction_status="no_periods",
        )
        assert session.add.call_count == 1  # detail のみ
        assert session.commit.called

    def test_withdrawn_empty_data(self):
        """取り下げ（data={}）でも detail が保存される"""
        session = MagicMock()
        post_forecast_revision(
            session=session,
            data={},
            code="5803",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18",
            extraction_status="withdrawn",
        )
        assert session.add.call_count == 1
        detail = session.add.call_args_list[0][0][0]
        assert detail.extraction_status == "withdrawn"
        assert detail.prev_forecast_date is None
        assert detail.reason_raw is None

    def test_none_data_does_not_save(self):
        """data が None の場合は何も保存せず False を返す"""
        session = MagicMock()
        result = post_forecast_revision(
            session=session,
            data=None,
            code="5803",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18",
            extraction_status="failed",
        )
        assert result is False
        assert not session.add.called
        assert not session.commit.called

    def test_integrity_error_returns_false(self):
        """主キー/自然キー重複はロールバックしFalseを返す（呼び出し元が保存失敗として検知できるように）"""
        session = MagicMock()
        session.flush.side_effect = IntegrityError("Duplicate key", None, None)

        result = post_forecast_revision(
            session=session,
            data=_make_data(),
            code="5803",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18",
            extraction_status="ok",
        )

        assert result is False
        session.rollback.assert_called()
        assert not session.commit.called

    def test_unexpected_error_returns_false(self):
        """予期しないエラーはロールバックしてFalseを返す"""
        session = MagicMock()
        session.commit.side_effect = Exception("unexpected")

        result = post_forecast_revision(
            session=session,
            data=_make_data(),
            code="5803",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18",
            extraction_status="ok",
        )

        assert result is False
        session.rollback.assert_called()

    def test_is_modified_overridden_when_values_equal(self):
        """prev_value == curr_value の場合、LLMのis_modifiedに関わらずコードが0に確定する"""
        session = MagicMock()
        periods = [
            {
                "period_type": "4q", "metric_name": "sales", "label_raw": "売上高",
                "prev_value": 1000.0, "prev_value_upper": None,
                "curr_value": 1000.0, "curr_value_upper": None,
                "is_modified": 1,  # LLMが誤って1を返しても
            }
        ]
        post_forecast_revision(
            session=session,
            data=_make_data(periods=periods),
            code="5803", url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18", extraction_status="ok",
        )
        metric = session.add.call_args_list[1][0][0]
        assert metric.is_modified == 0  # コードが0に上書きする

    def test_is_modified_1_when_values_differ(self):
        """prev_value != curr_value の場合は is_modified=1"""
        session = MagicMock()
        periods = [
            {
                "period_type": "4q", "metric_name": "sales", "label_raw": "売上高",
                "prev_value": 1000.0, "prev_value_upper": None,
                "curr_value": 1200.0, "curr_value_upper": None,
                "is_modified": 0,
            }
        ]
        post_forecast_revision(
            session=session,
            data=_make_data(periods=periods),
            code="5803", url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18", extraction_status="ok",
        )
        metric = session.add.call_args_list[1][0][0]
        assert metric.is_modified == 1

    def test_is_modified_0_when_both_none(self):
        """prev_value=None, curr_value=None は両値不明のため is_modified=0"""
        session = MagicMock()
        periods = [
            {
                "period_type": "4q", "metric_name": "eps", "label_raw": "EPS",
                "prev_value": None, "prev_value_upper": None,
                "curr_value": None, "curr_value_upper": None,
                "is_modified": 0,
            }
        ]
        post_forecast_revision(
            session=session,
            data=_make_data(periods=periods),
            code="5803", url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18", extraction_status="ok",
        )
        metric = session.add.call_args_list[1][0][0]
        assert metric.is_modified == 0

    def test_is_modified_1_when_prev_none_curr_set(self):
        """prev_value=None, curr_value に値がある場合は is_modified=1"""
        session = MagicMock()
        periods = [
            {
                "period_type": "2q", "metric_name": "dividend_per_share", "label_raw": "中間配当",
                "prev_value": None, "prev_value_upper": None,
                "curr_value": 0.0, "curr_value_upper": None,
                "is_modified": 1,
            }
        ]
        post_forecast_revision(
            session=session,
            data=_make_data(periods=periods),
            code="5803", url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18", extraction_status="ok",
        )
        metric = session.add.call_args_list[1][0][0]
        assert metric.is_modified == 1

    @pytest.mark.parametrize("status", ["ok", "no_periods", "failed", "withdrawn", "correction"])
    def test_extraction_status_values(self, status):
        """extraction_status の有効値がすべて保存できる"""
        session = MagicMock()
        post_forecast_revision(
            session=session,
            data=_make_data(),
            code="5803",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18",
            extraction_status=status,
        )
        detail = session.add.call_args_list[0][0][0]
        assert detail.extraction_status == status


class TestCheckMissingFields:

    def test_no_missing_returns_false(self):
        """全フィールドが揃っていれば False を返す"""
        assert check_missing_fields(_make_data(), "5803", "https://example.com/ir.pdf") is False

    def test_prev_forecast_date_none_returns_true(self):
        """prev_forecast_date が null なら True を返す"""
        assert check_missing_fields(
            _make_data(prev_forecast_date=None), "5803", "https://example.com/ir.pdf"
        ) is True

    @pytest.mark.parametrize("field", ["metric_name", "label_raw", "prev_value", "curr_value", "fiscal_year", "consolidation_type"])
    def test_period_required_field_none_returns_true(self, field):
        """period の必須フィールドが null なら True を返す"""
        period = {
            "period_type": "4q",
            "fiscal_year": 2026,
            "consolidation_type": "consolidated",
            "metric_name": "sales",
            "label_raw": "売上高",
            "prev_value": 1000.0,
            "prev_value_upper": None,
            "curr_value": 1200.0,
            "curr_value_upper": None,
            "is_modified": 1,
        }
        period[field] = None
        assert check_missing_fields(
            _make_data(periods=[period]), "5803", "https://example.com/ir.pdf"
        ) is True

    def test_empty_data_returns_true(self):
        """data={} (withdrawn/failed 相当) は prev_forecast_date=null として True を返す"""
        assert check_missing_fields({}, "5803", "https://example.com/ir.pdf") is True

    def test_empty_periods_with_prev_date_returns_false(self):
        """periods が空でも prev_forecast_date があれば False を返す"""
        assert check_missing_fields(
            _make_data(periods=[]), "5803", "https://example.com/ir.pdf"
        ) is False
