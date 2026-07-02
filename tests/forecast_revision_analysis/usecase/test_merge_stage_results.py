from forecast_revision_analysis.usecase.merge_stage_results import merge_stage_results


def _stage1_obj():
    return {
        "type": "FORECAST_REVISION",
        "data": {
            "prev_forecast_date": "2026-02-13",
            "value_unit": "百万円",
            "periods": [{"period_type": "4q", "metric_name": "sales", "label_raw": "売上高"}],
            "reason_raw": "修正理由の原文",
        },
    }


def _stage2_obj():
    return {
        "type": "FORECAST_REVISION",
        "data": {
            "direct_factors": ["受注増加"],
            "structural_vulnerability": ["光ファイバへの依存"],
            "spillover_conditions": ["光ケーブルメーカー"],
        },
    }


class TestMergeStageResults:

    def test_merges_both_stages(self):
        merged = merge_stage_results(_stage1_obj(), _stage2_obj())
        assert merged["type"] == "FORECAST_REVISION"
        data = merged["data"]
        assert data["prev_forecast_date"] == "2026-02-13"
        assert data["reason_raw"] == "修正理由の原文"
        assert data["direct_factors"] == ["受注増加"]
        assert data["structural_vulnerability"] == ["光ファイバへの依存"]
        assert data["spillover_conditions"] == ["光ケーブルメーカー"]

    def test_stage1_fields_preserved_when_stage2_none(self):
        merged = merge_stage_results(_stage1_obj(), None)
        data = merged["data"]
        assert data["prev_forecast_date"] == "2026-02-13"
        assert data["periods"] == [{"period_type": "4q", "metric_name": "sales", "label_raw": "売上高"}]
        assert data["reason_raw"] == "修正理由の原文"

    def test_reasoning_fields_none_when_stage2_none(self):
        merged = merge_stage_results(_stage1_obj(), None)
        data = merged["data"]
        assert data["direct_factors"] is None
        assert data["structural_vulnerability"] is None
        assert data["spillover_conditions"] is None

    def test_stage1_data_not_mutated(self):
        """stage1_objの元データを破壊しない"""
        stage1 = _stage1_obj()
        merge_stage_results(stage1, _stage2_obj())
        assert "direct_factors" not in stage1["data"]
