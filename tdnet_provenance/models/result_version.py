from sqlalchemy import Column, Index, String, Text

from tdnet_provenance.models.base import ProvenanceBase


class ResultVersion(ProvenanceBase):
    """1文書の抽出結果1回分。登録後は更新・削除しない。

    payloadは現行結果テーブル（midterm_plans等）に書いた行そのもののJSON
    （{テーブル名: [行の列値dict, ...]}。autoincrementのidは含めない）。
    """

    __tablename__ = "result_versions"
    __table_args__ = (Index("ix_result_versions_url_type", "url", "result_type"),)

    version_id = Column(String, primary_key=True)  # uuid4
    url = Column(String, nullable=False)
    code = Column(String, nullable=False)
    result_type = Column(String, nullable=False)  # midterm_plan / forecast_revision
    extraction_status = Column(String)
    payload = Column(Text, nullable=False)
    run_ids = Column(Text, nullable=False)  # この版を作ったrunのJSON配列。legacyは[]
    origin = Column(String, nullable=False)  # run / legacy（Step 2適用前の現行行を退避したもの）
    created_at = Column(String, nullable=False)
