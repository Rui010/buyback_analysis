import json

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from buyback_analysis.interface.logger import Logger
from midterm_plan_analysis.models.midterm_plan import MidtermPlan

logger = Logger()

VALID_EXTRACTION_STATUSES = {"ok", "failed", "withdrawn", "no_targets", "postponed", "skipped"}


def post_midterm_plan(
    session: Session,
    data: dict,
    code: str,
    url: str,
    disclosure_date: str,
    extraction_status: str,
    commit: bool = True,
) -> bool:
    """
    中期経営計画データをSQLiteに保存する。

    Args:
        session: SQLAlchemyセッション
        data: parse_text_by_llm() の返り値（"type" + "data" キーを持つ辞書）
        code: 証券コード（rowデータから渡す）
        url: ソースURL（rowデータから渡す）
        disclosure_date: 開示日（rowデータから渡す）
        extraction_status: ok / failed / withdrawn / no_targets / postponed / skipped
            （前後の空白は除去し、それ以外の値は保存しない）
        commit: Falseならcommitせずflushだけ行い、失敗時のrollbackも呼び出し側に任せる
            （採用版切替のトランザクションに含めるため）

    Returns:
        保存に成功した場合 True。dataがNone・不正なextraction_status・主キー重複・
        その他の保存失敗（database is locked 等）の場合 False。
    """
    if data is None:
        logger.error("dataがNoneです")
        return False

    status = extraction_status.strip() if isinstance(extraction_status, str) else extraction_status
    if status not in VALID_EXTRACTION_STATUSES:
        logger.error(f"不正なextraction_statusのため保存しません: {extraction_status!r} {code} - {url}")
        return False

    inner = data.get("data", {})

    metrics = inner.get("metrics")
    metrics_json = json.dumps(metrics, ensure_ascii=False) if metrics is not None else None

    instance = MidtermPlan(
        code=code,
        url=url,
        plan_name=inner.get("plan_name"),
        plan_start_year=inner.get("plan_start_year"),
        plan_end_year=inner.get("plan_end_year"),
        plan_start_period_label=inner.get("plan_start_period_label"),
        plan_end_period_label=inner.get("plan_end_period_label"),
        plan_start_fiscal_end=inner.get("plan_start_fiscal_end"),
        plan_end_fiscal_end=inner.get("plan_end_fiscal_end"),
        disclosure_date=disclosure_date,
        metrics=metrics_json,
        extraction_status=status,
    )

    try:
        session.add(instance)
        session.commit() if commit else session.flush()
        logger.info(f"中期経営計画を保存しました: {code} - {url}")
        return True
    except IntegrityError:
        if commit:
            session.rollback()
        logger.info(f"主キーエラーによりスキップしました: {code} - {url}")
        return False
    except Exception as e:
        if commit:
            session.rollback()
        logger.error(f"保存に失敗しました: {code} - {url} - {e}")
        return False
