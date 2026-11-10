from unittest.mock import MagicMock

import pytest

from midterm_plan_analysis.usecase.determine_midterm_status import determine_midterm_status

TARGET = [{"name": "売上高", "value": 500}]


def test_withdrawn_title_wins_over_metrics():
    classify = MagicMock()
    assert determine_midterm_status("中期経営計画の取り下げに関するお知らせ", TARGET, classify) == "withdrawn"
    classify.assert_not_called()


def test_metrics_with_value_is_ok():
    classify = MagicMock()
    assert determine_midterm_status("中期経営計画の策定", TARGET, classify) == "ok"
    classify.assert_not_called()


@pytest.mark.parametrize("metrics", [[], None, [{"name": "売上高", "value": None}]])
def test_postponed_title_without_metrics(metrics):
    classify = MagicMock()
    assert determine_midterm_status("次期中期経営計画の公表延期", metrics, classify) == "postponed"
    classify.assert_not_called()


def test_postponed_title_with_metrics_is_ok():
    assert determine_midterm_status("中期経営計画の公表延期", TARGET, MagicMock()) == "ok"


def test_otherwise_classification_decides():
    classify = MagicMock(return_value="no_targets")
    assert determine_midterm_status("中期経営計画説明会資料", [], classify) == "no_targets"
    classify.assert_called_once_with()
