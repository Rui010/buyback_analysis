from forecast_revision_analysis.models.forecast_revision_detail import ForecastRevisionDetail


def already_processed(session, code: str, url: str) -> bool:
    record = session.get(ForecastRevisionDetail, {'code': code, 'url': url})
    return record is not None and record.extraction_status != 'failed'


def get_failed_urls(session) -> list[str]:
    """日付範囲から外れた失敗も再試行対象に含める。"""
    rows = (session.query(ForecastRevisionDetail.url)
            .filter(ForecastRevisionDetail.extraction_status == 'failed')
            .order_by(ForecastRevisionDetail.disclosure_date, ForecastRevisionDetail.url).all())
    return list(dict.fromkeys(row[0] for row in rows))
