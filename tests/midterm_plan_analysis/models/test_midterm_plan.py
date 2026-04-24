import pytest
from midterm_plan_analysis.models.midterm_plan import MidtermPlan


class TestMidtermPlan:

    def test_tablename(self):
        assert MidtermPlan.__tablename__ == "midterm_plans"

    def test_primary_keys(self):
        pk_cols = {col.name for col in MidtermPlan.__table__.primary_key.columns}
        assert pk_cols == {"code", "url"}

    def test_instantiation(self):
        """モデルのインスタンス化と属性セットを確認"""
        plan = MidtermPlan(
            code="1234",
            url="https://example.com/plan.pdf",
            plan_name="2027中期経営計画",
            plan_start_year=2025,
            plan_end_year=2027,
            disclosure_date="2025-04-18",
            metrics='[{"name": "ROE", "value": 12, "unit": "%", "target_year": 2027}]',
        )
        assert plan.code == "1234"
        assert plan.url == "https://example.com/plan.pdf"
        assert plan.plan_end_year == 2027

    def test_nullable_fields(self):
        """必須でないフィールドはNoneを許容する"""
        plan = MidtermPlan(code="1234", url="https://example.com/plan.pdf")
        assert plan.plan_name is None
        assert plan.metrics is None
