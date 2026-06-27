from sqlalchemy import Column, String, Integer, Text
from buyback_analysis.models.base import Base


class MidtermPlan(Base):
    __tablename__ = "midterm_plans"

    code = Column(String, primary_key=True)
    url = Column(String, primary_key=True)
    plan_name = Column(String, nullable=True)
    plan_start_year = Column(Integer, nullable=True)
    plan_end_year = Column(Integer, nullable=True)
    disclosure_date = Column(String, nullable=True)
    metrics = Column(Text, nullable=True)  # JSON文字列
    extraction_status = Column(String, nullable=True)  # ok / failed / withdrawn / no_targets / postponed / skipped
