from typing import Any, Dict, Optional


def merge_stage_results(stage1_obj: Dict[str, Any], stage2_obj: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Stage1（抽出）とStage2（推論）の結果を、post_forecast_revision()が期待する現行shapeにマージする。

    Stage2が失敗（None）の場合でも、Stage1のデータ（periods/reason_raw等）は保存できるよう
    推論系フィールドをNoneのまま返す（詳細はdocs/forecast_revision_llm_pipeline_redesign.md §5）。
    """
    merged_data = dict(stage1_obj.get("data", {}))

    if stage2_obj is not None:
        merged_data.update(stage2_obj.get("data", {}))
    else:
        merged_data.setdefault("direct_factors", None)
        merged_data.setdefault("structural_vulnerability", None)
        merged_data.setdefault("spillover_conditions", None)

    return {"type": "FORECAST_REVISION", "data": merged_data}
