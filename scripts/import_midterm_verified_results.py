"""ローカル検証の結果（verify_midterm_targets.pyのresults.json）を、LLMを呼び直さずにSQLiteへ採用する。

--applyなしは読み取りだけ（各URLの現行状態と書き込み予定を表示）。--applyでは、
(1) オンラインバックアップ、(2) reference_values列の追加（未追加なら）、(3) URLごとに採用切替、の順に行う。
採用切替は既存のadopt_resultを通すため、現行行はlegacy版として残り旧版へ戻せる（新しい版はorigin=unrecorded）。

使い方:
    python -m scripts.import_midterm_verified_results --db-path <SQLiteファイル> --results <results.json>
    python -m scripts.import_midterm_verified_results --db-path <SQLiteファイル> --results <results.json> --apply

日次パイプラインが動いていない時間に実行すること。PostgreSQLのbuyback_midterm_plansにも
reference_values列を追加するまで、同期はmidterm_plansをスキップする。
"""

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from midterm_plan_analysis.usecase.import_verified_result import import_verified_result
from midterm_plan_analysis.usecase.migrate_reference_values import migrate_reference_values


def _engine(db_path: Path):
    return create_engine("sqlite://", creator=lambda: sqlite3.connect(str(db_path)), future=True)


def _backup(db_path: Path) -> Path:
    backup_path = db_path.with_name(f"{db_path.name}.bak-midterm-import-{datetime.now():%Y%m%d%H%M%S}")
    with sqlite3.connect(str(db_path)) as source, sqlite3.connect(str(backup_path)) as backup:
        source.backup(backup)
    return backup_path


def _preview(db_path: Path, entries: list[dict]) -> None:
    posix = db_path.as_posix()
    # UNC（//host/share/...）はURIでは file:////host/share/... と書く
    uri = f"file://{posix}" if posix.startswith("//") else f"file:{posix}"
    with sqlite3.connect(f"{uri}?mode=ro", uri=True) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(midterm_plans)")}
        print(f"reference_values列: {'あり' if 'reference_values' in columns else 'なし（--applyで追加）'}")
        for entry in entries:
            row = connection.execute(
                "SELECT code, extraction_status FROM midterm_plans WHERE url = ?", (entry["url"],)
            ).fetchone()
            versions = connection.execute(
                "SELECT COUNT(*) FROM result_versions WHERE url = ?", (entry["url"],)
            ).fetchone()[0]
            metrics = len(((entry.get("result") or {}).get("data") or {}).get("metrics") or [])
            print(f"{entry['security_code']} {entry['disclosure_date']} 現行={row} 版={versions} "
                  f"→ status={entry.get('extraction_status')} metrics={metrics}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="バックアップを作成してから書き込む")
    args = parser.parse_args()

    if not args.db_path.is_file():
        raise FileNotFoundError(f"SQLiteファイルが見つかりません: {args.db_path}")
    entries = [e for e in json.loads(args.results.read_text(encoding="utf-8")) if not e.get("error")]
    _preview(args.db_path, entries)
    if not args.apply:
        print("（dry-run: 書き込んでいません。--applyで実行）")
        return

    print(f"バックアップ: {_backup(args.db_path)}")
    engine = _engine(args.db_path)
    if "result_versions" not in inspect(engine).get_table_names():
        raise RuntimeError("履歴テーブルがありません。scripts/migrate_tdnet_provenance_tables.py を先に実行してください")
    print(f"列の追加: {migrate_reference_values(engine) or '追加不要'}")

    adopted = 0
    with sessionmaker(bind=engine, autoflush=False, future=True)() as session:
        for entry in entries:
            ok = import_verified_result(
                session, url=entry["url"], result=entry.get("result"), extraction_status=entry.get("extraction_status"),
            )
            adopted += ok
            print(f"{'採用' if ok else '未採用'}: {entry['security_code']} {entry['disclosure_date']} {entry['url']}")
    print(f"採用 {adopted}/{len(entries)}件")


if __name__ == "__main__":
    main()
