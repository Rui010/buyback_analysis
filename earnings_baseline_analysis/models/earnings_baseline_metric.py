from sqlalchemy import Column, Integer, String, Float, UniqueConstraint
from buyback_analysis.models.base import Base


class EarningsBaselineMetric(Base):
    __tablename__ = "earnings_baseline_metrics"
    __table_args__ = (
        UniqueConstraint(
            "code", "fiscal_year", "period_type", "consolidation_type", "metric_name", "value_type",
            name="uq_earnings_baseline_metrics_natural_key",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String, nullable=False)
    url = Column(String, nullable=False)          # earnings_baselines.url に対応（非正規化・追跡用。自然キーには含めない）
    fiscal_year = Column(Integer)                  # actualはfiscal_year_actual、initial_forecastはfiscal_year_forecastと一致
    period_type = Column(String, nullable=False)   # '1q'/'2q'/'3q'/'4q'（4q=通期）。forecast_revision_metricsのPeriodTypeと同じ語彙
    consolidation_type = Column(String)            # 'consolidated' / 'non_consolidated'
    metric_name = Column(String, nullable=False)   # 正規化指標名
    value_type = Column(String, nullable=False)    # 'actual'（当期実績）/ 'initial_forecast'（次期初回予想）
    label_raw = Column(String)
    value = Column(Float)
    value_upper = Column(Float)                    # レンジの上限（レンジでない場合はnull）
