from unittest.mock import MagicMock, patch
import pandas as pd
from sqlalchemy import text

from earnings_baseline_analysis.usecase.get_tdnet_earnings_baseline_data import (
    get_tdnet_earnings_baseline_data,
    get_tdnet_earnings_baseline_data_by_urls,
)

_COLUMNS = ["time", "code", "name", "title", "link", "date"]


def _make_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=_COLUMNS)


class TestGetTdnetEarningsBaselineData:

    def test_sql_uses_parameterized_query_with_market_filter(self):
        """text()とパラメータバインドを使用し、対象marketがパラメータに含まれることを確認"""
        engine = MagicMock()
        mock_df = _make_df([
            {"time": "10:00", "code": "2168", "name": "パソナグループ",
             "title": "2026年３月期 決算短信〔日本基準〕（連結）", "link": "url1", "date": "2026-05-13"},
        ])

        with patch(
            "earnings_baseline_analysis.usecase.get_tdnet_earnings_baseline_data.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df
            get_tdnet_earnings_baseline_data(engine, "2026-05-01", "2026-05-31")

            assert mock_read.called
            first_arg = mock_read.call_args[0][0]
            assert isinstance(first_arg, type(text("")))
            params = mock_read.call_args[1]["params"]
            assert set(params.values()) >= {"プライム", "スタンダード", "グロース", "2026-05-01", "2026-05-31"}

    def test_title_include_keyword_required(self):
        """「決算短信」を含まないタイトルは除外する"""
        engine = MagicMock()
        mock_df = _make_df([
            {"time": "10:00", "code": "2168", "name": "A社",
             "title": "2026年３月期 決算短信〔日本基準〕（連結）", "link": "url1", "date": "2026-05-13"},
            {"time": "10:00", "code": "1002", "name": "B社",
             "title": "自己株式の取得", "link": "url2", "date": "2026-05-13"},
        ])

        with patch(
            "earnings_baseline_analysis.usecase.get_tdnet_earnings_baseline_data.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df
            result = get_tdnet_earnings_baseline_data(engine, "2026-05-01", "2026-05-31")

        assert len(result) == 1
        assert result["code"].tolist() == ["2168"]

    def test_title_exclude_keywords(self):
        """「四半期」「訂正」「一部」「中間」を含むタイトルは除外する"""
        engine = MagicMock()
        mock_df = _make_df([
            {"time": "10:00", "code": "1001", "name": "A社",
             "title": "2026年３月期 決算短信〔日本基準〕（連結）", "link": "url1", "date": "2026-05-13"},
            {"time": "10:00", "code": "1002", "name": "B社",
             "title": "2026年３月期第３四半期決算短信〔日本基準〕（連結）", "link": "url2", "date": "2026-05-13"},
            {"time": "10:00", "code": "1003", "name": "C社",
             "title": "（訂正・数値データ訂正）「2026年３月期 決算短信」の一部訂正について", "link": "url3", "date": "2026-05-13"},
            {"time": "10:00", "code": "1004", "name": "D社",
             "title": "2026年３月期 中間決算短信〔日本基準〕（連結）", "link": "url4", "date": "2026-05-13"},
        ])

        with patch(
            "earnings_baseline_analysis.usecase.get_tdnet_earnings_baseline_data.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df
            result = get_tdnet_earnings_baseline_data(engine, "2026-05-01", "2026-05-31")

        assert len(result) == 1
        assert result["code"].tolist() == ["1001"]

    def test_empty_result(self):
        """該当レコードがない場合は空のDataFrameを返す"""
        engine = MagicMock()
        mock_df = pd.DataFrame(columns=_COLUMNS)

        with patch(
            "earnings_baseline_analysis.usecase.get_tdnet_earnings_baseline_data.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df
            result = get_tdnet_earnings_baseline_data(engine, "2026-05-01", "2026-05-31")

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_db_error_returns_empty_dataframe(self):
        """DB接続エラー時は空のDataFrameを返す"""
        engine = MagicMock()
        engine.connect.side_effect = Exception("connection error")

        result = get_tdnet_earnings_baseline_data(engine, "2026-05-01", "2026-05-31")

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0


class TestGetTdnetEarningsBaselineDataByUrls:

    def test_returns_matching_records(self):
        """指定URLに一致するレコードを返す"""
        engine = MagicMock()
        mock_df = _make_df([
            {"time": "10:00", "code": "2168", "name": "A社",
             "title": "2026年３月期 決算短信〔日本基準〕（連結）", "link": "url1", "date": "2026-05-13"},
        ])

        with patch(
            "earnings_baseline_analysis.usecase.get_tdnet_earnings_baseline_data.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df
            result = get_tdnet_earnings_baseline_data_by_urls(engine, ["url1"])

        assert len(result) == 1

    def test_empty_urls_returns_empty_dataframe(self):
        """URLリストが空の場合はDBを呼ばずに空のDataFrameを返す"""
        engine = MagicMock()
        result = get_tdnet_earnings_baseline_data_by_urls(engine, [])

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
        assert not engine.connect.called

    def test_db_error_returns_empty_dataframe(self):
        """DB接続エラー時は空のDataFrameを返す"""
        engine = MagicMock()
        engine.connect.side_effect = Exception("connection error")

        result = get_tdnet_earnings_baseline_data_by_urls(engine, ["url1"])

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
