# ProvenanceBase.metadataに全テーブルを登録する（未登録のテーブルがmigration・起動時チェックから漏れないようにする）
from tdnet_provenance.models import (  # noqa: F401
    processing_run,
    result_adoption,
    result_version,
    run_output,
    tdnet_source_document,
)
