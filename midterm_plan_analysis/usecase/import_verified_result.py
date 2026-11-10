"""ローカル検証（scripts/verify_midterm_targets.py）で抽出済みの結果を、LLMを呼び直さずに採用する。

既存の採用切替（adopt_result）を通すため、現行行は旧版（legacy）としてresult_versionsに残り、
旧版へ戻せる。run記録はないため新しい版はorigin=unrecordedになる。
現行のキーワード行は新しい版へそのまま引き継ぐ（検証ではキーワード抽出をしていないため）。
"""

import datetime

from midterm_plan_analysis.models.midterm_plan import MidtermPlan
from midterm_plan_analysis.models.midterm_plan_keyword import MidtermPlanKeyword
from midterm_plan_analysis.usecase.post_midterm_plan import post_midterm_plan
from midterm_plan_analysis.usecase.save_midterm_result import MIDTERM_RESULT_TYPE, MIDTERM_TABLES
from tdnet_provenance.usecase.adopt_result import adopt_result


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def import_verified_result(session, *, url: str, result, extraction_status: str, clock=_utc_now) -> bool:
    """現行のmidterm_plans行があるURLだけ、resultを新しい版として採用する。成否を返す。

    resultがない・failedの場合や現行行がない場合は何も書かずFalse（新しい行は作らない）。
    """
    if result is None or extraction_status == "failed":
        return False
    current = session.query(MidtermPlan).filter(MidtermPlan.url == url).one_or_none()
    if current is None:
        return False
    code, disclosure_date = current.code, current.disclosure_date
    keyword_rows = [
        {c.name: getattr(k, c.name) for c in MidtermPlanKeyword.__table__.columns if c.name != "id"}
        for k in session.query(MidtermPlanKeyword).filter(MidtermPlanKeyword.url == url).all()
    ]

    def write_current() -> bool:
        for row in keyword_rows:
            session.add(MidtermPlanKeyword(**row))
        session.flush()
        return post_midterm_plan(
            session=session, data=result, code=code, url=url, disclosure_date=disclosure_date,
            extraction_status=extraction_status, commit=False,
        )

    return adopt_result(
        session, result_type=MIDTERM_RESULT_TYPE, tables=MIDTERM_TABLES, url=url, code=code,
        extraction_status=extraction_status, run_ids=[], write_current=write_current, clock=clock,
    )
