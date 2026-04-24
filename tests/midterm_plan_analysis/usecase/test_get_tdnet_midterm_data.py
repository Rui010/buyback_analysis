import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
from sqlalchemy import text

from midterm_plan_analysis.usecase.get_tdnet_midterm_data import get_tdnet_midterm_data


class TestGetTdnetMidtermData:

    def test_sql_uses_parameterized_query(self):
        """text()とパラメータバインドを使用していることを確認"""
        engine = MagicMock()
        mock_df = pd.DataFrame(
            {
                "time": ["10:00"],
                "code": ["1234"],
                "name": ["Test Company"],
                "title": ["2027中期経営計画"],
                "link": ["https://example.com"],
                "date": ["2025-04-18"],
            }
        )

        with patch(
            "midterm_plan_analysis.usecase.get_tdnet_midterm_data.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df

            result = get_tdnet_midterm_data(
                engine=engine,
                start_date="2025-04-13",
                end_date="2025-04-18",
            )

            assert mock_read.called
            call_args = mock_read.call_args
            first_arg = call_args[0][0]
            assert isinstance(first_arg, type(text("")))
            assert "params" in call_args.kwargs or len(call_args[0]) > 2

    def test_midterm_keyword_filter(self):
        """経営計画・中計を含むタイトルのみ返す"""
        engine = MagicMock()
        mock_df = pd.DataFrame(
            {
                "time": ["10:00"] * 6,
                "code": ["1001", "1002", "1003", "1004", "1005", "1006"],
                "name": ["A社", "B社", "C社", "D社", "E社", "F社"],
                "title": [
                    "2027中期経営計画の策定",          # マッチ（経営計画）
                    "自己株式の取得予定",                # マッチしない
                    "中期三カ年経営計画について",        # マッチ（経営計画）
                    "配当金の決定",                     # マッチしない
                    "中計の見直しに関するお知らせ",      # マッチ（中計）
                    "途中経過のご報告",                  # マッチしない（中経を削除した確認）
                ],
                "link": ["url1", "url2", "url3", "url4", "url5", "url6"],
                "date": ["2025-04-18"] * 6,
            }
        )

        with patch(
            "midterm_plan_analysis.usecase.get_tdnet_midterm_data.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df

            result = get_tdnet_midterm_data(
                engine=engine,
                start_date="2025-04-13",
                end_date="2025-04-18",
            )

            assert len(result) == 3
            assert result["code"].tolist() == ["1001", "1003", "1005"]

    def test_empty_result(self):
        """該当レコードがない場合"""
        engine = MagicMock()
        mock_df = pd.DataFrame(
            {"time": [], "code": [], "name": [], "title": [], "link": [], "date": []}
        )

        with patch(
            "midterm_plan_analysis.usecase.get_tdnet_midterm_data.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df

            result = get_tdnet_midterm_data(
                engine=engine,
                start_date="2025-04-13",
                end_date="2025-04-18",
            )

            assert len(result) == 0
            assert isinstance(result, pd.DataFrame)

    def test_db_error_returns_empty_dataframe(self):
        """DB接続エラー時は空のDataFrameを返す"""
        engine = MagicMock()
        engine.connect.side_effect = Exception("connection error")

        result = get_tdnet_midterm_data(
            engine=engine,
            start_date="2025-04-13",
            end_date="2025-04-18",
        )

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
