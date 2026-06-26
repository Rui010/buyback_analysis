import json
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.exc import IntegrityError

from midterm_plan_analysis.usecase.post_midterm_plan import post_midterm_plan


class TestPostMidtermPlan:

    def _make_data(self, metrics=None):
        return {
            "type": "MIDTERM_PLAN",
            "data": {
                "plan_name": "2027中期経営計画",
                "plan_start_year": 2025,
                "plan_end_year": 2027,
                "metrics": metrics or [
                    {"name": "売上高", "value": 500, "unit": "億円", "target_year": 2027}
                ],
            },
        }

    def test_normal_save(self):
        """正常なデータが保存される"""
        session = MagicMock()
        post_midterm_plan(
            session=session,
            data=self._make_data(),
            code="1234",
            url="https://example.com/plan.pdf",
            disclosure_date="2025-04-18",
            extraction_status="ok",
        )
        assert session.add.called
        assert session.commit.called

    def test_metrics_serialized_as_json(self):
        """metricsがJSON文字列としてモデルに渡される"""
        session = MagicMock()
        metrics = [{"name": "ROE", "value": 12, "unit": "%", "target_year": 2027}]

        post_midterm_plan(
            session=session,
            data=self._make_data(metrics=metrics),
            code="1234",
            url="https://example.com/plan.pdf",
            disclosure_date="2025-04-18",
            extraction_status="ok",
        )

        instance = session.add.call_args[0][0]
        parsed = json.loads(instance.metrics)
        assert parsed == metrics

    def test_none_data_does_not_save(self):
        """dataがNoneの場合は保存しない"""
        session = MagicMock()
        post_midterm_plan(
            session=session,
            data=None,
            code="1234",
            url="https://example.com/plan.pdf",
            disclosure_date="2025-04-18",
            extraction_status="failed",
        )
        assert not session.add.called
        assert not session.commit.called

    def test_integrity_error_is_handled(self):
        """主キー重複はロールバックしてスキップ"""
        session = MagicMock()
        session.commit.side_effect = IntegrityError("Duplicate key", None, None)

        post_midterm_plan(
            session=session,
            data=self._make_data(),
            code="1234",
            url="https://example.com/plan.pdf",
            disclosure_date="2025-04-18",
            extraction_status="ok",
        )

        session.rollback.assert_called()

    def test_unexpected_error_is_handled(self):
        """予期しないエラーはロールバックして続行"""
        session = MagicMock()
        session.commit.side_effect = Exception("unexpected")

        post_midterm_plan(
            session=session,
            data=self._make_data(),
            code="1234",
            url="https://example.com/plan.pdf",
            disclosure_date="2025-04-18",
            extraction_status="ok",
        )

        session.rollback.assert_called()

    @pytest.mark.parametrize("status", ["ok", "failed", "withdrawn", "no_targets", "postponed"])
    def test_extraction_status_is_saved(self, status):
        """extraction_statusがモデルに正しくセットされる"""
        session = MagicMock()
        post_midterm_plan(
            session=session,
            data=self._make_data(),
            code="1234",
            url="https://example.com/plan.pdf",
            disclosure_date="2025-04-18",
            extraction_status=status,
        )
        instance = session.add.call_args[0][0]
        assert instance.extraction_status == status
