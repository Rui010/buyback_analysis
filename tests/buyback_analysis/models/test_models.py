import pytest
from sqlalchemy import inspect

from buyback_analysis.models.announcement import Announcement
from buyback_analysis.models.completion import Completion
from buyback_analysis.models.correction import Correction
from buyback_analysis.models.progress import Progress
from buyback_analysis.models.retirement import Retirement


class TestAnnouncementModel:
    """AnnouncementモデルのURL主キーと検索列を確認する。"""

    def test_announcement_primary_keys(self):
        """Announcementの主キーはURLのみであることを確認"""
        mapper = inspect(Announcement)
        pk_columns = [col.name for col in mapper.primary_key]

        assert pk_columns == ["url"]
        assert Announcement.code.nullable is False
        assert Announcement.disclosure_date.nullable is False
        assert Announcement.code.index is True
        assert Announcement.disclosure_date.index is True


class TestCompletionModel:
    """CompletionモデルのURL主キーを確認する。"""

    def test_completion_primary_keys(self):
        """Completionの主キーはURLのみであることを確認"""
        mapper = inspect(Completion)
        pk_columns = [col.name for col in mapper.primary_key]

        assert pk_columns == ["url"]

    def test_completion_column_types(self):
        """Completionの列の型が正しいことを確認"""
        mapper = inspect(Completion)
        columns = {col.name: col.type for col in mapper.columns}

        # shares_acquired は Float であるべき（小数を含む取得株数に対応）
        from sqlalchemy import Float, String

        assert isinstance(columns["shares_acquired"], Float)

        # buyback_method は String であるべき
        assert isinstance(columns["buyback_method"], String)


class TestRetirementModel:
    """Retirementモデルのテスト"""

    def test_retirement_primary_keys(self):
        """Retirementの主キーはURLのみであることを確認"""
        mapper = inspect(Retirement)
        pk_columns = [col.name for col in mapper.primary_key]

        assert pk_columns == ["url"]
        assert Retirement.code.nullable is False
        assert Retirement.disclosure_date.nullable is False


class TestProgressModel:
    def test_progress_primary_key_is_url(self):
        mapper = inspect(Progress)

        assert [col.name for col in mapper.primary_key] == ["url"]
        assert Progress.code.nullable is False
        assert Progress.disclosure_date.nullable is False

    def test_retirement_columns(self):
        """Retirementの列が正しく定義されていることを確認"""
        from sqlalchemy import BigInteger, String

        mapper = inspect(Retirement)
        columns = {col.name: col.type for col in mapper.columns}

        assert isinstance(columns["retirement_shares"], BigInteger)
        assert isinstance(columns["share_type"], String)

    def test_retirement_uses_shared_base(self):
        """RetirementがBaseクラスを継承していることを確認"""
        from buyback_analysis.models.base import Base

        assert issubclass(Retirement, Base)
        mapper = inspect(Retirement)
        assert mapper.persist_selectable.name == "retirements"


class TestCorrectionModel:
    """Correctionモデルのテスト（base.Baseを使用していることを確認）"""

    def test_correction_uses_shared_base(self):
        """Correctionが共有のBaseを使用していることを確認"""
        from buyback_analysis.models.base import Base

        # CorrectionがBaseクラスを継承していることを確認
        assert issubclass(Correction, Base)

        # テーブル名が正しく設定されている
        mapper = inspect(Correction)
        assert mapper.persist_selectable.name == "corrections"
