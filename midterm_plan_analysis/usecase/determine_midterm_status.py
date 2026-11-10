"""中計のextraction_statusの判定（main.pyとローカル検証スクリプトで共用）。"""

from collections.abc import Callable

WITHDRAWN_KEYWORDS = ["取り下げ", "廃止", "撤回"]
POSTPONED_KEYWORDS = ["延期", "見送り"]


def determine_midterm_status(title: str, metrics, classify: Callable[[], str]) -> str:
    """タイトルとmetricsから判定し、決まらなければclassify()（LLMの分類）を呼ぶ。

    値を持つmetricsが1件でもあればok。ただしタイトルが取り下げ等ならmetricsに関わらずwithdrawn。
    """
    has_metrics = bool(metrics) and any(m.get("value") is not None for m in metrics)
    if any(kw in title for kw in WITHDRAWN_KEYWORDS):
        return "withdrawn"
    if has_metrics:
        return "ok"
    if any(kw in title for kw in POSTPONED_KEYWORDS):
        return "postponed"
    return classify()
