"""運用原典台帳・processing run専用のDeclarative Base。

`init_db()`は`buyback_analysis.models.base.Base`だけを`create_all()`するため、
ここに登録したテーブルはパイプライン起動時に自動作成されない。
作成は`scripts/migrate_tdnet_provenance_tables.py`だけが行う。
"""

from sqlalchemy.orm import declarative_base

ProvenanceBase = declarative_base()
