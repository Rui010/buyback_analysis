import pytest
from pydantic import ValidationError

from forecast_revision_analysis.usecase.schemas import (
    PeriodExtraction,
    Stage1Extraction,
    Stage2Inference,
)


class TestPeriodExtraction:

    def test_valid_period(self):
        period = PeriodExtraction(
            period_type="4q",
            fiscal_year=2026,
            consolidation_type="consolidated",
            metric_name="sales",
            label_raw="売上高",
            prev_value=594000.0,
            curr_value=778000.0,
        )
        assert period.period_type == "4q"
        assert period.consolidation_type == "consolidated"
        assert period.metric_name == "sales"

    def test_optional_fields_default_none(self):
        period = PeriodExtraction(
            period_type="4q", metric_name="sales", label_raw="売上高"
        )
        assert period.fiscal_year is None
        assert period.consolidation_type is None
        assert period.prev_value is None
        assert period.prev_value_upper is None
        assert period.curr_value is None
        assert period.curr_value_upper is None
        assert period.prev_year_actual is None

    def test_invalid_period_type_rejected(self):
        with pytest.raises(ValidationError):
            PeriodExtraction(period_type="5q", metric_name="sales", label_raw="売上高")

    def test_invalid_metric_name_rejected(self):
        with pytest.raises(ValidationError):
            PeriodExtraction(period_type="4q", metric_name="unknown_metric", label_raw="売上高")

    def test_invalid_consolidation_type_rejected(self):
        with pytest.raises(ValidationError):
            PeriodExtraction(
                period_type="4q",
                metric_name="sales",
                label_raw="売上高",
                consolidation_type="both",
            )

    def test_missing_required_field_rejected(self):
        with pytest.raises(ValidationError):
            PeriodExtraction(period_type="4q", metric_name="sales")  # label_raw欠落


class TestStage1Extraction:

    def test_valid_extraction(self):
        obj = Stage1Extraction(
            prev_forecast_date="2026-02-13",
            value_unit="百万円",
            periods=[
                {
                    "period_type": "4q",
                    "fiscal_year": 2026,
                    "consolidation_type": "consolidated",
                    "metric_name": "sales",
                    "label_raw": "売上高",
                    "prev_value": 594000.0,
                    "curr_value": 778000.0,
                }
            ],
            reason_raw="修正理由の原文",
        )
        assert len(obj.periods) == 1
        assert obj.periods[0].metric_name == "sales"

    def test_all_optional_fields_default(self):
        obj = Stage1Extraction()
        assert obj.prev_forecast_date is None
        assert obj.value_unit is None
        assert obj.periods == []
        assert obj.reason_raw is None

    def test_no_is_modified_field(self):
        """is_modifiedはStage1スキーマに含まれない（コード側で確定するため）"""
        assert "is_modified" not in Stage1Extraction.model_fields
        assert "is_modified" not in PeriodExtraction.model_fields


class TestStage2Inference:

    def test_valid_inference(self):
        obj = Stage2Inference(
            direct_factors=["受注増加"],
            structural_vulnerability=["光ファイバへの依存"],
            spillover_conditions=["光ケーブルメーカー"],
        )
        assert obj.direct_factors == ["受注増加"]

    def test_empty_lists_allowed(self):
        obj = Stage2Inference(direct_factors=[], structural_vulnerability=[], spillover_conditions=[])
        assert obj.direct_factors == []

    def test_all_fields_default_empty(self):
        obj = Stage2Inference()
        assert obj.direct_factors == []
        assert obj.structural_vulnerability == []
        assert obj.spillover_conditions == []
