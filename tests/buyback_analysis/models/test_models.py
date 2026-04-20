import pytest
from sqlalchemy import inspect

from buyback_analysis.models.announcement import Announcement
from buyback_analysis.models.completion import Completion
from buyback_analysis.models.correction import Correction
from buyback_analysis.models.retirement import Retirement


class TestAnnouncementModel:
    """Announcementモデルのテスト（resolution_dateが複合主キーに含まれるかを確認）"""

    def test_announcement_primary_keys(self):
        """Announcementの複合主キーが (code, disclosure_date, resolution_date) であることを確認"""
        mapper = inspect(Announcement)
        pk_columns = [col.name for col in mapper.primary_key]

        assert len(pk_columns) == 3
        assert "code" in pk_columns
        assert "disclosure_date" in pk_columns
        assert "resolution_date" in pk_columns


class TestCompletionModel:
    """Completionモデルのテスト（resolution_dateが複合主キーに含まれるかを確認）"""

    def test_completion_primary_keys(self):
        """Completionの複合主キーが (code, disclosure_date, resolution_date) であることを確認"""
        mapper = inspect(Completion)
        pk_columns = [col.name for col in mapper.primary_key]

        assert len(pk_columns) == 3
        assert "code" in pk_columns
        assert "disclosure_date" in pk_columns
        assert "resolution_date" in pk_columns

    def test_completion_column_types(self):
        """Completionの列の型が正しいことを確認（修正後）"""
        mapper = inspect(Completion)
        columns = {col.name: col.type for col in mapper.columns}

        # shares_acquired は BigInteger であるべき
        from sqlalchemy import BigInteger, String

        assert isinstance(columns["shares_acquired"], BigInteger)

        # buyback_method は String であるべき
        assert isinstance(columns["buyback_method"], String)


class TestRetirementModel:
    """Retirementモデルのテスト"""

    def test_retirement_primary_keys(self):
        """Retirementの複合主キーが (code, disclosure_date, retirement_date) であることを確認"""
        mapper = inspect(Retirement)
        pk_columns = [col.name for col in mapper.primary_key]

        assert len(pk_columns) == 3
        assert "code" in pk_columns
        assert "disclosure_date" in pk_columns
        assert "retirement_date" in pk_columns

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
        assert mapper.mapped_table.name == "retirements"


class TestCorrectionModel:
    """Correctionモデルのテスト（base.Baseを使用していることを確認）"""

    def test_correction_uses_shared_base(self):
        """Correctionが共有のBaseを使用していることを確認"""
        from buyback_analysis.models.base import Base

        # CorrectionがBaseクラスを継承していることを確認
        assert issubclass(Correction, Base)

        # テーブル名が正しく設定されている
        mapper = inspect(Correction)
        assert mapper.mapped_table.name == "corrections"
