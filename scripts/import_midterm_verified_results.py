"""ローカル検証の結果（verify_midterm_targets.pyのresults.json）や、重複候補のレビューで直した結果
（review_midterm_duplicate_candidates.pyのレビュー用JSON）を、LLMを呼び直さずにSQLiteへ採用する。

--applyなしは読み取りだけ（各URLの現行状態と書き込み予定を表示）。--applyでは、
(1) オンラインバックアップ、(2) reference_values列の追加（未追加なら）、(3) URLごとに採用切替、の順に行う。
採用切替は既存のadopt_resultを通すため、現行行はlegacy版として残り旧版へ戻せる（新しい版はorigin=unrecorded）。

レビュー用JSON（"kind": "midterm_duplicate_review"）は、URLごとに取込み前に次を検査し、
満たさないURLは採用しない（import_reviewed_result.py）: 採用version ID・source hashが作成時と同じか、
schema・値・期末、正規化後に残る重複候補がすべてresolution=distinctか、現行から変更があるか。

使い方:
    python -m scripts.import_midterm_verified_results --db-path <SQLiteファイル> --results <results.json>
    python -m scripts.import_midterm_verified_results --db-path <SQLiteファイル> --results <results.json> --apply
    python -m scripts.import_midterm_verified_results --db-path <SQLiteファイル> --results <review.json> [--apply]

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

from midterm_plan_analysis.usecase.import_reviewed_result import import_reviewed_entry, prepare_reviewed_entry
from midterm_plan_analysis.usecase.import_verified_result import import_verified_result
from midterm_plan_analysis.usecase.migrate_reference_values import migrate_reference_values
from midterm_plan_analysis.usecase.review_duplicate_candidates import REVIEW_FORMAT_VERSION, REVIEW_KIND
from scripts.review_midterm_duplicate_candidates import readonly_engine, sqlite_readonly_uri


def _engine(db_path: Path):
    return create_engine("sqlite://", creator=lambda: sqlite3.connect(str(db_path)), future=True)


def _backup(db_path: Path) -> Path:
    backup_path = db_path.with_name(f"{db_path.name}.bak-midterm-import-{datetime.now():%Y%m%d%H%M%S}")
    with sqlite3.connect(str(db_path)) as source, sqlite3.connect(str(backup_path)) as backup:
        source.backup(backup)
    return backup_path


def _preview(db_path: Path, entries: list[dict]) -> None:
    with sqlite3.connect(sqlite_readonly_uri(db_path), uri=True) as connection:
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


def _print_check(entry: dict, ok: bool, errors: list[str], *, applied: bool) -> None:
    label = ("採用" if ok else "未採用") if applied else ("取込み可" if ok else "取込み不可")
    print(f"{label}: {entry.get('code')} {entry.get('disclosure_date')} {entry.get('url')}")
    for error in errors:
        print(f"  - {error}")


def _load_review_entries(document: dict) -> list[dict]:
    if document.get("format_version") != REVIEW_FORMAT_VERSION:
        raise ValueError(f"レビュー用JSONのformat_versionが違います: {document.get('format_version')!r}")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise ValueError("レビュー用JSONのentriesが配列ではありません")
    return entries


def _check_reviewed(db_path: Path, entries: list[dict]) -> int:
    """書き込まずに検査だけ行い、取込み可能な件数を返す。"""
    engine = readonly_engine(db_path)
    passed = 0
    with sessionmaker(bind=engine, autoflush=False, future=True)() as session:
        for entry in entries:
            result, errors = prepare_reviewed_entry(session, entry)
            passed += result is not None
            _print_check(entry, result is not None, errors, applied=False)
    engine.dispose()
    return passed


def run_import(db_path: Path, results_path: Path, *, apply: bool) -> int:
    """取り込み（apply=Falseなら検査・表示だけ）を行い、採用（または取込み可）の件数を返す。"""
    if not db_path.is_file():
        raise FileNotFoundError(f"SQLiteファイルが見つかりません: {db_path}")
    document = json.loads(results_path.read_text(encoding="utf-8"))
    reviewed = isinstance(document, dict) and document.get("kind") == REVIEW_KIND
    if reviewed:
        entries = _load_review_entries(document)
    else:
        entries = [e for e in document if not e.get("error")]
        _preview(db_path, entries)

    if not apply:
        count = _check_reviewed(db_path, entries) if reviewed else len(entries)
        print(f"（dry-run: 書き込んでいません。--applyで実行）{f' 取込み可 {count}/{len(entries)}件' if reviewed else ''}")
        return count

    print(f"バックアップ: {_backup(db_path)}")
    engine = _engine(db_path)
    if "result_versions" not in inspect(engine).get_table_names():
        raise RuntimeError("履歴テーブルがありません。scripts/migrate_tdnet_provenance_tables.py を先に実行してください")
    print(f"列の追加: {migrate_reference_values(engine) or '追加不要'}")

    adopted = 0
    with sessionmaker(bind=engine, autoflush=False, future=True)() as session:
        for entry in entries:
            if reviewed:
                ok, errors = import_reviewed_entry(session, entry)
                _print_check(entry, ok, errors, applied=True)
            else:
                ok = import_verified_result(
                    session, url=entry["url"], result=entry.get("result"),
                    extraction_status=entry.get("extraction_status"),
                )
                print(f"{'採用' if ok else '未採用'}: {entry['security_code']} {entry['disclosure_date']} {entry['url']}")
            adopted += ok
    engine.dispose()
    print(f"採用 {adopted}/{len(entries)}件")
    return adopted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="バックアップを作成してから書き込む")
    args = parser.parse_args()
    run_import(args.db_path, args.results, apply=args.apply)


if __name__ == "__main__":
    main()
