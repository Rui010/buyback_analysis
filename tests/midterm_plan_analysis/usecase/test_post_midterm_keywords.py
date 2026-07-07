from unittest.mock import MagicMock
from sqlalchemy.exc import IntegrityError

from midterm_plan_analysis.usecase.post_midterm_keywords import post_midterm_keywords


class TestPostMidtermKeywords:

    def test_each_keyword_is_saved_as_a_row(self):
        session = MagicMock()
        post_midterm_keywords(
            session=session,
            code="1234",
            url="https://example.com/plan.pdf",
            disclosure_date="2025-04-18",
            keywords=[
                {"keyword": "DX推進", "context_raw": "全社的なDX推進により業務効率化を図る"},
                {"keyword": "海外展開", "context_raw": None},
            ],
        )

        assert session.add.call_count == 2
        saved = {call.args[0].keyword: call.args[0].context_raw for call in session.add.call_args_list}
        assert saved == {"DX推進": "全社的なDX推進により業務効率化を図る", "海外展開": None}
        assert session.commit.called

    def test_duplicate_keywords_are_deduplicated_before_saving(self):
        """LLMが同じkeywordを重複して返しても、UniqueConstraint違反にならないよう先勝ちで1件にする"""
        session = MagicMock()
        post_midterm_keywords(
            session=session,
            code="1234",
            url="https://example.com/plan.pdf",
            disclosure_date="2025-04-18",
            keywords=[
                {"keyword": "DX推進", "context_raw": "1つ目の言及"},
                {"keyword": "DX推進", "context_raw": "2つ目の言及"},
            ],
        )

        assert session.add.call_count == 1
        assert session.add.call_args[0][0].context_raw == "1つ目の言及"

    def test_none_keywords_does_not_save(self):
        session = MagicMock()
        post_midterm_keywords(
            session=session, code="1234", url="https://example.com/plan.pdf",
            disclosure_date="2025-04-18", keywords=None,
        )
        assert not session.add.called
        assert not session.commit.called

    def test_empty_list_does_not_save(self):
        session = MagicMock()
        post_midterm_keywords(
            session=session, code="1234", url="https://example.com/plan.pdf",
            disclosure_date="2025-04-18", keywords=[],
        )
        assert not session.add.called
        assert not session.commit.called

    def test_integrity_error_is_handled(self):
        """主キー重複はロールバックしてスキップ"""
        session = MagicMock()
        session.commit.side_effect = IntegrityError("Duplicate key", None, None)

        post_midterm_keywords(
            session=session, code="1234", url="https://example.com/plan.pdf",
            disclosure_date="2025-04-18", keywords=[{"keyword": "DX推進", "context_raw": None}],
        )

        session.rollback.assert_called()

    def test_unexpected_error_is_handled(self):
        """予期しないエラーはロールバックして続行"""
        session = MagicMock()
        session.commit.side_effect = Exception("unexpected")

        post_midterm_keywords(
            session=session, code="1234", url="https://example.com/plan.pdf",
            disclosure_date="2025-04-18", keywords=[{"keyword": "DX推進", "context_raw": None}],
        )

        session.rollback.assert_called()
