import json
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from buyback_analysis.interface.logger import Logger
from buyback_analysis.consts.llm_model import LlmModel
from forecast_revision_analysis.models.forecast_revision_detail import ForecastRevisionDetail
from forecast_revision_analysis.models.forecast_revision_metric import ForecastRevisionMetric

logger = Logger()


def _calc_change_pct(prev: float | None, curr: float | None) -> float | None:
    """増減率を計算する。ゼロクロス・ゼロ除算はnullを返す（日本の財務慣行に準拠）。"""
    if prev is None or curr is None:
        return None
    if prev == 0:
        return None
    if (prev > 0 and curr < 0) or (prev < 0 and curr > 0):
        return None
    return round((curr - prev) / abs(prev) * 100, 1)


def post_forecast_revision(
    session: Session,
    data: dict,
    code: str,
    url: str,
    disclosure_date: str,
    extraction_status: str,
) -> None:
    """
    業績予想修正データをSQLiteに保存する。

    Args:
        session: SQLAlchemyセッション
        data: parse_text_by_llm() の返り値（"type" + "data" キーを持つ辞書）
        code: 証券コード
        url: ソースURL
        disclosure_date: 開示日
        extraction_status: ok / no_periods / failed / withdrawn / correction
    """
    if data is None:
        logger.error("dataがNoneです")
        return

    inner = data.get("data", {})

    detail = ForecastRevisionDetail(
        code=code,
        url=url,
        disclosure_date=disclosure_date,
        prev_forecast_date=inner.get("prev_forecast_date"),
        value_unit=inner.get("value_unit"),
        reason_raw=inner.get("reason_raw"),
        direct_factors=json.dumps(inner.get("direct_factors"), ensure_ascii=False),
        structural_vulnerability=json.dumps(inner.get("structural_vulnerability"), ensure_ascii=False),
        spillover_conditions=json.dumps(inner.get("spillover_conditions"), ensure_ascii=False),
        llm_model=LlmModel.LLM_MODEL_GEMINI.value,
        extraction_status=extraction_status,
        extracted_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    try:
        session.add(detail)
        session.flush()

        for period in inner.get("periods", []):
            metric = ForecastRevisionMetric(
                url=url,
                period_type=period.get("period_type"),
                metric_name=period.get("metric_name"),
                label_raw=period.get("label_raw"),
                prev_value=period.get("prev_value"),
                prev_value_upper=period.get("prev_value_upper"),
                curr_value=period.get("curr_value"),
                curr_value_upper=period.get("curr_value_upper"),
                change_pct=_calc_change_pct(period.get("prev_value"), period.get("curr_value")),
                is_modified=period.get("is_modified"),
            )
            session.add(metric)

        session.commit()
        logger.info(f"業績予想修正を保存しました: {code} - {url}")
    except IntegrityError:
        session.rollback()
        logger.info(f"主キーエラーによりスキップしました: {code} - {url}")
    except Exception as e:
        session.rollback()
        logger.error(f"保存に失敗しました: {code} - {url} - {e}")
