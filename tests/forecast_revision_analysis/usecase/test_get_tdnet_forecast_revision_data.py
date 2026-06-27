import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
from sqlalchemy import text

from forecast_revision_analysis.usecase.get_tdnet_forecast_revision_data import (
    get_tdnet_forecast_revision_data,
    get_tdnet_forecast_revision_data_by_urls,
)

_COLUMNS = ["time", "code", "name", "title", "link", "date"]


def _make_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=_COLUMNS)


class TestGetTdnetForecastRevisionData:

    def test_sql_uses_parameterized_query(self):
        """text()とパラメータバインドを使用していることを確認"""
        engine = MagicMock()
        mock_df = _make_df([
            {"time": "10:00", "code": "1001", "name": "A社",
             "title": "業績予想の修正", "link": "url1", "date": "2026-06-18"},
        ])

        with patch(
            "forecast_revision_analysis.usecase.get_tdnet_forecast_revision_data.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df
            get_tdnet_forecast_revision_data(engine, "2026-06-13", "2026-06-18")

            assert mock_read.called
            first_arg = mock_read.call_args[0][0]
            assert isinstance(first_arg, type(text("")))

    def test_and_filter_both_keywords_required(self):
        """「修正」AND「業績」の両方を含むタイトルのみ返す"""
        engine = MagicMock()
        mock_df = _make_df([
            {"time": "10:00", "code": "1001", "name": "A社",
             "title": "業績予想の修正に関するお知らせ", "link": "url1", "date": "2026-06-18"},
            {"time": "10:00", "code": "1002", "name": "B社",
             "title": "自己株式の取得", "link": "url2", "date": "2026-06-18"},
            {"time": "10:00", "code": "1003", "name": "C社",
             "title": "修正のお知らせ", "link": "url3", "date": "2026-06-18"},
            {"time": "10:00", "code": "1004", "name": "D社",
             "title": "業績のお知らせ", "link": "url4", "date": "2026-06-18"},
            {"time": "10:00", "code": "1005", "name": "E社",
             "title": "連結業績予想修正のご報告", "link": "url5", "date": "2026-06-18"},
        ])

        with patch(
            "forecast_revision_analysis.usecase.get_tdnet_forecast_revision_data.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df
            result = get_tdnet_forecast_revision_data(engine, "2026-06-13", "2026-06-18")

        assert len(result) == 2
        assert result["code"].tolist() == ["1001", "1005"]

    def test_empty_result(self):
        """該当レコードがない場合は空のDataFrameを返す"""
        engine = MagicMock()
        mock_df = pd.DataFrame(columns=_COLUMNS)

        with patch(
            "forecast_revision_analysis.usecase.get_tdnet_forecast_revision_data.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df
            result = get_tdnet_forecast_revision_data(engine, "2026-06-13", "2026-06-18")

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_db_error_returns_empty_dataframe(self):
        """DB接続エラー時は空のDataFrameを返す"""
        engine = MagicMock()
        engine.connect.side_effect = Exception("connection error")

        result = get_tdnet_forecast_revision_data(engine, "2026-06-13", "2026-06-18")

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0


class TestGetTdnetForecastRevisionDataByUrls:

    def test_returns_matching_records(self):
        """指定URLに一致するレコードを返す"""
        engine = MagicMock()
        mock_df = _make_df([
            {"time": "10:00", "code": "1001", "name": "A社",
             "title": "業績予想の修正", "link": "url1", "date": "2026-06-18"},
        ])

        with patch(
            "forecast_revision_analysis.usecase.get_tdnet_forecast_revision_data.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df
            result = get_tdnet_forecast_revision_data_by_urls(engine, ["url1"])

        assert len(result) == 1

    def test_empty_urls_returns_empty_dataframe(self):
        """URLリストが空の場合はDBを呼ばずに空のDataFrameを返す"""
        engine = MagicMock()
        result = get_tdnet_forecast_revision_data_by_urls(engine, [])

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
        assert not engine.connect.called

    def test_db_error_returns_empty_dataframe(self):
        """DB接続エラー時は空のDataFrameを返す"""
        engine = MagicMock()
        engine.connect.side_effect = Exception("connection error")

        result = get_tdnet_forecast_revision_data_by_urls(engine, ["url1"])

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
