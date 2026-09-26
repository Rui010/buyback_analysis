"""SQLiteの自己株買い4テーブルをURL主キーへ移行するエントリーポイント。"""

import sys
from pathlib import Path

# ``python scripts/...`` で実行してもリポジトリ直下のパッケージを解決できるようにする。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buyback_analysis.interface.sqlite_engine import engine
from buyback_analysis.usecase.migrate_url_primary_keys import migrate_url_primary_keys


if __name__ == "__main__":
    migrated = migrate_url_primary_keys(engine)
    print(f"URL主キー移行完了: {', '.join(migrated) if migrated else '対象テーブルなし'}")
