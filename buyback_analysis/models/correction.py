from sqlalchemy import Column, Integer, String, Date, Text, JSON
from buyback_analysis.models.base import Base


class Correction(Base):
    __tablename__ = "corrections"

    id = Column(Integer, primary_key=True)
    code = Column(String, nullable=False)
    url = Column(String)
    company_name = Column(String, nullable=False)
    disclosure_date = Column(String, nullable=False)
    original_announcement_date = Column(String, nullable=False)
    document_title = Column(String, nullable=False)
    correction_reason = Column(Text, nullable=True)
    corrections = Column(JSON, nullable=False)
