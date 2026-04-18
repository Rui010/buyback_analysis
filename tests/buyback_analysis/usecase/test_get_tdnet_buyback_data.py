import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
from sqlalchemy import text

from buyback_analysis.usecase.get_tdnet_buyback_data import get_tdnet_buyback_data


class TestGetTdnetBuybackData:
    """SQLインジェクション対策（text()の使用）テスト"""

    def test_sql_uses_parameterized_query(self):
        """SQLAlchemy text()とパラメータバインドを使用していることを確認"""
        engine = MagicMock()

        # モックデータ
        mock_df = pd.DataFrame(
            {
                "time": ["10:00"],
                "code": ["1234"],
                "name": ["Test Company"],
                "title": ["自己株式の取得予定"],
                "link": ["https://example.com"],
                "date": ["2025-04-18"],
            }
        )

        with patch(
            "buyback_analysis.usecase.get_tdnet_buyback_data.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df

            result = get_tdnet_buyback_data(
                engine=engine,
                start_date="2025-04-13",
                end_date="2025-04-18",
            )

            # read_sql_queryが呼ばれたことを確認
            assert mock_read.called

            # 第1引数がtext()オブジェクトであることを確認
            call_args = mock_read.call_args
            first_arg = call_args[0][0]
            assert isinstance(first_arg, type(text("")))

            # パラメータが渡されていることを確認
            assert "params" in call_args.kwargs or len(call_args[0]) > 2

    def test_buyback_filter(self):
        """自己株を含むタイトルでフィルタリング"""
        engine = MagicMock()

        # 自己株を含む/含まないデータ
        mock_df = pd.DataFrame(
            {
                "time": ["10:00", "11:00", "12:00"],
                "code": ["1234", "5678", "9012"],
                "name": ["A社", "B社", "C社"],
                "title": [
                    "自己株式の取得予定",  # マッチ
                    "配当金の決定",  # マッチしない
                    "自己株式の取得結果報告",  # マッチ
                ],
                "link": ["url1", "url2", "url3"],
                "date": ["2025-04-18", "2025-04-18", "2025-04-18"],
            }
        )

        with patch(
            "buyback_analysis.usecase.get_tdnet_buyback_data.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df

            result = get_tdnet_buyback_data(
                engine=engine,
                start_date="2025-04-13",
                end_date="2025-04-18",
            )

            # 自己株を含む2件だけが返される
            assert len(result) == 2
            assert result["code"].tolist() == ["1234", "9012"]

    def test_empty_result(self):
        """該当するレコードがない場合"""
        engine = MagicMock()

        mock_df = pd.DataFrame(
            {
                "time": [],
                "code": [],
                "name": [],
                "title": [],
                "link": [],
                "date": [],
            }
        )

        with patch(
            "buyback_analysis.usecase.get_tdnet_buyback_data.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df

            result = get_tdnet_buyback_data(
                engine=engine,
                start_date="2025-04-13",
                end_date="2025-04-18",
            )

            assert len(result) == 0
            assert isinstance(result, pd.DataFrame)
