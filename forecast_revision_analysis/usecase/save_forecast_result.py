"""会社予想修正の抽出結果の保存。provenance有効時は版保存と採用切替を通す（docs/tdnet_provenance_design.md）。"""

from forecast_revision_analysis.models.forecast_revision_detail import ForecastRevisionDetail
from forecast_revision_analysis.models.forecast_revision_metric import ForecastRevisionMetric
from forecast_revision_analysis.usecase.post_forecast_revision import post_forecast_revision
from tdnet_provenance.usecase.adopt_result import adopt_result, write_failure_placeholder
from tdnet_provenance.usecase.provenance_recorder import ProvenanceRecorder

FORECAST_RESULT_TYPE = "forecast_revision"
FORECAST_TABLES = (ForecastRevisionDetail, ForecastRevisionMetric)  # 先頭がextraction_statusを持つ主テーブル


def save_forecast_result(
    session,
    recorder: ProvenanceRecorder | None,
    *,
    code: str,
    url: str,
    disclosure_date: str,
    data: dict,
    extraction_status: str,
) -> bool:
    """detail・metricsを保存し、成否を返す。

    recorderがなければ従来どおりpost_forecast_revision()で保存する。recorderがあれば、
    failedは旧採用を維持（現行行がなければfailed行を書く）、それ以外は版として保存し採用する。
    """

    def write(commit: bool) -> bool:
        return post_forecast_revision(
            session=session, data=data, code=code, url=url, disclosure_date=disclosure_date,
            extraction_status=extraction_status, commit=commit,
        )

    if recorder is None:
        return write(commit=True)
    if extraction_status == "failed":
        return write_failure_placeholder(session, tables=FORECAST_TABLES, url=url, write_failed=lambda: write(commit=True))
    return adopt_result(
        session, result_type=FORECAST_RESULT_TYPE, tables=FORECAST_TABLES, url=url, code=code,
        extraction_status=extraction_status, run_ids=recorder.document_run_ids,
        write_current=lambda: write(commit=False), clock=recorder.clock,
    )
