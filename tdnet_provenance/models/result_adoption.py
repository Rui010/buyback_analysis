from sqlalchemy import Column, Index, String

from tdnet_provenance.models.base import ProvenanceBase


class ResultAdoption(ProvenanceBase):
    """採用versionの追記記録。URL・result_typeごとに最新の行が現在の採用versionで、
    次の行のadopted_atまでがその版の採用期間。行は更新・削除しない。

    legacy版には採用行を作らない（過去の採用時刻は分からないため推測しない）。
    """

    __tablename__ = "result_adoptions"
    __table_args__ = (Index("ix_result_adoptions_url_type", "url", "result_type", "adopted_at"),)

    adoption_id = Column(String, primary_key=True)  # uuid4
    url = Column(String, nullable=False)
    result_type = Column(String, nullable=False)
    version_id = Column(String, nullable=False)
    adopted_at = Column(String, nullable=False)
