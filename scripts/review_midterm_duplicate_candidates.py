"""中計の採用版から重複候補（possible_duplicate_target）を探し、レビュー用JSONに出す。LLMは呼ばない。

SQLiteは読み取り専用で開き、何も書かない（元の抽出結果・既存versionは変えない）。
自動では削除できない「同じ期の同じ目標かもしれない別ページの2行」を、人手・Chatが直すためのJSONを作る。
直したJSONは scripts/import_midterm_verified_results.py で取り込む（取込み前に前提・schema・値・期末・重複を再検査）。

使い方:
    python -m scripts.review_midterm_duplicate_candidates --db-path <SQLiteファイル> --out <review.json>
    python -m scripts.review_midterm_duplicate_candidates --db-path <SQLiteファイル> --out <review.json> --urls <URL>,<URL>

検査の条件は midterm_plan_analysis/usecase/detect_duplicate_candidates.py、
JSONの形は docs/midterm_plan_design.md「重複候補のレビュー」を参照。
"""

import argparse
import datetime
import json
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from midterm_plan_analysis.usecase.review_duplicate_candidates import build_review_document, build_review_entries
from tdnet_provenance.models.base import ProvenanceBase


def sqlite_readonly_uri(db_path: Path) -> str:
    posix = db_path.as_posix()
    # UNC（//host/share/...）はURIでは file:////host/share/... と書く
    uri = f"file://{posix}" if posix.startswith("//") else f"file:{posix}"
    return f"{uri}?mode=ro"


def readonly_engine(db_path: Path):
    uri = sqlite_readonly_uri(db_path)
    return create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True), future=True)


def export_review(db_path: Path, out_path: Path, urls=None, clock=None) -> dict:
    if not db_path.is_file():
        raise FileNotFoundError(f"SQLiteファイルが見つかりません: {db_path}")
    engine = readonly_engine(db_path)
    missing = sorted(set(ProvenanceBase.metadata.tables) - set(inspect(engine).get_table_names()))
    if missing:
        raise RuntimeError(f"履歴テーブルがありません: {missing}。scripts/migrate_tdnet_provenance_tables.py を先に実行してください")
    now = (clock or (lambda: datetime.datetime.now(datetime.timezone.utc)))()
    with sessionmaker(bind=engine, autoflush=False, future=True)() as session:
        document = build_review_document(build_review_entries(session, urls=urls), generated_at=now.isoformat())
    engine.dispose()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--urls", default="", help="カンマ区切り。省略時はextraction_status=okの全文書")
    args = parser.parse_args()

    urls = [u.strip() for u in args.urls.split(",") if u.strip()]
    document = export_review(args.db_path, args.out, urls=urls or None)
    entries = document["entries"]
    for entry in entries:
        print(f"{entry['code']} {entry['disclosure_date']} 候補{len(entry['candidates'])}件 "
              f"version={entry['adopted_version_id']} {entry['url']}")
        for candidate in entry["candidates"]:
            print(f"  - {candidate['candidate_id']} {','.join(candidate['reasons'])}: {candidate['detail']}")
    print(f"重複候補のある文書 {len(entries)}件 / 候補 {sum(len(e['candidates']) for e in entries)}件 → {args.out}")


if __name__ == "__main__":
    main()
