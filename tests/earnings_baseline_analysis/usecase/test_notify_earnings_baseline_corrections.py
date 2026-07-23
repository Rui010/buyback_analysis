from unittest.mock import MagicMock, patch
import pandas as pd
from sqlalchemy import text

from earnings_baseline_analysis.usecase.notify_earnings_baseline_corrections import (
    get_earnings_baseline_corrections,
    notify_earnings_baseline_corrections,
)

_COLUMNS = ["code", "name", "title", "link", "date"]


def _make_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=_COLUMNS)


class TestGetEarningsBaselineCorrections:

    def test_sql_uses_parameterized_query(self):
        """text()とパラメータバインドを使用していることを確認"""
        engine = MagicMock()
        mock_df = _make_df([
            {"code": "1001", "name": "A社", "title": "（訂正）「2026年３月期 決算短信」の一部訂正について",
             "link": "url1", "date": "2026-05-13"},
        ])

        with patch(
            "earnings_baseline_analysis.usecase.notify_earnings_baseline_corrections.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df
            get_earnings_baseline_corrections(engine, "2026-05-13", "2026-05-13")

            assert mock_read.called
            first_arg = mock_read.call_args[0][0]
            assert isinstance(first_arg, type(text("")))

    def test_sql_filters_by_target_markets(self):
        """抽出パイプラインと同様にBrands.marketで絞り込むパラメータが渡されることを確認"""
        engine = MagicMock()
        mock_df = _make_df([
            {"code": "1001", "name": "A社", "title": "（訂正）「2026年３月期 決算短信」の一部訂正について",
             "link": "url1", "date": "2026-05-13"},
        ])

        with patch(
            "earnings_baseline_analysis.usecase.notify_earnings_baseline_corrections.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df
            get_earnings_baseline_corrections(engine, "2026-05-13", "2026-05-13")

            first_arg = mock_read.call_args[0][0]
            assert '"public"."Brands"' in str(first_arg)
            params = mock_read.call_args[1]["params"]
            assert set(params.values()) >= {"プライム", "スタンダード", "グロース"}

    def test_correction_and_partial_correction_titles_included(self):
        """「訂正」または「一部」を含むタイトルのみ返す"""
        engine = MagicMock()
        mock_df = _make_df([
            {"code": "1001", "name": "A社", "title": "（訂正）「2026年３月期 決算短信」の一部訂正について", "link": "url1", "date": "2026-05-13"},
            {"code": "1002", "name": "B社", "title": "2026年３月期 決算短信〔日本基準〕（連結）", "link": "url2", "date": "2026-05-13"},
            {"code": "1003", "name": "C社", "title": "過年度有価証券報告書等の訂正報告書の提出", "link": "url3", "date": "2026-05-13"},
        ])

        with patch(
            "earnings_baseline_analysis.usecase.notify_earnings_baseline_corrections.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df
            result = get_earnings_baseline_corrections(engine, "2026-05-13", "2026-05-13")

        assert len(result) == 1
        assert result["code"].tolist() == ["1001"]

    def test_quarterly_titles_excluded(self):
        """「四半期」を含むタイトルは除外する"""
        engine = MagicMock()
        mock_df = _make_df([
            {"code": "1001", "name": "A社",
             "title": "（訂正）「2026年３月期第３四半期決算短信」の一部訂正について",
             "link": "url1", "date": "2026-05-13"},
        ])

        with patch(
            "earnings_baseline_analysis.usecase.notify_earnings_baseline_corrections.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df
            result = get_earnings_baseline_corrections(engine, "2026-05-13", "2026-05-13")

        assert len(result) == 0

    def test_empty_result(self):
        """該当レコードがない場合は空のDataFrameを返す"""
        engine = MagicMock()
        mock_df = pd.DataFrame(columns=_COLUMNS)

        with patch(
            "earnings_baseline_analysis.usecase.notify_earnings_baseline_corrections.pd.read_sql_query"
        ) as mock_read:
            mock_read.return_value = mock_df
            result = get_earnings_baseline_corrections(engine, "2026-05-13", "2026-05-13")

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_db_error_returns_empty_dataframe(self):
        """DB接続エラー時は空のDataFrameを返す"""
        engine = MagicMock()
        engine.connect.side_effect = Exception("connection error")

        result = get_earnings_baseline_corrections(engine, "2026-05-13", "2026-05-13")

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0


class TestNotifyEarningsBaselineCorrections:

    def test_sends_notification_with_count_and_details(self):
        """該当ありの場合、件数とタイトル・URLを含めてnotify_successを呼ぶ"""
        engine = MagicMock()
        mock_df = _make_df([
            {"code": "1001", "name": "A社", "title": "（訂正）「2026年３月期 決算短信」の一部訂正について", "link": "url1", "date": "2026-05-13"},
        ])

        with patch(
            "earnings_baseline_analysis.usecase.notify_earnings_baseline_corrections.get_earnings_baseline_corrections"
        ) as mock_get, patch(
            "earnings_baseline_analysis.usecase.notify_earnings_baseline_corrections.notify_success"
        ) as mock_notify:
            mock_get.return_value = mock_df
            result = notify_earnings_baseline_corrections(engine, "2026-05-13", "2026-05-13")

        assert result == 1
        assert mock_notify.called
        script_name, detail = mock_notify.call_args[0]
        assert script_name == "earnings_baseline_corrections"
        assert "1件" in detail
        assert "1001" in detail
        assert "url1" in detail

    def test_no_corrections_does_not_notify(self):
        """該当0件の場合はnotify_successを呼ばない"""
        engine = MagicMock()

        with patch(
            "earnings_baseline_analysis.usecase.notify_earnings_baseline_corrections.get_earnings_baseline_corrections"
        ) as mock_get, patch(
            "earnings_baseline_analysis.usecase.notify_earnings_baseline_corrections.notify_success"
        ) as mock_notify:
            mock_get.return_value = pd.DataFrame(columns=_COLUMNS)
            result = notify_earnings_baseline_corrections(engine, "2026-05-13", "2026-05-13")

        assert result == 0
        assert not mock_notify.called
