from forecast_revision_analysis.models.forecast_revision_metric import ForecastRevisionMetric


class TestForecastRevisionMetric:

    def test_tablename(self):
        assert ForecastRevisionMetric.__tablename__ == "forecast_revision_metrics"

    def test_primary_key(self):
        pk_cols = {col.name for col in ForecastRevisionMetric.__table__.primary_key.columns}
        assert pk_cols == {"id"}

    def test_natural_key_unique_constraint(self):
        """url + period_type + fiscal_year + consolidation_type + metric_name の複合ユニーク制約がある"""
        constraints = [
            c for c in ForecastRevisionMetric.__table__.constraints
            if c.__class__.__name__ == "UniqueConstraint"
        ]
        assert len(constraints) == 1
        col_names = {col.name for col in constraints[0].columns}
        assert col_names == {"url", "period_type", "fiscal_year", "consolidation_type", "metric_name"}

    def test_instantiation(self):
        metric = ForecastRevisionMetric(
            url="https://example.com/ir.pdf",
            period_type="4q",
            fiscal_year=2026,
            consolidation_type="consolidated",
            metric_name="sales",
            label_raw="売上高",
            prev_value=594000.0,
            prev_value_upper=None,
            curr_value=778000.0,
            curr_value_upper=None,
            prev_year_actual=489000.0,
            change_pct=31.0,
            is_modified=1,
        )
        assert metric.url == "https://example.com/ir.pdf"
        assert metric.period_type == "4q"
        assert metric.fiscal_year == 2026
        assert metric.consolidation_type == "consolidated"
        assert metric.metric_name == "sales"
        assert metric.prev_value_upper is None
        assert metric.curr_value_upper is None
        assert metric.prev_year_actual == 489000.0
        assert metric.is_modified == 1

    def test_range_forecast(self):
        """レンジ予想の場合は upper フィールドに上限が入る"""
        metric = ForecastRevisionMetric(
            url="https://example.com/ir.pdf",
            period_type="4q",
            metric_name="net_income",
            prev_value=50000.0,
            prev_value_upper=60000.0,
            curr_value=55000.0,
            curr_value_upper=65000.0,
            change_pct=10.0,
            is_modified=1,
        )
        assert metric.prev_value_upper == 60000.0
        assert metric.curr_value_upper == 65000.0

    def test_nullable_fields(self):
        """label_raw・数値フィールド・fiscal_year・consolidation_typeはNoneを許容する"""
        metric = ForecastRevisionMetric(
            url="https://example.com/ir.pdf",
            period_type="2q",
            metric_name="net_income",
        )
        assert metric.fiscal_year is None
        assert metric.consolidation_type is None
        assert metric.label_raw is None
        assert metric.prev_value is None
        assert metric.prev_value_upper is None
        assert metric.curr_value is None
        assert metric.curr_value_upper is None
        assert metric.prev_year_actual is None
        assert metric.change_pct is None
        assert metric.is_modified is None
