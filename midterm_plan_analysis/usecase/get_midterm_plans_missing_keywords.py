from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from midterm_plan_analysis.models.midterm_plan import MidtermPlan
from midterm_plan_analysis.models.midterm_plan_keyword import MidtermPlanKeyword


def get_midterm_plans_missing_keywords(session: Session, limit: int) -> List[MidtermPlan]:
    """
    keyword抽出が未実施の midterm_plans 行を、開示日が新しい順に limit 件取得する。

    `extraction_status='ok'`（metrics抽出成功）かつ、`midterm_plan_keywords` に対応する行が
    1件も無いものを対象にする。処理済みの行は次回呼び出し時に自動的に対象から外れるため、
    同じlimitで繰り返し呼び出すだけで続きから再開できる（オフセット管理は不要）。
    """
    keyworded_urls = select(MidtermPlanKeyword.url)
    return (
        session.query(MidtermPlan)
        .filter(MidtermPlan.extraction_status == "ok", ~MidtermPlan.url.in_(keyworded_urls))
        .order_by(MidtermPlan.disclosure_date.desc())
        .limit(limit)
        .all()
    )
