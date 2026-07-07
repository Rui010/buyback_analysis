from sqlalchemy import Column, Integer, String, UniqueConstraint
from buyback_analysis.models.base import Base


class MidtermPlanKeyword(Base):
    __tablename__ = "midterm_plan_keywords"
    __table_args__ = (
        UniqueConstraint("code", "url", "keyword", name="uq_midterm_plan_keywords_natural_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String, nullable=False)
    url = Column(String, nullable=False)  # midterm_plans.url に対応
    keyword = Column(String, nullable=False)  # LLM抽出時の生表記
    context_raw = Column(String, nullable=True)  # キーワードが言及されている一文程度の逐語引用
    disclosure_date = Column(String, nullable=True)
    normalized_keyword = Column(String, nullable=True)  # 正規化後の表記（フェーズ2で使用、当面は未使用）
