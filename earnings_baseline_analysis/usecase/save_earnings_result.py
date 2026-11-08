"""業績ベースラインの抽出結果の保存。

通常時は従来どおりpost_earnings_baseline()で保存する。RERUN時は旧結果を削除せず、
成功した結果だけを版として採用し、失敗時は旧結果を維持する（tdnet_provenance.usecase.adopt_result）。
"""

from earnings_baseline_analysis.models.earnings_baseline import EarningsBaseline
from earnings_baseline_analysis.models.earnings_baseline_metric import EarningsBaselineMetric
from earnings_baseline_analysis.usecase.post_earnings_baseline import post_earnings_baseline
from tdnet_provenance.usecase.adopt_result import adopt_result, write_failure_placeholder

EARNINGS_RESULT_TYPE = "earnings_baseline"
EARNINGS_TABLES = (EarningsBaseline, EarningsBaselineMetric)  # 先頭がextraction_statusを持つ主テーブル


def save_earnings_result(
    session, *, rerun: bool, code: str, url: str, disclosure_date: str, data: dict, extraction_status: str,
) -> bool:
    def write(commit: bool) -> bool:
        return post_earnings_baseline(
            session=session, data=data, code=code, url=url, disclosure_date=disclosure_date,
            extraction_status=extraction_status, commit=commit,
        )

    if not rerun:
        return write(commit=True)
    if extraction_status == "failed":
        return write_failure_placeholder(session, tables=EARNINGS_TABLES, url=url, write_failed=lambda: write(commit=True))
    return adopt_result(
        session, result_type=EARNINGS_RESULT_TYPE, tables=EARNINGS_TABLES, url=url, code=code,
        extraction_status=extraction_status, run_ids=[], write_current=lambda: write(commit=False),
    )
