from sqlalchemy import Column, Integer, String, Float
from buyback_analysis.models.base import Base


class ForecastRevisionMetric(Base):
    __tablename__ = "forecast_revision_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String, nullable=False)         # forecast_revision_details.url に対応
    period_type = Column(String, nullable=False) # '1q'/'2q'/'3q'/'4q'（4q=通期）
    metric_name = Column(String, nullable=False) # 正規化指標名
    label_raw = Column(String)
    prev_value = Column(Float)
    prev_value_upper = Column(Float)
    curr_value = Column(Float)
    curr_value_upper = Column(Float)
    prev_year_actual = Column(Float)          # 前年同期実績値（表に「前年同期実績」列があれば。なければnull）
    change_pct = Column(Float)
    is_modified = Column(Integer)                # 0=据え置き / 1=修正あり
