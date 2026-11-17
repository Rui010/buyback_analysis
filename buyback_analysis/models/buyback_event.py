from sqlalchemy import Boolean, Column, Integer, JSON, String

from buyback_analysis.models.base import Base


class BuybackEvent(Base):
    __tablename__ = "buyback_events"

    event_uid = Column(String, primary_key=True)
    version_id = Column(String, nullable=False, index=True)
    url = Column(String, nullable=False, index=True)
    document_title = Column(String)
    disclosure_datetime = Column(String)
    code = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    event_fingerprint = Column(String, nullable=False)
    event_date = Column(String)
    resolution_date = Column(String)
    referenced_document_date = Column(String)
    referenced_document_title = Column(String)
    source_quote = Column(String, nullable=False)
    source_quote_verified = Column(Boolean, nullable=False, default=False)
    source_page = Column(Integer)
    source_section = Column(String)
    payload = Column(JSON, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
