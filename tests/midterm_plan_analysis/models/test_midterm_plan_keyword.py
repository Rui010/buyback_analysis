from midterm_plan_analysis.models.midterm_plan_keyword import MidtermPlanKeyword


class TestMidtermPlanKeyword:

    def test_tablename(self):
        assert MidtermPlanKeyword.__tablename__ == "midterm_plan_keywords"

    def test_primary_key(self):
        pk_cols = {col.name for col in MidtermPlanKeyword.__table__.primary_key.columns}
        assert pk_cols == {"id"}

    def test_natural_key_unique_constraint(self):
        """code + url + keyword の複合ユニーク制約がある"""
        constraints = [
            c for c in MidtermPlanKeyword.__table__.constraints
            if c.__class__.__name__ == "UniqueConstraint"
        ]
        assert len(constraints) == 1
        col_names = {col.name for col in constraints[0].columns}
        assert col_names == {"code", "url", "keyword"}

    def test_instantiation(self):
        row = MidtermPlanKeyword(
            code="1234",
            url="https://example.com/plan.pdf",
            keyword="DX推進",
            context_raw="全社的なDX推進により業務効率化を図る",
            disclosure_date="2025-04-18",
        )
        assert row.code == "1234"
        assert row.url == "https://example.com/plan.pdf"
        assert row.keyword == "DX推進"
        assert row.context_raw == "全社的なDX推進により業務効率化を図る"
        assert row.disclosure_date == "2025-04-18"

    def test_nullable_fields(self):
        """context_raw/disclosure_date/normalized_keywordはNoneを許容する"""
        row = MidtermPlanKeyword(code="1234", url="https://example.com/plan.pdf", keyword="DX推進")
        assert row.context_raw is None
        assert row.disclosure_date is None
        assert row.normalized_keyword is None
