from forecast_revision_analysis.models.forecast_revision_metric import ForecastRevisionMetric


class TestForecastRevisionMetric:

    def test_tablename(self):
        assert ForecastRevisionMetric.__tablename__ == "forecast_revision_metrics"

    def test_primary_key(self):
        pk_cols = {col.name for col in ForecastRevisionMetric.__table__.primary_key.columns}
        assert pk_cols == {"id"}

    def test_instantiation(self):
        metric = ForecastRevisionMetric(
            url="https://example.com/ir.pdf",
            period_type="4q",
            metric_name="sales",
            label_raw="売上高",
            prev_value=594000.0,
            prev_value_upper=None,
            curr_value=778000.0,
            curr_value_upper=None,
            change_pct=31.0,
            is_modified=1,
        )
        assert metric.url == "https://example.com/ir.pdf"
        assert metric.period_type == "4q"
        assert metric.metric_name == "sales"
        assert metric.prev_value_upper is None
        assert metric.curr_value_upper is None
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
        """label_raw・数値フィールドはNoneを許容する"""
        metric = ForecastRevisionMetric(
            url="https://example.com/ir.pdf",
            period_type="2q",
            metric_name="net_income",
        )
        assert metric.label_raw is None
        assert metric.prev_value is None
        assert metric.prev_value_upper is None
        assert metric.curr_value is None
        assert metric.curr_value_upper is None
        assert metric.change_pct is None
        assert metric.is_modified is None
