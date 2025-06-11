from sqlalchemy import Column, Integer, String, Date, Text, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Correction(Base):
    __tablename__ = "corrections"

    id = Column(Integer, primary_key=True)
    code = Column(String, nullable=False)
    company_name = Column(String, nullable=False)
    disclosure_date = Column(Date, nullable=False)
    original_announcement_date = Column(Date, nullable=False)
    document_title = Column(String, nullable=False)
    correction_reason = Column(Text, nullable=True)
    corrections_json = Column(JSON, nullable=False)
