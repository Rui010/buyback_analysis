# ProvenanceBase.metadataに全テーブルを登録する（未登録のテーブルがmigration・起動時チェックから漏れないようにする）
from tdnet_provenance.models import processing_run, result_adoption, result_version, tdnet_source_document  # noqa: F401
