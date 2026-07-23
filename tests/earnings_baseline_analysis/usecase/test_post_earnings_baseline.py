import pytest
from unittest.mock import MagicMock
from sqlalchemy.exc import IntegrityError

from earnings_baseline_analysis.usecase.post_earnings_baseline import (
    post_earnings_baseline,
    _to_float,
    _to_int,
    _deduplicate_metrics,
)
from earnings_baseline_analysis.models.earnings_baseline import EarningsBaseline
from earnings_baseline_analysis.models.earnings_baseline_metric import EarningsBaselineMetric


def _make_data(actual_metrics=None, initial_forecast_metrics=None, fiscal_year_actual=2026, fiscal_year_forecast=2027):
    return {
        "type": "EARNINGS_BASELINE",
        "data": {
            "fiscal_year_actual": fiscal_year_actual,
            "fiscal_year_forecast": fiscal_year_forecast,
            "actual_metrics": actual_metrics if actual_metrics is not None else [
                {
                    "metric_name": "sales",
                    "period_type": "4q",
                    "consolidation_type": "consolidated",
                    "label_raw": "売上高",
                    "value": 594000.0,
                },
            ],
            "initial_forecast_metrics": initial_forecast_metrics if initial_forecast_metrics is not None else [
                {
                    "metric_name": "sales",
                    "period_type": "4q",
                    "consolidation_type": "consolidated",
                    "label_raw": "売上高",
                    "value": 650000.0,
                    "value_upper": None,
                },
            ],
        },
    }


class TestToFloat:

    def test_int(self):
        assert _to_float(500) == 500.0

    def test_string_float(self):
        assert _to_float("650000.0") == 650000.0

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


class TestDeduplicateMetrics:

    def test_no_duplicates_returns_all(self):
        items = [
            ({"period_type": "4q", "consolidation_type": "consolidated", "metric_name": "sales"}, "actual", 2026),
            ({"period_type": "4q", "consolidation_type": "consolidated", "metric_name": "net_income"}, "actual", 2026),
        ]
        result = _deduplicate_metrics(items, "2168", "https://example.com/ir.pdf")
        assert len(result) == 2

    def test_duplicate_natural_key_keeps_first_occurrence_when_no_tiebreaker_applies(self):
        """net_income以外は判定材料がないため先に出現した方を採用する"""
        first = ({"period_type": "4q", "consolidation_type": "consolidated", "metric_name": "sales", "label_raw": "売上高（1回目）"}, "actual", 2026)
        second = ({"period_type": "4q", "consolidation_type": "consolidated", "metric_name": "sales", "label_raw": "売上高（2回目）"}, "actual", 2026)
        result = _deduplicate_metrics([first, second], "2168", "https://example.com/ir.pdf")
        assert len(result) == 1
        assert result[0][0]["label_raw"] == "売上高（1回目）"

    def test_net_income_duplicate_prefers_parent_attributable(self):
        """net_income重複時、「親会社」を含むlabel_rawを優先する"""
        total = ({"period_type": "4q", "consolidation_type": "consolidated", "metric_name": "net_income", "label_raw": "当期利益"}, "actual", 2026)
        parent = ({"period_type": "4q", "consolidation_type": "consolidated", "metric_name": "net_income", "label_raw": "親会社の所有者に帰属する当期利益"}, "actual", 2026)
        result = _deduplicate_metrics([total, parent], "8725", "https://example.com/ir.pdf")
        assert len(result) == 1
        assert result[0][0]["label_raw"] == "親会社の所有者に帰属する当期利益"

    def test_different_value_type_not_deduplicated(self):
        """value_typeが異なれば別自然キーとして両方残る（actual/initial_forecastは別行）"""
        actual = ({"period_type": "4q", "consolidation_type": "consolidated", "metric_name": "sales"}, "actual", 2026)
        forecast = ({"period_type": "4q", "consolidation_type": "consolidated", "metric_name": "sales"}, "initial_forecast", 2027)
        result = _deduplicate_metrics([actual, forecast], "2168", "https://example.com/ir.pdf")
        assert len(result) == 2

    def test_empty_list_returns_empty(self):
        assert _deduplicate_metrics([], "2168", "https://example.com/ir.pdf") == []


class TestPostEarningsBaseline:

    def test_normal_save(self):
        """baseline 1件 + actual metric 1件 + initial_forecast metric 1件が保存され、Trueを返す"""
        session = MagicMock()
        result = post_earnings_baseline(
            session=session,
            data=_make_data(),
            code="2168",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-05-13",
            extraction_status="ok",
        )
        assert result is True
        assert session.add.call_count == 3  # baseline + actual + initial_forecast
        assert session.flush.called
        assert session.commit.called

    def test_baseline_fields(self):
        """EarningsBaseline のフィールドが正しくセットされる"""
        session = MagicMock()
        post_earnings_baseline(
            session=session,
            data=_make_data(),
            code="2168",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-05-13",
            extraction_status="ok",
        )
        baseline = session.add.call_args_list[0][0][0]
        assert isinstance(baseline, EarningsBaseline)
        assert baseline.code == "2168"
        assert baseline.url == "https://example.com/ir.pdf"
        assert baseline.disclosure_date == "2026-05-13"
        assert baseline.fiscal_year_actual == 2026
        assert baseline.fiscal_year_forecast == 2027
        assert baseline.extraction_status == "ok"

    def test_actual_metric_fields(self):
        """actual_metrics の行が value_type=actual・fiscal_year_actual で保存される"""
        session = MagicMock()
        post_earnings_baseline(
            session=session,
            data=_make_data(),
            code="2168",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-05-13",
            extraction_status="ok",
        )
        metric = session.add.call_args_list[1][0][0]
        assert isinstance(metric, EarningsBaselineMetric)
        assert metric.code == "2168"
        assert metric.url == "https://example.com/ir.pdf"
        assert metric.fiscal_year == 2026
        assert metric.period_type == "4q"
        assert metric.consolidation_type == "consolidated"
        assert metric.metric_name == "sales"
        assert metric.value_type == "actual"
        assert metric.value == 594000.0
        assert metric.value_upper is None

    def test_initial_forecast_metric_fields(self):
        """initial_forecast_metrics の行が value_type=initial_forecast・fiscal_year_forecast で保存される"""
        session = MagicMock()
        post_earnings_baseline(
            session=session,
            data=_make_data(),
            code="2168",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-05-13",
            extraction_status="ok",
        )
        metric = session.add.call_args_list[2][0][0]
        assert metric.fiscal_year == 2027
        assert metric.value_type == "initial_forecast"
        assert metric.value == 650000.0

    def test_range_forecast_metric_fields(self):
        """レンジ予想の value_upper が正しくセットされる"""
        session = MagicMock()
        initial_forecast_metrics = [
            {
                "metric_name": "net_income",
                "period_type": "4q",
                "consolidation_type": "consolidated",
                "label_raw": "当期純利益",
                "value": 50000.0,
                "value_upper": 60000.0,
            }
        ]
        post_earnings_baseline(
            session=session,
            data=_make_data(initial_forecast_metrics=initial_forecast_metrics),
            code="2168",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-05-13",
            extraction_status="ok",
        )
        metric = session.add.call_args_list[2][0][0]
        assert metric.value == 50000.0
        assert metric.value_upper == 60000.0

    def test_multiple_metrics_saved(self):
        """複数のmetricが同数保存される"""
        session = MagicMock()
        actual_metrics = [
            {"metric_name": "sales", "period_type": "4q", "consolidation_type": "consolidated", "label_raw": "売上高", "value": 594000.0},
            {"metric_name": "bussiness_income", "period_type": "4q", "consolidation_type": "consolidated", "label_raw": "営業利益", "value": 92000.0},
        ]
        post_earnings_baseline(
            session=session,
            data=_make_data(actual_metrics=actual_metrics),
            code="2168",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-05-13",
            extraction_status="ok",
        )
        assert session.add.call_count == 4  # baseline + 2 actual + 1 initial_forecast

    def test_duplicate_natural_key_metrics_saved_without_crash(self):
        """actual_metrics内に自然キー重複があってもクラッシュせず1件だけ保存される（IntegrityError回避）"""
        session = MagicMock()
        actual_metrics = [
            {"metric_name": "net_income", "period_type": "4q", "consolidation_type": "consolidated", "label_raw": "当期利益", "value": 470000.0},
            {"metric_name": "net_income", "period_type": "4q", "consolidation_type": "consolidated", "label_raw": "親会社の所有者に帰属する当期利益", "value": 420000.0},
        ]
        result = post_earnings_baseline(
            session=session,
            data=_make_data(actual_metrics=actual_metrics),
            code="8725",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-05-13",
            extraction_status="ok",
        )
        assert result is True
        # baseline + 1 actual metric（重複除去後）+ 1 initial_forecast metric（デフォルト値・別自然キーのため残る）
        assert session.add.call_count == 3
        metrics = [session.add.call_args_list[1][0][0], session.add.call_args_list[2][0][0]]
        actual_metric = next(m for m in metrics if m.value_type == "actual")
        assert actual_metric.label_raw == "親会社の所有者に帰属する当期利益"  # net_incomeは親会社帰属分を優先
        session.commit.assert_called()
        assert not session.rollback.called

    def test_no_metrics_saves_baseline_only(self):
        """metricsが空でもbaselineは保存される"""
        session = MagicMock()
        post_earnings_baseline(
            session=session,
            data=_make_data(actual_metrics=[], initial_forecast_metrics=[]),
            code="2168",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-05-13",
            extraction_status="no_data",
        )
        assert session.add.call_count == 1  # baseline のみ
        assert session.commit.called

    def test_none_data_does_not_save(self):
        """data が None の場合は何も保存せず False を返す"""
        session = MagicMock()
        result = post_earnings_baseline(
            session=session,
            data=None,
            code="2168",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-05-13",
            extraction_status="failed",
        )
        assert result is False
        assert not session.add.called
        assert not session.commit.called

    def test_integrity_error_returns_false(self):
        """主キー/自然キー重複はロールバックしFalseを返す"""
        session = MagicMock()
        session.flush.side_effect = IntegrityError("Duplicate key", None, None)

        result = post_earnings_baseline(
            session=session,
            data=_make_data(),
            code="2168",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-05-13",
            extraction_status="ok",
        )

        assert result is False
        session.rollback.assert_called()
        assert not session.commit.called

    def test_unexpected_error_returns_false(self):
        """予期しないエラーはロールバックしてFalseを返す"""
        session = MagicMock()
        session.commit.side_effect = Exception("unexpected")

        result = post_earnings_baseline(
            session=session,
            data=_make_data(),
            code="2168",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-05-13",
            extraction_status="ok",
        )

        assert result is False
        session.rollback.assert_called()

    @pytest.mark.parametrize("status", ["ok", "no_data", "failed"])
    def test_extraction_status_values(self, status):
        """extraction_status の有効値がすべて保存できる"""
        session = MagicMock()
        post_earnings_baseline(
            session=session,
            data=_make_data(),
            code="2168",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-05-13",
            extraction_status=status,
        )
        baseline = session.add.call_args_list[0][0][0]
        assert baseline.extraction_status == status
