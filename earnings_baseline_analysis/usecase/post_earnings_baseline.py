from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from buyback_analysis.interface.logger import Logger
from buyback_analysis.consts.llm_model import LlmModel
from earnings_baseline_analysis.models.earnings_baseline import EarningsBaseline
from earnings_baseline_analysis.models.earnings_baseline_metric import EarningsBaselineMetric

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


def _metric_natural_key(item: tuple) -> tuple:
    metric, value_type, fiscal_year = item
    return (
        fiscal_year,
        metric.get("period_type"),
        metric.get("consolidation_type"),
        metric.get("metric_name"),
        value_type,
    )


def _prefer_candidate(candidate: dict, existing: dict) -> bool:
    """
    同一自然キーのmetricが2件ある場合、candidateをexistingより優先すべきか判定する。

    forecast_revision_analysisの_prefer_candidate()と同じ理由（IFRS決算で「当期利益」と
    「親会社の所有者に帰属する当期利益」が別行として開示され、net_incomeに丸められた際に
    重複するケース）でnet_incomeの優先順位を判定する。
    """
    if candidate.get("metric_name") == "net_income":
        candidate_is_parent = "親会社" in (candidate.get("label_raw") or "")
        existing_is_parent = "親会社" in (existing.get("label_raw") or "")
        if candidate_is_parent and not existing_is_parent:
            return True
    return False


def _deduplicate_metrics(items: list, code: str, url: str) -> list:
    """
    earnings_baseline_metricsの自然キー（fiscal_year, period_type, consolidation_type,
    metric_name, value_type）で重複するmetricを除去する。

    forecast_revision_analysisの_deduplicate_periods()と同じ理由（LLMのmetric_name正規化で
    同一自然キーの行が複数返り、そのままINSERTするとUNIQUE制約違反で文書全体がロールバック
    されてしまう）で、保存前にコード側で重複排除する。
    """
    kept: dict = {}
    for item in items:
        key = _metric_natural_key(item)
        if key not in kept:
            kept[key] = item
            continue

        existing_metric, _, _ = kept[key]
        candidate_metric, _, _ = item
        if _prefer_candidate(candidate_metric, existing_metric):
            dropped, kept[key] = kept[key], item
        else:
            dropped = item
        dropped_metric, _, _ = dropped
        logger.info(
            f"[DUPLICATE] 自然キー重複のためmetricを除外しました: key={key}"
            f" label_raw={dropped_metric.get('label_raw')} code={code} url={url}"
        )
    return list(kept.values())


def post_earnings_baseline(
    session: Session,
    data: dict,
    code: str,
    url: str,
    disclosure_date: str,
    extraction_status: str,
) -> bool:
    """
    決算短信の起点データ（前期実績・当期初回予想）をSQLiteに保存する。

    Args:
        session: SQLAlchemyセッション
        data: parse_text_by_llm() の返り値（"type" + "data" キーを持つ辞書）
        code: 証券コード
        url: ソースURL
        disclosure_date: 開示日
        extraction_status: ok / no_data / failed

    Returns:
        True: 保存成功 / False: 保存失敗
    """
    if data is None:
        logger.error("dataがNoneです")
        return False

    inner = data.get("data", {})
    fiscal_year_actual = _to_int(inner.get("fiscal_year_actual"))
    fiscal_year_forecast = _to_int(inner.get("fiscal_year_forecast"))

    baseline = EarningsBaseline(
        code=code,
        url=url,
        disclosure_date=disclosure_date,
        fiscal_year_actual=fiscal_year_actual,
        fiscal_year_forecast=fiscal_year_forecast,
        llm_model=LlmModel.LLM_MODEL_GEMINI.value,
        extraction_status=extraction_status,
        extracted_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    try:
        session.add(baseline)
        session.flush()

        combined = (
            [(m, "actual", fiscal_year_actual) for m in inner.get("actual_metrics", [])]
            + [(m, "initial_forecast", fiscal_year_forecast) for m in inner.get("initial_forecast_metrics", [])]
        )

        for metric_dict, value_type, fiscal_year in _deduplicate_metrics(combined, code, url):
            metric = EarningsBaselineMetric(
                code=code,
                url=url,
                fiscal_year=fiscal_year,
                period_type=metric_dict.get("period_type"),
                consolidation_type=metric_dict.get("consolidation_type"),
                metric_name=metric_dict.get("metric_name"),
                value_type=value_type,
                label_raw=metric_dict.get("label_raw"),
                value=_to_float(metric_dict.get("value")),
                value_upper=_to_float(metric_dict.get("value_upper")),
            )
            session.add(metric)

        session.commit()
        logger.info(f"決算短信の起点データを保存しました: {code} - {url}")
        return True
    except IntegrityError as e:
        session.rollback()
        logger.error(f"主キーエラーにより保存に失敗しました: {code} - {url} - {e}")
        return False
    except Exception as e:
        session.rollback()
        logger.error(f"保存に失敗しました: {code} - {url} - {e}")
        return False
