from earnings_baseline_analysis.models.earnings_baseline_metric import EarningsBaselineMetric


class TestEarningsBaselineMetric:

    def test_tablename(self):
        assert EarningsBaselineMetric.__tablename__ == "earnings_baseline_metrics"

    def test_primary_key(self):
        pk_cols = {col.name for col in EarningsBaselineMetric.__table__.primary_key.columns}
        assert pk_cols == {"id"}

    def test_natural_key_unique_constraint(self):
        """code + fiscal_year + period_type + consolidation_type + metric_name + value_type の複合ユニーク制約がある"""
        constraints = [
            c for c in EarningsBaselineMetric.__table__.constraints
            if c.__class__.__name__ == "UniqueConstraint"
        ]
        assert len(constraints) == 1
        col_names = {col.name for col in constraints[0].columns}
        assert col_names == {
            "code", "fiscal_year", "period_type", "consolidation_type", "metric_name", "value_type",
        }

    def test_instantiation(self):
        metric = EarningsBaselineMetric(
            code="2168",
            url="https://example.com/ir.pdf",
            fiscal_year=2026,
            period_type="4q",
            consolidation_type="consolidated",
            metric_name="sales",
            value_type="actual",
            label_raw="売上高",
            value=594000.0,
            value_upper=None,
        )
        assert metric.code == "2168"
        assert metric.url == "https://example.com/ir.pdf"
        assert metric.fiscal_year == 2026
        assert metric.period_type == "4q"
        assert metric.consolidation_type == "consolidated"
        assert metric.metric_name == "sales"
        assert metric.value_type == "actual"
        assert metric.value == 594000.0
        assert metric.value_upper is None

    def test_range_forecast(self):
        """レンジ予想の場合は value_upper に上限が入る"""
        metric = EarningsBaselineMetric(
            code="2168",
            url="https://example.com/ir.pdf",
            period_type="4q",
            metric_name="net_income",
            value_type="initial_forecast",
            value=50000.0,
            value_upper=60000.0,
        )
        assert metric.value == 50000.0
        assert metric.value_upper == 60000.0

    def test_nullable_fields(self):
        """label_raw・数値フィールド・fiscal_year・consolidation_typeはNoneを許容する"""
        metric = EarningsBaselineMetric(
            code="2168",
            url="https://example.com/ir.pdf",
            period_type="2q",
            metric_name="net_income",
            value_type="actual",
        )
        assert metric.fiscal_year is None
        assert metric.consolidation_type is None
        assert metric.label_raw is None
        assert metric.value is None
        assert metric.value_upper is None
