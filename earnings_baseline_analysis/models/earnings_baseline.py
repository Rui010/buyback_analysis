from sqlalchemy import Column, Integer, String
from buyback_analysis.models.base import Base


class EarningsBaseline(Base):
    __tablename__ = "earnings_baselines"

    code = Column(String, primary_key=True)
    url = Column(String, primary_key=True)
    disclosure_date = Column(String)
    fiscal_year_actual = Column(Integer)      # 当期実績の対象年度（例:「2026年3月期」→2026）
    fiscal_year_forecast = Column(Integer)    # 次期初回予想の対象年度（fiscal_year_actual + 1が基本だが決算期変更時は非連続もありうるためLLMが個別抽出）
    llm_model = Column(String)
    extraction_status = Column(String)        # ok / no_data / failed
    extracted_at = Column(String)             # "%Y-%m-%d %H:%M:%S"
