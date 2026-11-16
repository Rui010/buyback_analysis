from sqlalchemy import inspect

from buyback_analysis.models.buyback_plan_projection import BuybackPlanProjection


def test_projection_is_one_row_per_plan_and_contains_recalculation_metadata():
    mapper = inspect(BuybackPlanProjection)
    columns = {column.name for column in mapper.columns}

    assert [column.name for column in mapper.primary_key] == ["buyback_plan_id"]
    assert {
        "original_shares",
        "original_amount_yen",
        "current_shares",
        "current_amount_yen",
        "cumulative_shares_acquired",
        "cumulative_amount_spent_yen",
        "completion_shares_acquired",
        "completion_amount_spent_yen",
        "plan_status",
        "lifecycle_status",
        "is_publishable",
        "input_fingerprint",
        "aggregation_rule_version",
        "calculated_at",
    } <= columns
