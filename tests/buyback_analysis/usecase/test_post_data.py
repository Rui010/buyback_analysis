import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.exc import IntegrityError

from buyback_analysis.usecase.post_data import post_data
from buyback_analysis.consts.detect_type import DetectType


class TestPostDataValidation:
    """LLM出力のバリデーション追加テスト"""

    def test_post_data_with_missing_required_field(self):
        """必須フィールド (code, disclosure_date) がNULLの場合はValueErrorを送出してロールバックする"""
        session = MagicMock()

        data = {
            "type": "buyback_announcement",
            "data": {
                "code": "1234",
                "disclosure_date": None,  # NULL
                "url": "https://example.com",
            },
        }

        with pytest.raises(ValueError, match="disclosure_date"):
            assert post_data(session, data) is True

        assert session.rollback.called

    def test_post_data_with_valid_data(self):
        """有効なデータは正常に保存される"""
        session = MagicMock()

        data = {
            "type": "buyback_announcement",  # enum値を使用
            "data": {
                "code": "1234",
                "disclosure_date": "2025-04-18",
                "resolution_date": "2025-04-18",
                "url": "https://example.com",
                "company_name": "Test Company",
                "buyback_method": "Market Purchase",
            },
        }

        with patch("buyback_analysis.usecase.post_data.inspect") as mock_inspect:
            mock_mapper = MagicMock()
            mock_mapper.mapper.column_attrs = []
            mock_inspect.return_value = mock_mapper

            assert post_data(session, data) is True
            # session.add()とsession.commit()が呼ばれることを確認
            assert session.add.called
            assert session.commit.called

    def test_post_data_retirement_valid(self):
        """RETIREMENTタイプの有効なデータが正常に保存される"""
        session = MagicMock()

        data = {
            "type": "retirement",
            "data": {
                "code": "1234",
                "disclosure_date": "2025-04-18",
                "retirement_date": "2025-04-01",
                "company_name": "Test Company",
                "share_type": "普通株式",
                "retirement_shares": 1000000,
            },
        }

        with patch("buyback_analysis.usecase.post_data.inspect") as mock_inspect:
            mock_mapper = MagicMock()
            mock_mapper.mapper.column_attrs = []
            mock_inspect.return_value = mock_mapper

            post_data(session, data)
            assert session.add.called
            assert session.commit.called

    def test_post_data_integrity_error_returns_false(self):
        """一意制約違反ではロールバックし、保存失敗を呼び出し側へ返す。"""
        session = MagicMock()
        session.commit.side_effect = IntegrityError("Duplicate key", None, None)

        data = {
            "type": "buyback_announcement",  # enum値を使用
            "data": {
                "code": "1234",
                "disclosure_date": "2025-04-18",
                "resolution_date": "2025-04-18",
                "url": "https://example.com",
            },
        }

        with patch("buyback_analysis.usecase.post_data.inspect") as mock_inspect:
            mock_mapper = MagicMock()
            mock_mapper.mapper.column_attrs = []
            mock_inspect.return_value = mock_mapper

            assert post_data(session, data) is False
            session.rollback.assert_called()
