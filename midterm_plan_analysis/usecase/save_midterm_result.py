"""中計の抽出結果の保存。provenance有効時は版保存と採用切替を通す（docs/tdnet_provenance_design.md）。"""

from midterm_plan_analysis.models.midterm_plan import MidtermPlan
from midterm_plan_analysis.models.midterm_plan_keyword import MidtermPlanKeyword
from midterm_plan_analysis.usecase.post_midterm_keywords import post_midterm_keywords
from midterm_plan_analysis.usecase.post_midterm_plan import post_midterm_plan
from tdnet_provenance.usecase.adopt_result import adopt_result, write_failure_placeholder
from tdnet_provenance.usecase.provenance_recorder import ProvenanceRecorder

MIDTERM_RESULT_TYPE = "midterm_plan"
MIDTERM_TABLES = (MidtermPlan, MidtermPlanKeyword)  # 先頭がextraction_statusを持つ主テーブル

KEYWORDS_NOT_REQUESTED = object()


def save_midterm_result(
    session,
    recorder: ProvenanceRecorder | None,
    *,
    code: str,
    url: str,
    disclosure_date: str,
    data: dict,
    extraction_status: str,
    keywords=KEYWORDS_NOT_REQUESTED,
) -> bool:
    """計画（とキーワード抽出を行った場合はキーワード）を保存し、成否を返す。

    recorderがなければ従来どおりキーワード→計画の順に保存する。recorderがあれば、
    failedは旧採用を維持（現行行がなければfailed行を書く）、それ以外は版として保存し採用する。
    """

    def write(commit: bool) -> bool:
        if keywords is not KEYWORDS_NOT_REQUESTED:
            saved_keywords = post_midterm_keywords(
                session=session, code=code, url=url, disclosure_date=disclosure_date,
                keywords=keywords, commit=commit,
            )
            # 採用切替中はキーワードだけ欠けた版を作らない（従来経路はキーワード失敗でも計画を保存する）
            if not saved_keywords and not commit:
                return False
        return post_midterm_plan(
            session=session, data=data, code=code, url=url, disclosure_date=disclosure_date,
            extraction_status=extraction_status, commit=commit,
        )

    if recorder is None:
        return write(commit=True)
    if extraction_status == "failed":
        return write_failure_placeholder(session, tables=MIDTERM_TABLES, url=url, write_failed=lambda: write(commit=True))
    return adopt_result(
        session, result_type=MIDTERM_RESULT_TYPE, tables=MIDTERM_TABLES, url=url, code=code,
        extraction_status=extraction_status, run_ids=recorder.document_run_ids,
        write_current=lambda: write(commit=False), clock=recorder.clock,
    )


def save_backfilled_keywords(session, recorder: ProvenanceRecorder | None, *, plan, keywords) -> bool:
    """backfill_keywords.py用。既存の計画行は変えずにキーワードだけを追加する。

    recorderがあれば、既存の計画＋追加したキーワードを新しい版として採用する。
    """

    def write(commit: bool) -> bool:
        return post_midterm_keywords(
            session=session, code=plan.code, url=plan.url, disclosure_date=plan.disclosure_date,
            keywords=keywords, commit=commit,
        )

    if recorder is None:
        return write(commit=True)
    return adopt_result(
        session, result_type=MIDTERM_RESULT_TYPE, tables=MIDTERM_TABLES, url=plan.url, code=plan.code,
        extraction_status=plan.extraction_status, run_ids=recorder.document_run_ids,
        write_current=lambda: write(commit=False), clock=recorder.clock, replace_current=False,
    )
