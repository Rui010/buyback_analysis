from sqlalchemy import Float, Integer, String, Text

from buyback_analysis.models.base import Base
from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.processing_run import ProcessingRun
from tdnet_provenance.models.result_adoption import ResultAdoption
from tdnet_provenance.models.result_version import ResultVersion
from tdnet_provenance.models.tdnet_source_document import TdnetSourceDocument


def _columns(model):
    return {column.name: column for column in model.__table__.columns}


def test_provenance_tables_are_not_created_by_init_db():
    # init_db()はBase.metadataだけをcreate_allするため、履歴テーブルは別metadataに置く
    assert "tdnet_source_documents" not in Base.metadata.tables
    assert "processing_runs" not in Base.metadata.tables
    assert set(ProvenanceBase.metadata.tables) == {
        "tdnet_source_documents", "processing_runs", "result_versions", "result_adoptions", "run_outputs",
    }
    assert not set(ProvenanceBase.metadata.tables) & set(Base.metadata.tables)


def test_tdnet_source_document_columns():
    columns = _columns(TdnetSourceDocument)
    assert [c.name for c in TdnetSourceDocument.__table__.primary_key.columns] == ["url"]
    required = {
        "url", "source_document_id", "external_document_id", "disclosure_date",
        "storage_uri", "source_hash", "file_size", "observed_at",
    }
    for name in required:
        assert columns[name].nullable is False, name
    for name in ("published_at", "fetched_at"):
        assert columns[name].nullable is True, name
    assert isinstance(columns["file_size"].type, Integer)
    assert columns["source_document_id"].unique is True


def test_processing_run_columns():
    columns = _columns(ProcessingRun)
    assert [c.name for c in ProcessingRun.__table__.primary_key.columns] == ["run_id"]
    required = {
        "run_id", "input_locator", "input_hash", "run_kind", "stage", "code_commit",
        "generation_config", "reuse_key", "status", "started_at", "completed_at",
    }
    for name in required:
        assert columns[name].nullable is False, name
    optional = {
        "url", "source_document_id", "source_hash", "extractor_version", "prompt_name",
        "prompt_hash", "model_provider", "model_name", "outcome", "outcome_reason",
        "retry_of_run_id", "reused_run_id", "provider_request_id", "input_tokens",
        "output_tokens", "estimated_cost", "estimated_cost_currency", "error_code",
    }
    for name in optional:
        assert columns[name].nullable is True, name
    assert set(columns) == required | optional
    assert isinstance(columns["generation_config"].type, Text)
    assert isinstance(columns["input_tokens"].type, Integer)
    assert isinstance(columns["estimated_cost"].type, Float)
    assert isinstance(columns["status"].type, String)


def test_result_version_columns():
    columns = _columns(ResultVersion)
    assert [c.name for c in ResultVersion.__table__.primary_key.columns] == ["version_id"]
    for name in ("version_id", "url", "code", "result_type", "payload", "run_ids", "origin", "created_at"):
        assert columns[name].nullable is False, name
    assert columns["extraction_status"].nullable is True
    assert isinstance(columns["payload"].type, Text)


def test_result_adoption_columns():
    columns = _columns(ResultAdoption)
    assert [c.name for c in ResultAdoption.__table__.primary_key.columns] == ["adoption_id"]
    assert set(columns) == {"adoption_id", "url", "result_type", "version_id", "adopted_at"}
    for column in columns.values():
        assert column.nullable is False, column.name
