from sqlalchemy import Column, String, Text
from buyback_analysis.models.base import Base


class ForecastRevisionDetail(Base):
    __tablename__ = "forecast_revision_details"

    code = Column(String, primary_key=True)
    url = Column(String, primary_key=True)
    disclosure_date = Column(String)
    prev_forecast_date = Column(String)
    value_unit = Column(String)          # 財務数値の単位（百万円 / 千円）。EPS・配当は常に円のため対象外
    reason_raw = Column(Text)
    direct_factors = Column(Text)           # JSON配列文字列
    structural_vulnerability = Column(Text) # JSON配列文字列
    spillover_conditions = Column(Text)     # JSON配列文字列
    llm_model = Column(String)
    extraction_status = Column(String)      # ok / no_periods / failed / withdrawn / correction
    extracted_at = Column(String)           # "%Y-%m-%d %H:%M:%S"
