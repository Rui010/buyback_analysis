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
        """経営計画・中計、および「中期/中長期」+計画系サフィックスを含むタイトルのみ返す"""
        engine = MagicMock()
        titles = [
            "2027中期経営計画の策定",              # マッチ（経営計画）
            "自己株式の取得予定",                    # マッチしない
            "中期三カ年経営計画について",            # マッチ（経営計画）
            "配当金の決定",                         # マッチしない
            "中計の見直しに関するお知らせ",          # マッチ（中計）
            "途中経過のご報告",                      # マッチしない（中経を削除した確認）
            "中期事業計画の策定に関するお知らせ",     # マッチ（中期+計画）
            "中期経営方針の策定に関するお知らせ",     # マッチ（中期+方針）
            "2030中期経営戦略の策定について",        # マッチ（中期+戦略）
            "中期計画2028について",                  # マッチ（中期+計画、経営/事業を伴わない）
            "中長期経営ビジョン2035策定に関するお知らせ",  # マッチ（中長期+ビジョン）
            "事業計画及び成長可能性に関する事項",     # マッチしない（中期・中長期を伴わない定型開示）
            "当社グループ役職員に対する中期インセンティブプランとしての株式報酬制度",  # マッチしない（計画系サフィックスなし）
            "中期的業績連動報酬の一部改定に関するお知らせ",  # マッチしない（計画系サフィックスなし）
            "中長期業績連動型株式報酬制度の導入に関するお知らせ",  # マッチしない（計画系サフィックスなし）
        ]
        mock_df = pd.DataFrame(
            {
                "time": ["10:00"] * len(titles),
                "code": [f"{1001 + i}" for i in range(len(titles))],
                "name": [f"社{i}" for i in range(len(titles))],
                "title": titles,
                "link": [f"url{i}" for i in range(len(titles))],
                "date": ["2025-04-18"] * len(titles),
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

            assert result["code"].tolist() == [
                "1001", "1003", "1005", "1007", "1008", "1009", "1010", "1011",
            ]

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
