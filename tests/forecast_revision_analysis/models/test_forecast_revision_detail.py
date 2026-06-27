from forecast_revision_analysis.models.forecast_revision_detail import ForecastRevisionDetail


class TestForecastRevisionDetail:

    def test_tablename(self):
        assert ForecastRevisionDetail.__tablename__ == "forecast_revision_details"

    def test_primary_keys(self):
        pk_cols = {col.name for col in ForecastRevisionDetail.__table__.primary_key.columns}
        assert pk_cols == {"code", "url"}

    def test_instantiation(self):
        detail = ForecastRevisionDetail(
            code="5803",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-06-18",
            prev_forecast_date="2026-02-13",
            value_unit="百万円",
            reason_raw="光コンポーネント製品のプロジェクト受注",
            direct_factors='["受注増加"]',
            structural_vulnerability='["光ファイバへの依存"]',
            spillover_conditions='["光ケーブルメーカー"]',
            llm_model="gemini-2.5-flash-lite",
            extraction_status="ok",
            extracted_at="2026-06-18 19:20:00",
        )
        assert detail.code == "5803"
        assert detail.url == "https://example.com/ir.pdf"
        assert detail.prev_forecast_date == "2026-02-13"
        assert detail.value_unit == "百万円"
        assert detail.extraction_status == "ok"

    def test_nullable_fields(self):
        """必須でないフィールドはNoneを許容する"""
        detail = ForecastRevisionDetail(code="5803", url="https://example.com/ir.pdf")
        assert detail.prev_forecast_date is None
        assert detail.value_unit is None
        assert detail.reason_raw is None
        assert detail.direct_factors is None
        assert detail.structural_vulnerability is None
        assert detail.spillover_conditions is None
        assert detail.extraction_status is None
