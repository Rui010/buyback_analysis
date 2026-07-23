from earnings_baseline_analysis.models.earnings_baseline import EarningsBaseline


class TestEarningsBaseline:

    def test_tablename(self):
        assert EarningsBaseline.__tablename__ == "earnings_baselines"

    def test_primary_keys(self):
        pk_cols = {col.name for col in EarningsBaseline.__table__.primary_key.columns}
        assert pk_cols == {"code", "url"}

    def test_instantiation(self):
        baseline = EarningsBaseline(
            code="2168",
            url="https://example.com/ir.pdf",
            disclosure_date="2026-05-13",
            fiscal_year_actual=2026,
            fiscal_year_forecast=2027,
            llm_model="gemini-3.1-flash-lite",
            extraction_status="ok",
            extracted_at="2026-05-13 19:20:00",
        )
        assert baseline.code == "2168"
        assert baseline.url == "https://example.com/ir.pdf"
        assert baseline.disclosure_date == "2026-05-13"
        assert baseline.fiscal_year_actual == 2026
        assert baseline.fiscal_year_forecast == 2027
        assert baseline.extraction_status == "ok"

    def test_nullable_fields(self):
        """必須でないフィールドはNoneを許容する"""
        baseline = EarningsBaseline(code="2168", url="https://example.com/ir.pdf")
        assert baseline.disclosure_date is None
        assert baseline.fiscal_year_actual is None
        assert baseline.fiscal_year_forecast is None
        assert baseline.llm_model is None
        assert baseline.extraction_status is None
        assert baseline.extracted_at is None
