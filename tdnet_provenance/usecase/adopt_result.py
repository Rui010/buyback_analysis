"""抽出結果のversion保存と採用切替（tdnet-provenance-v1 §4.6・§5）。

現行結果テーブル（midterm_plans等）は「現在の採用値」として扱い、次を1トランザクションで行う。

1. そのURLの版がまだなければ、現行行をlegacy版として退避する（failed行だけなら退避しない）
2. 現行行を削除して新しい結果を書く（replace_current=Falseなら削除せず追記）
3. 書いた行をそのまま新しい版としてresult_versionsへ、採用をresult_adoptionsへ追記する

どこかで失敗したらrollbackし、現行行（旧採用）をそのまま残す。
"""

import datetime
import json
from collections.abc import Callable, Sequence
from uuid import uuid4

from buyback_analysis.interface.logger import Logger
from tdnet_provenance.models.result_adoption import ResultAdoption
from tdnet_provenance.models.result_version import ResultVersion

logger = Logger()


class _WriteFailed(Exception):
    pass


def _row_dict(row) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name != "id"}


def snapshot_current(session, tables: Sequence, url: str) -> dict[str, list[dict]]:
    """現行結果テーブルのそのURLの行を {テーブル名: [行dict, ...]} で返す（順序は内容で固定）。"""
    snapshot = {}
    for model in tables:
        rows = [_row_dict(r) for r in session.query(model).filter(model.url == url).all()]
        snapshot[model.__tablename__] = sorted(rows, key=lambda r: json.dumps(r, ensure_ascii=False, sort_keys=True))
    return snapshot


def has_current(session, tables: Sequence, url: str) -> bool:
    primary = tables[0]
    return session.query(primary).filter(primary.url == url).first() is not None


def current_is_failed(session, tables: Sequence, url: str) -> bool:
    """現行の主テーブル行があり、すべてextraction_status=failedならTrue（=今回の処理はretry）。"""
    primary = tables[0]
    rows = session.query(primary).filter(primary.url == url).all()
    return bool(rows) and all(r.extraction_status == "failed" for r in rows)


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def adopt_result(
    session,
    *,
    result_type: str,
    tables: Sequence,
    url: str,
    code: str,
    extraction_status: str | None,
    run_ids: Sequence[str],
    write_current: Callable[[], bool],
    clock: Callable[[], datetime.datetime],
    replace_current: bool = True,
) -> bool:
    """新しい結果を版として保存し採用する。write_currentはcommitせずに現行テーブルへ書き、成否を返すこと。"""
    now = clock().isoformat()
    try:
        has_version = (
            session.query(ResultVersion.version_id)
            .filter(ResultVersion.url == url, ResultVersion.result_type == result_type)
            .first()
            is not None
        )
        if not has_version:
            legacy = snapshot_current(session, tables, url)
            primary_rows = legacy[tables[0].__tablename__]
            if any(r.get("extraction_status") != "failed" for r in primary_rows):
                session.add(ResultVersion(
                    version_id=str(uuid4()), url=url, code=primary_rows[0]["code"], result_type=result_type,
                    extraction_status=primary_rows[0].get("extraction_status"), payload=_dumps(legacy),
                    run_ids="[]", origin="legacy", created_at=now,
                ))

        if replace_current:
            for model in reversed(tables):
                session.query(model).filter(model.url == url).delete(synchronize_session="fetch")
        if not write_current():
            raise _WriteFailed()

        version = ResultVersion(
            version_id=str(uuid4()), url=url, code=code, result_type=result_type,
            extraction_status=extraction_status, payload=_dumps(snapshot_current(session, tables, url)),
            run_ids=_dumps(list(run_ids)), origin="run", created_at=now,
        )
        session.add(version)
        session.add(ResultAdoption(
            adoption_id=str(uuid4()), url=url, result_type=result_type,
            version_id=version.version_id, adopted_at=now,
        ))
        session.commit()
        logger.info(f"[Provenance] 採用版を切り替えました [{result_type}]: {url} version={version.version_id}")
        return True
    except Exception as exc:
        session.rollback()
        reason = "現行テーブルへの書き込み失敗" if isinstance(exc, _WriteFailed) else repr(exc)
        logger.error(f"[Provenance] 採用版を切り替えられませんでした（旧採用を維持）[{result_type}]: {url} {reason}")
        return False


def write_failure_placeholder(session, *, tables: Sequence, url: str, write_failed: Callable[[], bool]) -> bool:
    """新抽出の失敗時。現行行があれば旧採用を維持して何も書かず、なければ従来どおりfailed行を書く。"""
    if has_current(session, tables, url):
        logger.info(f"[Provenance] 抽出に失敗したため旧採用を維持します: {url}")
        return True
    return write_failed()


def require_provenance_for_rerun(recorder, rerun_urls: Sequence[str]) -> None:
    """RERUNは旧結果を版として残すため、provenance有効時だけ許可する。"""
    if rerun_urls and recorder is None:
        raise RuntimeError(
            "RERUN_URLSを使うにはTDNET_PROVENANCE_ENABLED=trueが必要です（旧結果を削除せず版として残すため）"
        )
