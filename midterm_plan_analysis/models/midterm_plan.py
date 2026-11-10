from sqlalchemy import Column, String, Integer, Text
from buyback_analysis.models.base import Base


class MidtermPlan(Base):
    __tablename__ = "midterm_plans"

    code = Column(String, primary_key=True)
    url = Column(String, primary_key=True)
    plan_name = Column(String, nullable=True)
    plan_start_year = Column(Integer, nullable=True)
    plan_end_year = Column(Integer, nullable=True)
    plan_start_period_label = Column(String, nullable=True)
    plan_end_period_label = Column(String, nullable=True)
    plan_start_fiscal_end = Column(String, nullable=True)
    plan_end_fiscal_end = Column(String, nullable=True)
    disclosure_date = Column(String, nullable=True)
    metrics = Column(Text, nullable=True)  # JSON文字列（目標の配列）
    # JSON文字列（目標表に並ぶ基準年の実績・見込・予想の配列）。この列より前の抽出（旧仕様）はnull
    reference_values = Column(Text, nullable=True)
    extraction_status = Column(String, nullable=True)  # ok / failed / withdrawn / no_targets / postponed / skipped
