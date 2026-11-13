"""中計の採用版から重複候補（possible_duplicate_target）を探し、レビュー用JSONに出す。LLMは呼ばない。

SQLiteは読み取り専用で開き、何も書かない（元の抽出結果・既存versionは変えない）。
自動では削除できない「同じ期の同じ目標かもしれない別ページの2行」を、人手・Chatが直すためのJSONを作る。
レビュー・手修正は下流（PostgreSQL側）で行い、SQLiteへは書き戻さない。

使い方:
    python -m scripts.review_midterm_duplicate_candidates                      # .envのSQLITE_DB_URLのDB
    python -m scripts.review_midterm_duplicate_candidates --db-path <SQLiteファイル>
    python -m scripts.review_midterm_duplicate_candidates --db-path <SQLiteファイル> --out <review.json> --urls <URL>,<URL>

--outを省略すると、SQLiteファイルと同じ場所の midterm_duplicate_review/review_<日時>.json に出す。

検査の条件は midterm_plan_analysis/usecase/detect_duplicate_candidates.py、
JSONの形は docs/midterm_plan_design.md「重複候補のレビュー」を参照。
"""

import argparse
import datetime
import json
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from midterm_plan_analysis.usecase.review_duplicate_candidates import build_review_document, build_review_entries
from tdnet_provenance.models.base import ProvenanceBase


def sqlite_readonly_uri(db_path: Path) -> str:
    posix = db_path.as_posix()
    # UNC（//host/share/...）はURIでは file:////host/share/... と書く
    uri = f"file://{posix}" if posix.startswith("//") else f"file:{posix}"
    return f"{uri}?mode=ro"


DEFAULT_REVIEW_DIR = "midterm_duplicate_review"


def default_out_path(db_path: Path, now: datetime.datetime) -> Path:
    """SQLiteファイルと同じ場所の midterm_duplicate_review/review_<日時>.json（日時はローカル時刻）。"""
    return db_path.parent / DEFAULT_REVIEW_DIR / f"review_{now.astimezone():%Y%m%d_%H%M%S}.json"


def resolve_db_path(db_path: Path | None, env=None) -> Path:
    """--db-pathがなければSQLITE_DB_URL（パイプラインと同じDB）のファイルパスを使う。"""
    if db_path is not None:
        return db_path
    env = os.environ if env is None else env
    url = env.get("SQLITE_DB_URL")
    if not url:
        raise ValueError("--db-pathを指定するか、SQLITE_DB_URLを設定してください")
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or not parsed.database:
        raise ValueError(f"SQLITE_DB_URLがSQLiteのファイルを指していません: {url}")
    return Path(parsed.database)


def readonly_engine(db_path: Path):
    uri = sqlite_readonly_uri(db_path)
    return create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True), future=True)


def export_review(db_path: Path, out_path: Path | None = None, urls=None, clock=None) -> tuple[dict, Path]:
    """レビュー用JSONを書き、(内容, 出力先)を返す。out_pathがNoneならdefault_out_path。"""
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
    out_path = out_path or default_out_path(db_path, now)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return document, out_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, help="省略時は.envのSQLITE_DB_URL")
    parser.add_argument("--out", type=Path, help=f"省略時は<SQLiteと同じ場所>/{DEFAULT_REVIEW_DIR}/review_<日時>.json")
    parser.add_argument("--urls", default="", help="カンマ区切り。省略時はextraction_status=okの全文書")
    args = parser.parse_args()
    load_dotenv()

    urls = [u.strip() for u in args.urls.split(",") if u.strip()]
    document, out_path = export_review(resolve_db_path(args.db_path), args.out, urls=urls or None)
    entries = document["entries"]
    for entry in entries:
        print(f"{entry['code']} {entry['disclosure_date']} 候補{len(entry['candidates'])}件 "
              f"version={entry['adopted_version_id']} {entry['url']}")
        for candidate in entry["candidates"]:
            print(f"  - {candidate['candidate_id']} {','.join(candidate['reasons'])}: {candidate['detail']}")
    print(f"重複候補のある文書 {len(entries)}件 / 候補 {sum(len(e['candidates']) for e in entries)}件 → {out_path}")


if __name__ == "__main__":
    main()
