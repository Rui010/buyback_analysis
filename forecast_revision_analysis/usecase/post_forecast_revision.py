import json
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from buyback_analysis.interface.logger import Logger
from buyback_analysis.consts.llm_model import LlmModel
from forecast_revision_analysis.models.forecast_revision_detail import ForecastRevisionDetail
from forecast_revision_analysis.models.forecast_revision_metric import ForecastRevisionMetric

logger = Logger()


def _to_float(v) -> float | None:
    """LLMが文字列で返した数値をfloatに変換する。変換不能な場合はNone。"""
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _to_int(v) -> int | None:
    """LLMが文字列で返した年をintに変換する。変換不能な場合はNone。"""
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _calc_change_pct(prev: float | None, curr: float | None) -> float | None:
    """対称変化率 2*(curr-prev)/(|prev|+|curr|)*100 を返す（-200%〜+200% に収まる）。"""
    if prev is None or curr is None:
        return None
    denom = abs(prev) + abs(curr)
    if denom == 0:
        return 0.0
    return round(2 * (curr - prev) / denom * 100, 1)


_PERIOD_REQUIRED_FIELDS = ["metric_name", "label_raw", "prev_value", "curr_value", "fiscal_year", "consolidation_type"]


def check_missing_fields(data: dict, code: str, url: str) -> bool:
    """
    extraction_status=ok のレコードに対して重要フィールドの欠損をチェックする。

    欠損があれば [MISSING] プレフィックスでログに記録する。
    Returns:
        True: 欠損あり / False: 欠損なし
    """
    inner = data.get("data", {})
    has_missing = False

    if inner.get("prev_forecast_date") is None:
        logger.info(f"[MISSING] field=prev_forecast_date code={code} url={url}")
        has_missing = True

    for i, period in enumerate(inner.get("periods", [])):
        for field in _PERIOD_REQUIRED_FIELDS:
            if period.get(field) is None:
                logger.info(
                    f"[MISSING] field=periods[{i}].{field}"
                    f" period_type={period.get('period_type')}"
                    f" code={code} url={url}"
                )
                has_missing = True

    return has_missing


def post_forecast_revision(
    session: Session,
    data: dict,
    code: str,
    url: str,
    disclosure_date: str,
    extraction_status: str,
) -> bool:
    """
    業績予想修正データをSQLiteに保存する。

    Args:
        session: SQLAlchemyセッション
        data: parse_text_by_llm() の返り値（"type" + "data" キーを持つ辞書）
        code: 証券コード
        url: ソースURL
        disclosure_date: 開示日
        extraction_status: ok / no_periods / failed / withdrawn / correction

    Returns:
        True: 保存成功または重複スキップ / False: 保存失敗
    """
    if data is None:
        logger.error("dataがNoneです")
        return False

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
            prev = _to_float(period.get("prev_value"))
            curr = _to_float(period.get("curr_value"))
            is_modified = 0 if prev == curr else 1
            metric = ForecastRevisionMetric(
                url=url,
                period_type=period.get("period_type"),
                fiscal_year=_to_int(period.get("fiscal_year")),
                consolidation_type=period.get("consolidation_type"),
                metric_name=period.get("metric_name"),
                label_raw=period.get("label_raw"),
                prev_value=prev,
                prev_value_upper=_to_float(period.get("prev_value_upper")),
                curr_value=curr,
                curr_value_upper=_to_float(period.get("curr_value_upper")),
                prev_year_actual=_to_float(period.get("prev_year_actual")),
                change_pct=_calc_change_pct(prev, curr),
                is_modified=is_modified,
            )
            session.add(metric)

        session.commit()
        logger.info(f"業績予想修正を保存しました: {code} - {url}")
        return True
    except IntegrityError as e:
        session.rollback()
        # 呼び出し元の_already_exists()で既存レコードは事前に除外済みのため、ここに到達する
        # IntegrityErrorは「既に保存済みなので安全にスキップ」ではなく、多くの場合
        # periods内の自然キー重複（例: metric_nameの正規化で複数指標が同じキーに丸められた）
        # のような実データ上の問題である。Falseを返し、呼び出し元に「保存失敗」として
        # 検知・カウントさせる（詳細はdocs/forecast_revision_llm_pipeline_redesign.md参照）。
        logger.error(f"主キーエラーにより保存に失敗しました: {code} - {url} - {e}")
        return False
    except Exception as e:
        session.rollback()
        logger.error(f"保存に失敗しました: {code} - {url} - {e}")
        return False
