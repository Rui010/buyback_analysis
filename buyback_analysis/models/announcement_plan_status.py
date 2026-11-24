"""発表文書URLごとの自己株買い案件の現在状態（フロント提供用）.

buyback_plans / buyback_plan_projections から毎回まるごと作り直す派生表。
PostgreSQLへはこの表だけを同期するため、他テーブルへの外部キーは持たない。
"""

from sqlalchemy import BigInteger, Column, DateTime, Float, String

from buyback_analysis.models.base import Base


class AnnouncementPlanStatus(Base):
    __tablename__ = "announcement_plan_status"

    buyback_plan_id = Column(String, primary_key=True)
    announcement_url = Column(String, nullable=False, index=True)
    code = Column(String, nullable=False)
    plan_status = Column(String, nullable=False)
    current_shares = Column(BigInteger)
    current_amount_yen = Column(BigInteger)
    current_start_date = Column(String)
    current_end_date = Column(String)
    cumulative_shares_acquired = Column(BigInteger)
    cumulative_amount_spent_yen = Column(BigInteger)
    completion_shares_acquired = Column(Float)
    completion_amount_spent_yen = Column(BigInteger)
    # 累計 ÷ 現在の上限（0〜1の比率）。上限・累計のどちらかが欠けるか上限0ならNULL
    progress_rate_amount = Column(Float)
    progress_rate_shares = Column(Float)
    latest_progress_date = Column(String)
    aggregation_rule_version = Column(String, nullable=False)
    calculated_at = Column(DateTime(timezone=True), nullable=False)
