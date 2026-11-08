from sqlalchemy import Column, Float, Index, Integer, String, Text

from tdnet_provenance.models.base import ProvenanceBase


class ProcessingRun(ProvenanceBase):
    """抽出・判断runの追記専用履歴。INSERTのみで、既存行は更新・削除しない。

    token・費用・request ID・retry/reuse列はStep 3で使用する。後から列を追加する
    migrationを避けるため、Step 1の時点でNULL許容で用意している。
    """

    __tablename__ = "processing_runs"
    __table_args__ = (
        Index("ix_processing_runs_url", "url"),
        Index("ix_processing_runs_reuse_key", "reuse_key"),
    )

    run_id = Column(String, primary_key=True)  # uuid4
    url = Column(String)
    source_document_id = Column(String)  # PDF取得前に終わるrunはNULL
    input_locator = Column(String, nullable=False)  # PDF照合後はstorage_uri、それ以外はURL
    source_hash = Column(String(64))  # PDF照合前に終わったrunはNULL
    input_hash = Column(String(64), nullable=False)  # PDF以外の機械入力の正規化hash（PDFの絶対パスは含めない）
    run_kind = Column(String, nullable=False)  # extract / route
    stage = Column(String, nullable=False)  # eligibility / metrics / keywords / classification / stage1 / stage2
    code_commit = Column(String, nullable=False)
    extractor_version = Column(String)  # NULLのときreuse keyはcode_commitを使う
    prompt_name = Column(String)
    prompt_hash = Column(String(64))
    model_provider = Column(String)
    model_name = Column(String)
    generation_config = Column(Text, nullable=False)  # JSON
    reuse_key = Column(String(64), nullable=False)
    status = Column(String, nullable=False)  # succeeded / failed（Step 3でreused）
    outcome = Column(String)  # 判断runの業務上の結果（withdrawn等）
    outcome_reason = Column(String)
    started_at = Column(String, nullable=False)
    completed_at = Column(String, nullable=False)
    retry_of_run_id = Column(String)
    reused_run_id = Column(String)
    provider_request_id = Column(String)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    estimated_cost = Column(Float)
    estimated_cost_currency = Column(String)
    error_code = Column(String)
