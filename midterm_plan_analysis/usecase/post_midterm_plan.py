import json

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from buyback_analysis.interface.logger import Logger
from midterm_plan_analysis.models.midterm_plan import MidtermPlan

logger = Logger()


def post_midterm_plan(
    session: Session,
    data: dict,
    code: str,
    url: str,
    disclosure_date: str,
    extraction_status: str,
) -> None:
    """
    中期経営計画データをSQLiteに保存する。

    Args:
        session: SQLAlchemyセッション
        data: parse_text_by_llm() の返り値（"type" + "data" キーを持つ辞書）
        code: 証券コード（rowデータから渡す）
        url: ソースURL（rowデータから渡す）
        disclosure_date: 開示日（rowデータから渡す）
        extraction_status: ok / failed / withdrawn / no_targets
    """
    if data is None:
        logger.error("dataがNoneです")
        return

    inner = data.get("data", {})

    metrics = inner.get("metrics")
    metrics_json = json.dumps(metrics, ensure_ascii=False) if metrics is not None else None

    instance = MidtermPlan(
        code=code,
        url=url,
        plan_name=inner.get("plan_name"),
        plan_start_year=inner.get("plan_start_year"),
        plan_end_year=inner.get("plan_end_year"),
        disclosure_date=disclosure_date,
        metrics=metrics_json,
        extraction_status=extraction_status,
    )

    try:
        session.add(instance)
        session.commit()
        logger.info(f"中期経営計画を保存しました: {code} - {url}")
    except IntegrityError:
        session.rollback()
        logger.info(f"主キーエラーによりスキップしました: {code} - {url}")
    except Exception as e:
        session.rollback()
        logger.error(f"保存に失敗しました: {code} - {url} - {e}")
