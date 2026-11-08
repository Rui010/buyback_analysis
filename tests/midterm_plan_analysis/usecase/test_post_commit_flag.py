"""保存関数のcommit=False（採用切替のトランザクションに含める）の振る舞い。"""

from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from forecast_revision_analysis.usecase.post_forecast_revision import post_forecast_revision
from midterm_plan_analysis.usecase.post_midterm_keywords import post_midterm_keywords
from midterm_plan_analysis.usecase.post_midterm_plan import post_midterm_plan

COMMON = dict(code="1234", url="https://x/a.pdf", disclosure_date="2026-02-19")


def _call(target, session, commit):
    if target == "plan":
        return post_midterm_plan(session=session, data={"data": {}}, extraction_status="ok", commit=commit, **COMMON)
    if target == "keywords":
        return post_midterm_keywords(session=session, keywords=[{"keyword": "DX"}], commit=commit, **COMMON)
    session.query.return_value.filter.return_value.delete.return_value = 0
    return post_forecast_revision(session=session, data={"data": {}}, extraction_status="ok", commit=commit, **COMMON)


@pytest.mark.parametrize("target", ["plan", "keywords", "forecast"])
def test_commit_false_flushes_without_commit(target):
    session = MagicMock()
    assert _call(target, session, commit=False) is True
    session.commit.assert_not_called()
    session.flush.assert_called()


@pytest.mark.parametrize("target", ["plan", "keywords", "forecast"])
def test_commit_false_leaves_rollback_to_caller(target):
    session = MagicMock()
    session.flush.side_effect = IntegrityError("insert", {}, Exception("UNIQUE constraint failed"))
    assert _call(target, session, commit=False) is False
    session.rollback.assert_not_called()


@pytest.mark.parametrize("target", ["plan", "keywords", "forecast"])
def test_default_commits(target):
    session = MagicMock()
    assert _call(target, session, commit=True) is True
    session.commit.assert_called_once()


def test_keywords_return_true_when_nothing_to_save():
    session = MagicMock()
    assert post_midterm_keywords(session=session, keywords=None, **COMMON) is True
    session.commit.assert_not_called()
