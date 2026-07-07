from unittest.mock import MagicMock

from midterm_plan_analysis.models.midterm_plan import MidtermPlan
from midterm_plan_analysis.usecase.get_midterm_plans_missing_keywords import (
    get_midterm_plans_missing_keywords,
)


class TestGetMidtermPlansMissingKeywords:

    def test_query_chain_and_return_value(self):
        session = MagicMock()
        expected = [MagicMock(spec=MidtermPlan)]
        session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = expected

        result = get_midterm_plans_missing_keywords(session=session, limit=50)

        assert result == expected
        session.query.assert_called_once_with(MidtermPlan)
        session.query.return_value.filter.return_value.order_by.return_value.limit.assert_called_once_with(50)

    def test_filter_requires_ok_status_and_excludes_existing_keyword_urls(self):
        session = MagicMock()
        get_midterm_plans_missing_keywords(session=session, limit=10)

        args, _ = session.query.return_value.filter.call_args
        rendered = " ".join(str(a) for a in args)
        assert "extraction_status" in rendered
        assert "midterm_plan_keywords" in rendered
        assert "NOT" in rendered

    def test_order_by_disclosure_date_descending(self):
        session = MagicMock()
        get_midterm_plans_missing_keywords(session=session, limit=10)

        args, _ = session.query.return_value.filter.return_value.order_by.call_args
        rendered = str(args[0])
        assert "disclosure_date" in rendered
        assert "DESC" in rendered
