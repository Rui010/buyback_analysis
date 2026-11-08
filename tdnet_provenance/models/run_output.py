from sqlalchemy import Column, String, Text

from tdnet_provenance.models.base import ProvenanceBase


class RunOutput(ProvenanceBase):
    """成功したLLM runの出力（LLM関数の戻り値のJSON）。同じreuse keyのrunを再利用するときに返す。
    登録後は更新・削除しない。"""

    __tablename__ = "run_outputs"

    run_id = Column(String, primary_key=True)  # processing_runs.run_id
    output = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)
